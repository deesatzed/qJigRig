"""Verify the review packet, source fingerprints and pending build DAG; no model calls."""
from pathlib import Path
import hashlib,json,re
ROOT=Path(__file__).resolve().parents[1]
def verify():
    required=['README.md','AGENTS.md','GOAL.md','STANDARDS.md','IMPLEMENT.md','DECISIONS.md','PROGRESS.md','TASK_QUEUE.md','SOURCE_AUDIT.md','SYNTHESIS.md','METHOD_CARDS.md','RISK_REGISTER.md','VALIDATION_REPORT.md','docs/CONTRACTS.md','docs/ALGORITHM.md','docs/TEST_STRATEGY.md','docs/plans/2026-11-06-qjig-build.md']
    for name in required:assert (ROOT/name).is_file(),name
    queue=json.loads((ROOT/'plan/tasks.json').read_text()); tasks=queue['tasks']; by_id={t['id']:t for t in tasks}
    assert len(tasks)==len(by_id)==74
    done=set()
    for task in tasks:
        assert task['status']=='pending',task['id']
        assert set(task['depends_on'])<=done,task['id']
        assert task['test_name'].startswith('test_')
        assert task['test_file'].startswith('tests/') and task['acceptance']
        assert all(p=='pyproject.toml' or p.startswith('src/qjig/') for p in task['files'])
        done.add(task['id'])
    checked=[]
    for folder, names in [('Decision_Program_Codex_Handoff',json.loads((ROOT/'plan/jig-source-hashes.json').read_text())),('sources/quixer',json.loads((ROOT/'plan/quixer-source-hashes.json').read_text()))]:
        for rel,expected in names.items():
            path=ROOT/folder/rel
            assert path.is_file(),str(path)
            assert hashlib.sha256(path.read_bytes()).hexdigest()==expected,str(path)
        checked.append({'source':folder,'files':len(names)})
    # Only new review links; source application historical links can reference ignored local runs.
    for name in required:
        for target in re.findall(r'\]\(([^)]+)\)',(ROOT/name).read_text()):
            if '://' in target or target.startswith('#'):continue
            local=target.split('#',1)[0];local=re.sub(r':\d+$','',local)
            assert (ROOT/Path(name).parent/local).exists(),(name,target)
    return {'schema':'qjig-review-packet-verification-v1','status':'passed','required_documents':len(required),'pending_tasks':len(tasks),'dependency_graph':'acyclic/topologically ordered','checked_sources':checked,'scope':'review packet only; no qJig runtime acceptance'}
if __name__=='__main__':print(json.dumps(verify(),indent=2))
