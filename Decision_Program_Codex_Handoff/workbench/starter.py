"""Import hash-pinned public development sources and label-free questions."""
import hashlib
import json
from . import core, collections, datasets

SOURCES={'keyword':('manifest.json','python-3.12.10-keyword.rst'),
         'token':('manifest-token.json','python-3.12.10-token.rst')}

def initialize_development():
    folder=core.ROOT/'starter_corpus'
    inputs={}
    for key,(manifest_name,source_name) in SOURCES.items():
        metadata=json.loads((folder/manifest_name).read_text())
        raw=(folder/source_name).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=metadata['sha256']: raise ValueError('Starter source hash mismatch: '+source_name)
        inputs[key]=(metadata,raw.decode('utf-8'))
    questions=json.loads((folder/'development_questions.json').read_text())
    if not isinstance(questions,list) or not questions: raise ValueError('Invalid development questions')
    seen=set()
    for item in questions:
        if not isinstance(item,dict) or set(item)!={'case_id','source','question'} or item['source'] not in ('keyword','token','collection'):
            raise ValueError('Development questions must contain only case ID, source and question')
        if not isinstance(item['case_id'],str) or not item['case_id'].strip() or item['case_id'] in seen or not isinstance(item['question'],str) or not item['question'].strip():
            raise ValueError('Development question IDs and questions must be nonempty and unique')
        seen.add(item['case_id'])
    if len(questions)>datasets.MAX_CASES: raise ValueError('Too many development questions')
    snapshots={}
    for key,(metadata,text) in inputs.items():
        snapshots[key]=core.snapshot(metadata['title'],text,scope='Python 3.12.10',origin=metadata['upstream'],observed_at=metadata['retrieved_at'][:10])
    collection=collections.create('Python 3.12.10 keyword and token development sources',[snapshots['keyword']['id'],snapshots['token']['id']])
    snapshots['collection']=collection
    cases=[{'case_id':item['case_id'],'question':item['question'],'snapshot_id':snapshots[item['source']]['id'],'scope':'Python 3.12.10'} for item in questions]
    frozen=datasets.freeze('Python documentation development questions',cases)
    return {'dataset_id':frozen['id'],'dataset_sha256':frozen['sha256'],'collection_id':collection['id'],
            'source_ids':{key:snapshots[key]['id'] for key in SOURCES},'case_count':len(cases),
            'classification':'Developer-authored development questions; not independently adjudicated, pilot, or holdout.'}
