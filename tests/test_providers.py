"""All transports here are STAND-INS with authored responses. They prove validation, journaling and
accounting mechanics only; they say nothing about any real model's behavior."""
import json

import pytest

from qjig.budgets import BudgetLedger
from qjig.contracts import Budget
from qjig.journal import Journal, UncertainOutcome
from qjig.logic import Outcome
from qjig.providers import (
    FieldSpec, ProviderRequest, ProviderUnavailable, RawResponse, StandInTransport, call_typed, unresolved_observation,
)

SCHEMA = {"outcome": FieldSpec(str, enum=("true", "false", "unknown", "conflict")), "reason": FieldSpec(str)}
REQ = ProviderRequest(stage="judge", provider="stand-in", model="stand-in-model", prompt="Is it?", max_tokens=50)
GOOD = json.dumps({"outcome": "true", "reason": "quoted"})
USAGE = {"prompt_tokens": 5, "completion_tokens": 2, "cost_usd": 0.0}


def setup(tmp_path, responses, calls=5):
    j = Journal.open(tmp_path / "j.sqlite")
    return j, BudgetLedger(Budget(calls, 1000, 1.0), j, "req-1"), StandInTransport(responses)


def test_malformed_is_unknown(tmp_path):
    j, ledger, t = setup(tmp_path, [RawResponse(200, "Sure! The answer is yes.", USAGE)])
    with j:
        r = call_typed(ledger, t, REQ, SCHEMA)
        # HTTP success with unusable output is a failure, never a value
        assert r.ok is False and r.value is None and r.failure == "malformed_output"
        obs = unresolved_observation(r)
        assert obs.outcome is Outcome.UNKNOWN and obs.reason == "provider_malformed_output"
        # a receipt is retained, with the raw output and its hash, and the call still counts
        (receipt,) = [e for e in j.events("req-1") if e.kind == "receipt"]
        assert receipt.payload["raw_response"] == "Sure! The answer is yes."
        assert receipt.payload["validation"] == "malformed_output" and receipt.payload["http_status"] == 200
        assert len(receipt.payload["raw_sha256"]) == 64 and receipt.payload["usage"] == USAGE
        assert ledger.used_calls() == 1 and r.call_id == receipt.call_id
        assert t.label.startswith("STAND_IN") and t.calls_made == 1


def test_other_invalid_outputs_and_the_valid_path(tmp_path):
    cases = [
        (RawResponse(200, json.dumps({"outcome": "maybe", "reason": "x"}), USAGE), "schema_violation"),
        (RawResponse(200, json.dumps({"outcome": "true"}), USAGE), "schema_violation"),  # missing field
        (RawResponse(200, json.dumps({"outcome": "true", "reason": "x", "extra": 1}), USAGE), "schema_violation"),
        (RawResponse(200, json.dumps(["not", "an", "object"]), USAGE), "schema_violation"),
        (RawResponse(500, "upstream error", USAGE), "http_error"),
        (RawResponse(429, "", USAGE), "http_error"),
    ]
    j, ledger, t = setup(tmp_path, [c[0] for c in cases] + [RawResponse(200, GOOD, USAGE)], calls=10)
    with j:
        for _, expected in cases:
            r = call_typed(ledger, t, REQ, SCHEMA)
            assert (r.ok, r.failure) == (False, expected)
            assert unresolved_observation(r).reason == f"provider_{expected}"
        good = call_typed(ledger, t, REQ, SCHEMA)
        assert good.ok and good.value == {"outcome": "true", "reason": "quoted"} and good.failure is None
        assert unresolved_observation(good) is None
        assert ledger.used_calls() == 7  # every attempt, failed or not


def test_timeout_is_uncertain_and_refusal_to_connect_is_a_definite_failure(tmp_path):
    j, ledger, t = setup(tmp_path, [TimeoutError("read timed out"), ProviderUnavailable("connection refused")])
    with j:
        with pytest.raises(UncertainOutcome):
            call_typed(ledger, t, REQ, SCHEMA)
        assert [e.kind for e in j.events("req-1")] == ["intent", "uncertain"]
        other = ProviderRequest("judge", "stand-in", "stand-in-model", "different prompt", 50)
        from qjig.budgets import BudgetExceeded
        with pytest.raises(BudgetExceeded):
            call_typed(ledger, t, other, SCHEMA)
        other_ledger = BudgetLedger(Budget(2, 1000, 1), j, "req-2")
        with pytest.raises(ProviderUnavailable):
            call_typed(other_ledger, t, other, SCHEMA)
        assert [e.kind for e in j.events("req-2")] == ["intent", "failure"]
        assert ledger.used_calls() == 1 and other_ledger.used_calls() == 1


def test_exhausted_stand_in_and_unbudgeted_calls_never_reach_the_transport(tmp_path):
    j, ledger, t = setup(tmp_path, [], calls=1)
    with j:
        with pytest.raises(AssertionError):
            call_typed(ledger, t, REQ, SCHEMA)  # stand-in has no authored response left
    j2 = Journal.open(tmp_path / "k.sqlite")
    with j2:
        from qjig.budgets import BudgetExceeded

        t2 = StandInTransport([RawResponse(200, GOOD, USAGE)])
        with pytest.raises(BudgetExceeded):
            call_typed(BudgetLedger(None, j2, "req-2"), t2, REQ, SCHEMA)
        assert t2.calls_made == 0 and j2.events("req-2") == []


# --- T046: the real adapter. The HTTP layer below is a labeled FAKE used only to test request shaping, parsing and
# labeling offline; the actual network path is exercised by scripts/smoke_t046.py, which is opt-in and live. ---
from qjig.providers import OpenRouterTransport, load_env_value  # noqa: E402

LIVE_BODY = json.dumps({
    "choices": [{"message": {"content": GOOD}}],
    "usage": {"prompt_tokens": 11, "completion_tokens": 7, "cost": 0.0002},
})


def _env(tmp_path, text="OPENROUTER_API_KEY=sk-test-SECRET\nBASE_URL=https://openrouter.ai/api/v1\n"):
    p = tmp_path / ".env"
    p.write_text(text)
    return p


def test_real_adapter_smoke_contract(tmp_path):
    seen = {}

    def fake_post(url, headers, payload, timeout):
        seen.update(url=url, headers=headers, payload=json.loads(payload), timeout=timeout)
        return 200, LIVE_BODY

    t = OpenRouterTransport(_env(tmp_path), post=fake_post)
    # successful path: labeled live, content extracted, usage reported with its source fields
    assert t.label == "LIVE: openrouter, real model call"
    raw = t.send(ProviderRequest("judge", "openrouter", "vendor/model-x", "Is it?", 50))
    assert raw.http_status == 200 and raw.body == GOOD
    assert raw.usage == {"prompt_tokens": 11, "completion_tokens": 7, "cost_usd": 0.0002}
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["payload"]["model"] == "vendor/model-x" and seen["payload"]["max_tokens"] == 50
    assert seen["payload"]["messages"] == [{"role": "user", "content": "Is it?"}]
    assert seen["headers"]["Authorization"] == "Bearer sk-test-SECRET"
    assert "SECRET" not in repr(t)

    # cost not reported -> unknown, never zero
    t2 = OpenRouterTransport(_env(tmp_path), post=lambda *a: (200, json.dumps({"choices": [{"message": {"content": "x"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}})))
    assert t2.send(REQ).usage["cost_usd"] is None
    # non-2xx is returned as a failure response, with no usage invented
    t3 = OpenRouterTransport(_env(tmp_path), post=lambda *a: (429, "rate limited"))
    r = t3.send(REQ)
    assert (r.http_status, r.body, r.usage) == (429, "rate limited", None)
    # a 200 whose envelope has no choices is kept as raw text so the typed layer records the failure
    # a 200 with no message content (e.g. a reasoning model that spent its whole token cap) is an empty body
    # with the observed cause recorded, so the typed layer fails it as malformed rather than mislabeling it
    empty = json.dumps({"choices": [{"finish_reason": "length", "message": {"content": None}}], "usage": {"prompt_tokens": 3, "completion_tokens": 50}})
    r4 = OpenRouterTransport(_env(tmp_path), post=lambda *a: (200, empty)).send(REQ)
    assert r4.body == "" and r4.note == "no_message_content; finish_reason=length" and r4.usage["completion_tokens"] == 50

    # unavailable path: no key means the request never leaves; the HTTP layer is not touched
    called = []
    t5 = OpenRouterTransport(_env(tmp_path, "BASE_URL=x\n"), post=lambda *a: called.append(1))
    with pytest.raises(ProviderUnavailable, match="OPENROUTER_API_KEY"):
        t5.send(REQ)
    assert called == []
    with pytest.raises(ProviderUnavailable):
        OpenRouterTransport(tmp_path / "missing.env", post=lambda *a: called.append(1)).send(REQ)
    # connection refused happens before anything is sent
    def refuse(*a):
        raise ConnectionRefusedError("no route")
    with pytest.raises(ProviderUnavailable):
        OpenRouterTransport(_env(tmp_path), post=refuse).send(REQ)
    # a timeout after sending is outcome-unknown and is left for the journal to treat as uncertain
    def slow(*a):
        raise TimeoutError("read timed out")
    with pytest.raises(TimeoutError):
        OpenRouterTransport(_env(tmp_path), post=slow).send(REQ)
    assert load_env_value(_env(tmp_path), "BASE_URL") == "https://openrouter.ai/api/v1"
    assert load_env_value(_env(tmp_path), "NOPE") is None


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_redirect_never_forwards_authorization(status):
    """Real local HTTP servers, dummy credential only; no hosted call."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from qjig.providers import _urllib_post

    received = []
    class Destination(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()
        def do_GET(self):
            received.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()
        def log_message(self, *args):
            pass
    destination = ThreadingHTTPServer(("127.0.0.1", 0), Destination)
    class Redirect(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(status)
            self.send_header("Location", f"http://127.0.0.1:{destination.server_port}/")
            self.end_headers()
        def log_message(self, *args):
            pass
    redirect = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    threads = [Thread(target=s.serve_forever, daemon=True) for s in (destination, redirect)]
    for thread in threads:
        thread.start()
    try:
        result, _ = _urllib_post(f"http://127.0.0.1:{redirect.server_port}/", {"Authorization": "Bearer DUMMY"}, "{}", 2)
        assert result == status
        assert received == []
    finally:
        for server in (redirect, destination):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join()


@pytest.mark.parametrize("base", ["http://openrouter.ai/api/v1", "https://evil.example/api/v1", "https://openrouter.ai.evil.example/api/v1", "https://user@openrouter.ai/api/v1", "https://openrouter.ai/api/v1?key=bad"])
def test_reject_untrusted_provider_endpoint(tmp_path, base):
    sent = []
    transport = OpenRouterTransport(_env(tmp_path, f"OPENROUTER_API_KEY=dummy\nBASE_URL={base}\n"), post=lambda *args: sent.append(args))
    with pytest.raises(ProviderUnavailable):
        transport.send(REQ)
    assert not sent


@pytest.mark.parametrize("kind", ["http_error", "timeout", "connection", "unexpected"])
def test_provider_secrets_do_not_reach_journal_or_errors(tmp_path, kind):
    """Fake HTTP responses and exceptions intentionally echo a dummy credential."""
    secret = "sk-dummy-secret-value"
    env = _env(tmp_path, f"OPENROUTER_API_KEY={secret}\nBASE_URL=https://openrouter.ai/api/v1\n")
    def post(*args):
        if kind == "http_error":
            return 500, f"upstream echoed {secret}"
        if kind == "timeout":
            raise TimeoutError(f"request echoed {secret}")
        if kind == "connection":
            raise ConnectionRefusedError(f"request echoed {secret}")
        raise RuntimeError(f"request echoed {secret}")
    adapter = OpenRouterTransport(env, post=post)
    class FakeHTTPAdapter:
        label = "STAND_IN: injected fake HTTP"
        def send(self, request):
            return adapter.send(request)
    transport = FakeHTTPAdapter()
    with Journal.open(tmp_path / "receipt.sqlite") as journal:
        ledger = BudgetLedger(Budget(2, 1000, 1), journal, "safety")
        try:
            call_typed(ledger, transport, REQ, SCHEMA)
        except Exception as exc:
            assert secret not in str(exc)
        events = journal.events("safety")
        assert secret not in repr(events)
        assert events[-1].kind == {"http_error": "receipt", "timeout": "uncertain", "connection": "failure", "unexpected": "uncertain"}[kind]
        assert bool(journal.pending("safety")) == (kind in ("timeout", "unexpected"))


def test_live_provider_without_complete_preflight_never_dispatches(tmp_path):
    """Injected fake HTTP and dummy credential: incomplete budgeting must refuse before an intent."""
    from qjig.budgets import BudgetExceeded
    seen = []
    transport = OpenRouterTransport(_env(tmp_path), post=lambda *args: seen.append(args))
    with Journal.open(tmp_path / "preflight.sqlite") as journal:
        ledger = BudgetLedger(Budget(5, 10000, 1), journal, "preflight")
        with pytest.raises(BudgetExceeded):
            call_typed(ledger, transport, REQ, SCHEMA)
        assert seen == [] and journal.events("preflight") == []


def test_bound_reservation_rejects_changed_request_and_reaches_goal_ledger(tmp_path):
    """Synthetic pricing, input bound and stand-in response; no hosted call."""
    from qjig.goal_budget import GoalBudget
    from qjig.providers import make_call_reservation
    from qjig.contracts import ContractError

    model = {"id": REQ.model, "context_length": 1000, "top_provider": {"max_completion_tokens": 100},
             "pricing": {"prompt": "0.001", "completion": "0.001"}}
    bound = make_call_reservation(REQ, model, input_tokens=100, input_bound_provenance="synthetic fixture")
    limit = Budget(2, 500, 1)
    with GoalBudget.open(tmp_path / "goal.sqlite", total=limit, per_request=limit, allocations={"smoke": limit}) as goal, Journal.open(tmp_path / "j.sqlite") as journal:
        ledger = BudgetLedger(limit, journal, "r", goal_budget=goal, partition="smoke")
        transport = StandInTransport([RawResponse(200, GOOD, USAGE)])
        changed_requests = [ProviderRequest(REQ.stage, REQ.provider, REQ.model, REQ.prompt + " changed", REQ.max_tokens),
                            ProviderRequest(REQ.stage, REQ.provider, "other-model", REQ.prompt, REQ.max_tokens),
                            ProviderRequest(REQ.stage, REQ.provider, REQ.model, REQ.prompt, REQ.max_tokens + 1)]
        for changed in changed_requests:
            with pytest.raises(ContractError):
                call_typed(ledger, transport, changed, SCHEMA, reservation=bound)
        assert goal.totals().max_calls == 0 and transport.calls_made == 0
        result = call_typed(ledger, transport, REQ, SCHEMA, reservation=bound)
        assert result.ok and goal.totals().max_tokens == 150
        intent = journal.events("r")[0]
        assert intent.payload["reservation_binding"]["request_sha256"] == REQ.input_sha256()
        assert intent.payload["reservation_binding"]["pricing_sha256"] == bound.pricing_sha256
