"""Synthetic stand-in run; replay makes no provider calls or quality claims."""
import sqlite3
import pytest
from qjig.acquisition import run_fresh
from qjig.applicability import Applicability, ApplicabilityInputs, Collection, Interval, MemberMetadata, OPEN
from qjig.budgets import BudgetLedger
from qjig.contracts import Budget, Request
from qjig.indexing import current_entries, index_entries, save_entries
from qjig.journal import Journal
from qjig.providers import RawResponse, StandInTransport
from qjig.run_archive import RunArchive
from qjig.sources import SourceRevision, decode_source
from qjig.store import Catalog
from qjig.replay import verify_archive


def make_archive(tmp_path, positive=None, negative=None, predicate_question="refund fourteen?", **run_options):
    source = SourceRevision.create("synthetic/rules.md", "synthetic", decode_source(b"# Rules\nRefunds within fourteen days.\n", encoding="utf-8"))
    request = Request("r", "refund fourteen?", "reviewer", "1", "project")
    usage = {"prompt_tokens": 5, "completion_tokens": 3, "cost_usd": 0.0}
    import json
    planner = json.dumps({'predicates': [{'id': 'p1', 'question': predicate_question}], 'expression': {'ref': 'p1'}})
    transport = StandInTransport([RawResponse(200, planner, usage),
                                  RawResponse(200, positive or '{"supported":false,"quote":"","reason":"none"}', usage),
                                  RawResponse(200, negative or '{"supported":false,"quote":"","reason":"none"}', usage)])
    directory = tmp_path / "run"
    with Catalog.open(tmp_path / "c.sqlite") as catalog, Journal.open(tmp_path / "j.sqlite") as journal, RunArchive.open(directory) as archive:
        catalog.add_revision(source)
        catalog.put_metadata_row((source.revision_id, "project", None, "[]", "2026-01-01", "open", None))
        save_entries(catalog, index_entries(source))
        ledger = BudgetLedger(Budget(5, 50000, 1), journal, "r")
        inputs = ApplicabilityInputs(Collection((MemberMetadata(source.revision_id, "project", Interval("2026-01-01", OPEN)),)), frozenset(), "2026-11-15", False)
        result = run_fresh(request=request, catalog=catalog, entries=current_entries(catalog, source.source_id, source.revision_id),
                           ledger=ledger, transport=transport, planner=("stand-in", "planner"), judge=("stand-in", "judge"),
                           revision_applicability=lambda _: Applicability.MATCH, applicability_inputs=inputs, archive=archive, **run_options)
        assert result.status == "deferred"
    return directory, transport.calls_made


def test_replay_validates_fresh_retrieval_followup(tmp_path):
    import json
    directory, calls = make_archive(tmp_path, predicate_question='zephyr eligibility')
    assert calls == 3
    with RunArchive.open(directory) as archive:
        report = verify_archive(archive)
        assert report.status == 'unanchored' and report.checked_traces == 2
        assert verify_archive(archive, expected_digest=report.digest).status == 'structurally_verified'
    with sqlite3.connect(directory / 'run.sqlite') as con:
        con.execute('DROP TRIGGER event_no_update')
        seq, raw = con.execute("SELECT seq,data FROM events WHERE kind='trace' ORDER BY seq DESC LIMIT 1").fetchone()
        changed = json.loads(raw)
        changed['query'] = 'unrelated search'
        con.execute('UPDATE events SET data=? WHERE seq=?', (json.dumps(changed), seq))
    with RunArchive.open(directory) as archive:
        assert verify_archive(archive).status == 'invalid'
    with sqlite3.connect(directory / 'run.sqlite') as con:
        con.execute('DROP TRIGGER event_no_update')
        changed['query'] = 'refund fourteen?'
        con.execute('UPDATE events SET data=? WHERE seq=?', (json.dumps(changed), seq))
        seq, raw = con.execute("SELECT seq,data FROM events WHERE kind='trace' ORDER BY seq LIMIT 1").fetchone()
        first = json.loads(raw)
        first['observation']['reason'] = 'provider_timeout'
        con.execute('UPDATE events SET data=? WHERE seq=?', (json.dumps(first), seq))
    with RunArchive.open(directory) as archive:
        assert verify_archive(archive).status == 'invalid'


def test_fresh_run_binds_routing_ceilings_to_requests_and_replay(tmp_path):
    planner_cap = {'prompt': 1.0, 'completion': 2.0}
    judge_cap = {'prompt': 3.0, 'completion': 4.0}
    directory, calls = make_archive(tmp_path, planner_max_price=planner_cap, judge_max_price=judge_cap)
    assert calls == 3
    with RunArchive.open(directory) as archive:
        requests = [e['data'] for e in archive.events() if e['kind'] == 'request']
        assert [r['max_price'] for r in requests] == [planner_cap, judge_cap, judge_cap]
        assert verify_archive(archive).status == 'unanchored'
    import json
    from qjig.providers import ProviderRequest
    with sqlite3.connect(directory / 'run.sqlite') as con:
        con.execute('DROP TRIGGER event_no_update')
        seq, raw = con.execute("SELECT seq,data FROM events WHERE kind='request' ORDER BY seq LIMIT 1").fetchone()
        changed = json.loads(raw)
        changed['max_price']['prompt'] = 9
        changed['input_sha256'] = ProviderRequest(changed['stage'], changed['provider'], changed['model'],
                                                  changed['prompt'], changed['max_tokens'], max_price=changed['max_price']).input_sha256()
        con.execute('UPDATE events SET data=? WHERE seq=?', (json.dumps(changed), seq))
    with RunArchive.open(directory) as archive:
        assert verify_archive(archive).status == 'invalid'


def test_archive_replay_detects_changed_evidence_without_inference(tmp_path, monkeypatch):
    directory, calls = make_archive(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError("replay attempted inference")
    monkeypatch.setattr(StandInTransport, "send", forbidden)
    with RunArchive.open(directory) as archive:
        initial = verify_archive(archive)
        assert initial.status == "unanchored" and not initial.issues
        replay = verify_archive(archive, expected_digest=initial.digest)
        assert replay.status == "structurally_verified" and replay.checked_traces == 1
    assert calls == 3  # replay did not invoke the stand-in
    # Deliberately bypass a SQLite guard in a temporary fixture to test detection.
    with sqlite3.connect(directory / "run.sqlite") as con:
        con.execute("DROP TRIGGER revision_no_update")
        con.execute("UPDATE revisions SET raw=?", (b"tampered",))
    with RunArchive.open(directory) as archive:
        changed = verify_archive(archive, expected_digest=initial.digest)
        assert changed.status == "invalid" and changed.issues


def test_replay_reports_interrupted_request_as_incomplete(tmp_path):
    directory = tmp_path / "partial"
    with RunArchive.open(directory) as archive:
        archive.record_context({"schema": "qjig.fresh-context.v1", "corpus": {}})
        archive.record_request("r#1", __import__("qjig.providers", fromlist=["ProviderRequest"]).ProviderRequest("planner", "stand-in", "m", "question", 20))
        report = verify_archive(archive)
        assert report.status == "incomplete"
        assert "pending_request:r#1" in report.issues


def test_replay_rejects_tampered_trace_and_response(tmp_path):
    import json
    directory, _ = make_archive(tmp_path)
    with RunArchive.open(directory) as archive:
        digest = verify_archive(archive).digest
    with sqlite3.connect(directory / "run.sqlite") as con:
        con.execute("DROP TRIGGER event_no_update")
        seq, raw = con.execute("SELECT seq,data FROM events WHERE kind='trace'").fetchone()
        trace = json.loads(raw)
        trace["evidence"][0]["text"] = "fabricated"
        con.execute("UPDATE events SET data=? WHERE seq=?", (json.dumps(trace), seq))
        seq, raw = con.execute("SELECT seq,data FROM events WHERE kind='response' LIMIT 1").fetchone()
        response = json.loads(raw)
        response["body"] = "changed"
        con.execute("UPDATE events SET data=? WHERE seq=?", (json.dumps(response), seq))
    with RunArchive.open(directory) as archive:
        report = verify_archive(archive, expected_digest=digest)
        assert report.status == "invalid"
        assert "archive_digest_mismatch" in report.issues
        assert any(issue.startswith("invalid_trace:") for issue in report.issues)
        assert any(issue.startswith("invalid_response:") for issue in report.issues)


def test_replay_checks_planning_packet_even_if_context_hash_is_rewritten(tmp_path):
    import hashlib
    import json

    directory, _ = make_archive(tmp_path)
    with RunArchive.open(directory) as archive:
        digest = verify_archive(archive).digest
    with sqlite3.connect(directory / "run.sqlite") as con:
        con.execute("DROP TRIGGER context_no_update")
        (raw,) = con.execute("SELECT data FROM run_context WHERE id=1").fetchone()
        context = json.loads(raw)
        context["planning_evidence"]["packet"]["items"][0]["text"] = "fabricated"
        encoded = json.dumps(context, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        con.execute("UPDATE run_context SET data=?, sha256=? WHERE id=1", (encoded, hashlib.sha256(encoded.encode()).hexdigest()))
    with RunArchive.open(directory) as archive:
        report = verify_archive(archive, expected_digest=digest)
        assert report.status == "invalid"
        assert "invalid_planning_or_applicability" in report.issues
        assert "archive_digest_mismatch" in report.issues


def test_replay_requires_final_run_record(tmp_path):
    directory, _ = make_archive(tmp_path)
    # Remove a final record if present, simulating interruption after the last trace.
    with sqlite3.connect(directory / "run.sqlite") as con:
        con.execute("DROP TRIGGER event_no_delete")
        con.execute("DELETE FROM events WHERE kind='run_result'")
    with RunArchive.open(directory) as archive:
        snapshot = verify_archive(archive)
        assert snapshot.status == "incomplete"
        assert "missing_run_result" in snapshot.issues


def test_replay_rejects_result_that_disagrees_with_archived_plan(tmp_path):
    import json
    directory, _ = make_archive(tmp_path)
    with sqlite3.connect(directory / "run.sqlite") as con:
        con.execute("DROP TRIGGER event_no_update")
        seq, raw = con.execute("SELECT seq,data FROM events WHERE kind='run_result'").fetchone()
        result = json.loads(raw)
        result["expression"] = {"op": "not", "args": [{"ref": "p1"}]}
        con.execute("UPDATE events SET data=? WHERE seq=?", (json.dumps(result), seq))
    with RunArchive.open(directory) as archive:
        report = verify_archive(archive)
        assert report.status == "invalid"
        assert any(item.startswith("invalid_run_result:") for item in report.issues)


def test_replay_rejects_rehashed_judge_prompt_and_changed_validation(tmp_path):
    import json
    from qjig.providers import ProviderRequest

    directory, _ = make_archive(tmp_path)
    with sqlite3.connect(directory / "run.sqlite") as con:
        con.execute("DROP TRIGGER event_no_update")
        rows = con.execute("SELECT seq,call_id,data FROM events WHERE kind='request'").fetchall()
        seq, call_id, raw = next(row for row in rows if json.loads(row[2])["stage"] == "judge_positive")
        request = json.loads(raw)
        request["prompt"] = request["prompt"].replace("Refunds within fourteen days", "Unrelated altered passage")
        rebuilt = ProviderRequest(request["stage"], request["provider"], request["model"], request["prompt"], request["max_tokens"])
        request["input_sha256"] = rebuilt.input_sha256()
        con.execute("UPDATE events SET data=? WHERE seq=?", (json.dumps(request), seq))
        seq, raw = con.execute("SELECT seq,data FROM events WHERE kind='validation' AND call_id=?", (call_id,)).fetchone()
        validation = json.loads(raw)
        validation["value"]["supported"] = True
        con.execute("UPDATE events SET data=? WHERE seq=?", (json.dumps(validation), seq))
    with RunArchive.open(directory) as archive:
        report = verify_archive(archive)
        assert report.status == "invalid"
        assert any(issue.startswith("invalid_judge_binding:") for issue in report.issues)
        assert any(issue.startswith("invalid_validation:") for issue in report.issues)


def test_replay_rejects_jointly_fabricated_judge_outcome(tmp_path):
    import json
    directory, _ = make_archive(tmp_path)
    with sqlite3.connect(directory / "run.sqlite") as con:
        con.execute("DROP TRIGGER event_no_update")
        seq, raw = con.execute("SELECT seq,data FROM events WHERE kind='trace'").fetchone()
        trace = json.loads(raw)
        trace["observation"] = {"outcome": "true", "reason": "judge_positive_supported"}
        con.execute("UPDATE events SET data=? WHERE seq=?", (json.dumps(trace), seq))
        seq, raw = con.execute("SELECT seq,data FROM events WHERE kind='run_result'").fetchone()
        result = json.loads(raw)
        result["observations"]["p1"] = trace["observation"]
        con.execute("UPDATE events SET data=? WHERE seq=?", (json.dumps(result), seq))
    with RunArchive.open(directory) as archive:
        report = verify_archive(archive)
        assert report.status == "invalid"
        assert any(item.startswith("invalid_judge_outcome:") for item in report.issues)


@pytest.mark.parametrize("positive,negative,expected", [
    ('{"supported":true,"quote":"Refunds within fourteen days.","reason":"source"}', '{"supported":false,"quote":"","reason":"none"}', "true"),
    ('{"supported":true,"quote":"Refunds within fourteen days.","reason":"source"}', '{"supported":true,"quote":"Refunds within fourteen days.","reason":"source"}', "conflict"),
    ('{"supported":true,"quote":"not in source","reason":"fabricated"}', '{"supported":false,"quote":"","reason":"none"}', "unknown"),
])
def test_replay_recomputes_quoted_judge_outcomes(tmp_path, positive, negative, expected):
    directory, _ = make_archive(tmp_path, positive, negative)
    with RunArchive.open(directory) as archive:
        report = verify_archive(archive)
        assert report.status == "unanchored" and not report.issues
        trace = next(e["data"] for e in archive.events() if e["kind"] == "trace")
        assert trace["observation"]["outcome"] == expected
        assert report.semantic_assurance == "not_assessed"


def test_replay_rejects_tampered_source_scope_even_if_context_hash_rewritten(tmp_path):
    import hashlib
    import json

    directory, _ = make_archive(tmp_path)
    with sqlite3.connect(directory / "run.sqlite") as con:
        con.execute("DROP TRIGGER context_no_update")
        (raw,) = con.execute("SELECT data FROM run_context WHERE id=1").fetchone()
        context = json.loads(raw)
        revision_id = next(iter(context["source_scopes"]))
        context["source_scopes"][revision_id] = "different-project"
        encoded = json.dumps(context, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        con.execute("UPDATE run_context SET data=?, sha256=? WHERE id=1", (encoded, hashlib.sha256(encoded.encode()).hexdigest()))
    with RunArchive.open(directory) as archive:
        report = verify_archive(archive)
        assert report.status == "invalid" and "invalid_planning_or_applicability" in report.issues


def test_replay_rejects_changed_routing_ceiling(tmp_path):
    import json
    from qjig.providers import ProviderRequest

    directory = tmp_path / 'partial'
    with RunArchive.open(directory) as archive:
        archive.record_context({'schema': 'qjig.fresh-context.v1', 'corpus': {}})
        request = ProviderRequest('planner', 'stand-in', 'm', 'question', 20,
                                  max_price={'prompt': 0.5, 'completion': 2.0})
        archive.record_request('r#1', request)
        assert verify_archive(archive).status == 'incomplete'
    with sqlite3.connect(directory / 'run.sqlite') as con:
        con.execute('DROP TRIGGER event_no_update')
        seq, raw = con.execute("SELECT seq,data FROM events WHERE kind='request'").fetchone()
        changed = json.loads(raw)
        changed['max_price']['completion'] = 20
        con.execute('UPDATE events SET data=? WHERE seq=?', (json.dumps(changed), seq))
    with RunArchive.open(directory) as archive:
        report = verify_archive(archive)
        assert report.status == 'invalid'
        assert any(item.startswith('invalid_request:') for item in report.issues)


def test_replay_rejects_response_wire_digest_that_differs_from_request(tmp_path):
    import json
    from qjig.providers import ProviderRequest, OpenRouterTransport
    directory=tmp_path/'partial-wire'
    env=tmp_path/'env'; env.write_text('OPENROUTER_API_KEY=dummy\n')
    request=ProviderRequest('planner','openrouter','vendor/model','question α',20,
                            max_price={'prompt':0.5,'completion':2.0})
    adapter=OpenRouterTransport(env,post=lambda *args:(200,json.dumps({'choices':[{'message':{'content':'{}'}}]})))
    response=adapter._send_unchecked(request)
    with RunArchive.open(directory) as archive:
        archive.record_context({'schema':'qjig.fresh-context.v1','corpus':{}})
        archive.record_request('r#1',request)
        archive.record_response('r#1',response)
        assert verify_archive(archive).status != 'invalid'
    with sqlite3.connect(directory/'run.sqlite') as con:
        con.execute('DROP TRIGGER event_no_update')
        seq,raw=con.execute("SELECT seq,data FROM events WHERE kind='response'").fetchone()
        changed=json.loads(raw);changed['metadata']['wire_payload_sha256']='0'*64
        con.execute('UPDATE events SET data=? WHERE seq=?',(json.dumps(changed),seq))
    with RunArchive.open(directory) as archive:
        report=verify_archive(archive)
        assert report.status=='invalid'
        assert any(issue.startswith('invalid_response:') for issue in report.issues)
    with sqlite3.connect(directory/'run.sqlite') as con:
        con.execute('DROP TRIGGER event_no_update')
        changed['metadata'].pop('wire_payload_format')
        con.execute('UPDATE events SET data=? WHERE seq=?',(json.dumps(changed),seq))
    with RunArchive.open(directory) as archive:
        report=verify_archive(archive)
        assert report.status=='incomplete'
        assert 'wire_payload_format_unavailable:r#1' in report.issues


@pytest.mark.parametrize('version', [1, 2, 3, 4])
def test_replay_accepts_historical_openrouter_wire_receipt(tmp_path, version):
    import hashlib
    from qjig.providers import ProviderRequest, RawResponse, openrouter_wire_payload_v1, openrouter_wire_payload_v2, openrouter_wire_payload_v3, openrouter_wire_payload_v4
    request = ProviderRequest('planner', 'openrouter', 'vendor/model', 'older request', 20,
                              max_price={'prompt': 0.5, 'completion': 2.0})
    serializer = {1:openrouter_wire_payload_v1, 2:openrouter_wire_payload_v2, 3:openrouter_wire_payload_v3, 4:openrouter_wire_payload_v4}[version]
    digest = hashlib.sha256(serializer(request).encode('utf-8')).hexdigest()
    response = RawResponse(200, '{}', None, metadata={'wire_payload_format':f'openrouter.chat.v{version}',
                                                      'wire_payload_sha256':digest})
    with RunArchive.open(tmp_path / 'historical') as archive:
        archive.record_context({'schema':'qjig.fresh-context.v1', 'corpus':{}})
        archive.record_request('r#1', request)
        archive.record_response('r#1', response)
        assert verify_archive(archive).status != 'invalid'


def test_replay_checks_restricted_provider_route_against_wire_digest(tmp_path):
    import hashlib,json
    from qjig.providers import ProviderRequest,RawResponse,openrouter_wire_payload_v5
    request=ProviderRequest('planner','openrouter','vendor/model','question',20,
                            max_price={'prompt':2,'completion':3},route='relace/fp4')
    digest=hashlib.sha256(openrouter_wire_payload_v5(request).encode()).hexdigest()
    with RunArchive.open(tmp_path/'route') as archive:
        archive.record_context({'schema':'qjig.fresh-context.v1','corpus':{}})
        archive.record_request('r#1',request)
        archive.record_response('r#1',RawResponse(200,'{}',None,metadata={
            'wire_payload_format':'openrouter.chat.v5','wire_payload_sha256':digest}))
        assert verify_archive(archive).status!='invalid'
        archive._con.execute('DROP TRIGGER event_no_update')
        seq,encoded=archive._con.execute("SELECT seq,data FROM events WHERE kind='request'").fetchone()
        data=json.loads(encoded);data['route']='relace/fp8'
        changed=ProviderRequest('planner','openrouter','vendor/model','question',20,
                                max_price={'prompt':2,'completion':3},route='relace/fp8')
        data['input_sha256']=changed.input_sha256()
        archive._con.execute('UPDATE events SET data=? WHERE seq=?',(json.dumps(data),seq))
        assert verify_archive(archive).status=='invalid'
        from qjig.providers import openrouter_wire_payload_v4
        seq,encoded=archive._con.execute("SELECT seq,data FROM events WHERE kind='response'").fetchone()
        response=json.loads(encoded);response['metadata']['wire_payload_format']='openrouter.chat.v4'
        response['metadata']['wire_payload_sha256']=hashlib.sha256(openrouter_wire_payload_v4(changed).encode()).hexdigest()
        archive._con.execute('UPDATE events SET data=? WHERE seq=?',(json.dumps(response),seq))
        assert verify_archive(archive).status=='invalid'
