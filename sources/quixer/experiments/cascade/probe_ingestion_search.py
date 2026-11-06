"""Bounded separate real-provider extraction and hybrid search research probe."""
import hashlib,json,sqlite3,time
from pathlib import Path
from quix_knowledge.openrouter import load_settings
from quix_knowledge.research_providers import OpenRouterResearchTransport,CohereSearchEmbedder,extract_metadata
from quix_knowledge.retrieval_study import verify_source_snapshot
from quix_knowledge.retrieve import search
from quix_knowledge.hitm import _check_sources
from quix_knowledge.store import corpus_fingerprint
root=Path(__file__).resolve().parents[2];study=root/'.local/retrieval-study-isolated-v1';manifest=json.loads((root/'experiments/retrieval/manifest.json').read_text());prep=json.loads((study/'preparation.json').read_text());tasks=json.loads((root/'experiments/cascade/manifest-v1.json').read_text())['tasks'];verify_source_snapshot(study,prep,manifest)
db=sqlite3.connect((study/'catalog.db').resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
_check_sources(db)
if corpus_fingerprint(db)!=prep['corpus_revision']:raise ValueError('catalog changed')
settings=load_settings('/Volumes/WS4TB/QUIX/.env',2);transport=OpenRouterResearchTransport(settings.api_key)
text=(root/'experiments/cascade/fixtures/metadata.txt').read_text();fields={'document_title':{'type':'text','instructions':'Extract the document title.'},'owner':{'type':'text','instructions':'Extract the document owner.'},'revision_date':{'type':'date','instructions':'Extract the revision date.'},'missing_author':{'type':'text','instructions':'Extract the author if explicitly present.'}}
start=time.monotonic();extraction=extract_metadata(text,fields,transport);extraction['elapsed_seconds']=time.monotonic()-start;extraction['source_sha256']=hashlib.sha256(text.encode()).hexdigest()
results=[]
for task in tasks:
    encoder=CohereSearchEmbedder(transport);start=time.monotonic()
    try:
        baseline=search(db,task['query'],variant='baseline',limit=3,ranking='bm25',include_generated=False)
        hybrid=search(db,task['query'],variant='baseline',limit=3,ranking='hybrid',embedder=encoder,include_generated=False)
        result={'task_id':task['id'],'status':'ok','baseline_ids':[x['id'] for x in baseline],'hybrid_ids':[x['id'] for x in hybrid],'hybrid_fallback':[x.get('embedding_fallback_reason') for x in hybrid],'receipts':encoder.receipts}
    except Exception as e:result={'task_id':task['id'],'status':'unknown','error_type':type(e).__name__,'receipts':encoder.receipts}
    result['elapsed_seconds']=time.monotonic()-start;results.append(result);print(json.dumps({'task':task['id'],'status':result['status']}),flush=True)
_check_sources(db)
if corpus_fingerprint(db)!=prep['corpus_revision']:raise ValueError('catalog changed during probe')
db.close();verify_source_snapshot(study,prep,manifest)
p=root/'.local/cascade-ingestion-search-20261104-v1.json'
with p.open('x') as f:json.dump({'schema':'quix-cascade-ingestion-search-probe-v1','corpus_revision':prep['corpus_revision'],'metadata_fixture_expected':{'document_title':'Retry Policy','owner':'Platform Team','revision_date':'2026-10-01','missing_author':None},'extraction':extraction,'search':results,'limits':'Unlabeled exploratory comparison on shared sources; no human quality claim. Repeated document embeddings are not cached; costs include repeated calls.'},f,indent=2)
print('extraction',extraction['status'],flush=True)
