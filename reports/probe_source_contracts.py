"""Reproduce four source compatibility probes using temporary local data only."""
from pathlib import Path
import os,sys,tempfile,json
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'sources/quixer/src'),str(ROOT/'Decision_Program_Codex_Handoff')]
with tempfile.TemporaryDirectory() as td:
    os.environ['WORKBENCH_DATA']=str(Path(td)/'records')
    from quix_knowledge.store import open_catalog
    from quix_knowledge.ingest import ingest
    from workbench import core,collections
    from workbench.local_judge import combine_support
    p=Path(td)/'crlf.txt';p.write_bytes(b'One\r\nTwo\r\n')
    db=open_catalog(':memory:');ingest(db,p)
    q=db.execute('select revision,body from sources').fetchone()
    j=core.snapshot('raw',p.read_bytes().decode('utf-8'))
    out={'hash_contract':{'quix_hash':q['revision'],'jig_hash':j['sha256'],'same_raw_file_different_hashes':q['revision']!=j['sha256'],'quix_universal_newlines':q['body']=='One\nTwo\n'}}
    a=core.snapshot('old','old policy',scope='project',effective_from='2026-01-01',effective_to='2026-10-31')
    b=core.snapshot('new','new policy',scope='project',effective_from='2026-11-01')
    try:collections.create('versions',[a['id'],b['id']]);out['mixed_date_collection']='accepted'
    except ValueError as e:out['mixed_date_collection']={'rejected':str(e)}
    expr={'op':'or','args':[{'ref':'ordinary'},{'ref':'exception'}]}
    out['unknown_exception']={'ordinary_false_exception_missing':core.stable_outcome(expr,['ordinary','exception'],{'ordinary':False}),'exception_material':core.predicate_relevant(expr,['ordinary','exception'],{'ordinary':False},'exception')}
    out['conflict_preserved']=combine_support('supported','supported');db.close()
    expected=json.loads((ROOT/'reports/compatibility-probes.json').read_text())
    assert out==expected,(out,expected)
    print(json.dumps({'status':'passed','observations':out},indent=2))
