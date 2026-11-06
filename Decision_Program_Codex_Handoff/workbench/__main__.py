import argparse
import json
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from . import core

def main():
    p=argparse.ArgumentParser(prog='python -m workbench'); sub=p.add_subparsers(dest='cmd',required=True)
    sub.add_parser('fixture-demo')
    sub.add_parser('preflight')
    sub.add_parser('starter-development')
    s=sub.add_parser('import'); s.add_argument('file'); s.add_argument('--title'); s.add_argument('--origin',help='Recorded source location or description; not fetched or verified'); s.add_argument('--scope',default=''); s.add_argument('--effective-from',default=''); s.add_argument('--effective-to',default=''); s.add_argument('--observed-at',default='')
    coll=sub.add_parser('collection'); coll.add_argument('--title',required=True); coll.add_argument('source_ids',nargs='+')
    d=sub.add_parser('derive'); d.add_argument('--parent',required=True); d.add_argument('--file',required=True); d.add_argument('--title',required=True); d.add_argument('--reason',required=True)
    r=sub.add_parser('run'); r.add_argument('--question',required=True); r.add_argument('--snapshot',required=True); r.add_argument('--scope',default=''); r.add_argument('--as-of',default=''); r.add_argument('--historical-as-known',action='store_true'); r.add_argument('--exhaustive',action='store_true',help='Evaluate all remote predicates or search all unresolved local predicates'); r.add_argument('--no-extra-search',action='store_true',help='Disable additional lexical searches'); r.add_argument('--mode',choices=['fresh','direct','frontier','reviewed','intervention'],default='fresh'); r.add_argument('--program'); r.add_argument('--intervention-reason',default=''); r.add_argument('--evidence-mode',choices=['shared','lexical'],default='shared'); r.add_argument('--judge-backend',choices=['remote','local'],default='remote'); r.add_argument('--local-threshold',type=float); r.add_argument('--share-sources',action='store_true')
    web=sub.add_parser('web-research'); web.add_argument('--question',required=True); web.add_argument('--scope',default=''); web.add_argument('--as-of',default=''); web.add_argument('--allow-web',action='store_true'); web.add_argument('--accept-unenforced-budget',action='store_true',help='Acknowledge provider may exceed the requested one-search limit')
    probe=sub.add_parser('decision-probe'); probe.add_argument('--snapshot',required=True); probe.add_argument('--question',required=True); probe.add_argument('--model',default=None); probe.add_argument('--share-sources',action='store_true')
    local=sub.add_parser('local-judge-probe'); local.add_argument('--snapshot',required=True); local.add_argument('--claim',required=True)
    intrep=sub.add_parser('intervention-report'); intrep.add_argument('original_run_id'); intrep.add_argument('intervention_run_id')
    draft=sub.add_parser('program-draft'); draft.add_argument('run_id')
    edit=sub.add_parser('program-revise'); edit.add_argument('program_id'); edit.add_argument('--plan-file',required=True); edit.add_argument('--author',required=True); edit.add_argument('--rationale',required=True)
    revp=sub.add_parser('program-review'); revp.add_argument('program_id'); revp.add_argument('--reviewer',required=True); revp.add_argument('--rationale',required=True)
    l=sub.add_parser('list'); l.add_argument('kind',choices=['snapshots','runs','programs','dataset_runs','comparison_intents','comparison_arm_intents','comparison_arm_receipts','run_intents','run_call_intents','run_call_receipts'])
    show=sub.add_parser('show'); show.add_argument('kind',choices=['snapshots','runs','programs','dataset_runs','comparison_intents','comparison_arm_intents','comparison_arm_receipts','run_intents','run_call_intents','run_call_receipts']); show.add_argument('id')
    verify_run=sub.add_parser('verify-run'); verify_run.add_argument('run_id')
    cmp=sub.add_parser('compare'); cmp.add_argument('--question',required=True); cmp.add_argument('--snapshot',required=True); cmp.add_argument('--scope',default=''); cmp.add_argument('--as-of',default=''); cmp.add_argument('--historical-as-known',action='store_true'); cmp.add_argument('--share-sources',action='store_true'); cmp.add_argument('--stage',choices=['shared-evidence','shared-corpus','practical'],default='shared-evidence'); cmp.add_argument('--allow-web',action='store_true'); cmp.add_argument('--accept-unenforced-budget',action='store_true'); cmp.add_argument('--exhaustive',action='store_true'); cmp.add_argument('--no-extra-search',action='store_true',help='Disable additional lexical searches'); cmp.add_argument('--judge-backend',choices=['remote','local'],default='remote'); cmp.add_argument('--local-threshold',type=float)
    blind=sub.add_parser('blind'); blind.add_argument('comparison_id')
    assess=sub.add_parser('assess-case'); assess.add_argument('comparison_id'); assess.add_argument('--reviewer',required=True); assess.add_argument('--answerability',choices=['answerable','unanswerable','uncertain'],required=True); assess.add_argument('--rationale',required=True); assess.add_argument('--references',default='')
    rev=sub.add_parser('adjudicate'); rev.add_argument('comparison_id'); rev.add_argument('review_id'); rev.add_argument('--reviewer',required=True); rev.add_argument('--verdict',choices=['correct','incorrect','unresolved'],required=True); rev.add_argument('--support',choices=['supported','unsupported','unclear'],required=True); rev.add_argument('--notes',required=True)
    report=sub.add_parser('report'); report.add_argument('comparison_id')
    export=sub.add_parser('export-comparison'); export.add_argument('comparison_id')
    ds=sub.add_parser('dataset-freeze'); ds.add_argument('file'); ds.add_argument('--title',required=True)
    dsrun=sub.add_parser('dataset-run'); dsrun.add_argument('dataset_id'); dsrun.add_argument('--share-sources',action='store_true'); dsrun.add_argument('--max-calls',type=int,required=True); dsrun.add_argument('--stage',choices=['shared-evidence','shared-corpus','practical'],default='shared-evidence'); dsrun.add_argument('--allow-web',action='store_true'); dsrun.add_argument('--accept-unenforced-budget',action='store_true'); dsrun.add_argument('--exhaustive',action='store_true'); dsrun.add_argument('--no-extra-search',action='store_true',help='Disable additional lexical searches'); dsrun.add_argument('--judge-backend',choices=['remote','local'],default='remote'); dsrun.add_argument('--local-threshold',type=float)
    dsresume=sub.add_parser('dataset-resume'); dsresume.add_argument('dataset_run_id'); dsresume.add_argument('--share-sources',action='store_true')
    dsstatus=sub.add_parser('dataset-status'); dsstatus.add_argument('dataset_run_id')
    dsscore=sub.add_parser('dataset-score'); dsscore.add_argument('dataset_run_id'); dsscore.add_argument('--format',choices=['json','markdown'],default='json')
    dsexport=sub.add_parser('dataset-export'); dsexport.add_argument('dataset_run_id')
    dsverify=sub.add_parser('dataset-verify'); dsverify.add_argument('file')
    serve=sub.add_parser('serve'); serve.add_argument('--port',type=int,default=8765)
    a=p.parse_args()
    if a.cmd=='serve':
        server=ThreadingHTTPServer(('127.0.0.1',a.port),Handler); print(f'http://127.0.0.1:{a.port}',flush=True); server.serve_forever(); return
    if a.cmd=='preflight':
        from .preflight import inspect
        result=inspect()
    elif a.cmd=='fixture-demo':
        from .fixture import demo
        result=demo()
    elif a.cmd=='starter-development':
        from .starter import initialize_development
        result=initialize_development()
    elif a.cmd=='import':
        path=Path(a.file); result=core.snapshot(a.title or path.name,path.read_bytes().decode('utf-8'),a.scope,a.effective_from,a.effective_to,origin=a.origin if a.origin is not None else str(path),observed_at=a.observed_at)
    elif a.cmd=='collection':
        from .collections import create
        result=create(a.title,a.source_ids)
    elif a.cmd=='derive': result=core.derive_snapshot(a.parent,a.title,Path(a.file).read_bytes().decode('utf-8'),a.reason)
    elif a.cmd=='run': result=core.run(a.question,a.snapshot,a.scope,a.as_of,a.mode,a.share_sources,program_id=a.program,judge_backend=a.judge_backend,local_threshold=a.local_threshold,evidence_mode=a.evidence_mode,intervention_reason=a.intervention_reason,historical_as_known=a.historical_as_known,targeted=not a.exhaustive,extra_search=not a.no_extra_search)
    elif a.cmd=='local-judge-probe':
        from .local_judge import probe
        result=probe(core.load('snapshots',a.snapshot)['text'],a.claim)
    elif a.cmd=='intervention-report':
        from .programs import intervention_report
        result=intervention_report(a.original_run_id,a.intervention_run_id)
    elif a.cmd in ('program-draft','program-review','program-revise'):
        from . import programs
        if a.cmd=='program-draft': result=programs.draft(a.run_id)
        elif a.cmd=='program-revise': result=programs.revise(a.program_id,json.loads(Path(a.plan_file).read_text()),a.author,a.rationale)
        else: result=programs.review(a.program_id,a.reviewer,a.rationale)
    elif a.cmd=='web-research':
        from .web_research import run as web_run
        result=web_run(a.question,a.scope,a.as_of,a.allow_web,a.accept_unenforced_budget)
    elif a.cmd=='decision-probe':
        from .decisions import probe
        source=core.load('snapshots',a.snapshot)
        result=probe(source['text'],a.question,a.model or core.config().get('OPENROUTER_DEC_MODEL_3'),a.share_sources)
    elif a.cmd in ('compare','blind','assess-case','adjudicate','report','export-comparison'):
        from . import compare
        if a.cmd=='compare':
            created=compare.create(a.question,a.snapshot,a.scope,a.as_of,a.share_sources,judge_backend=a.judge_backend,local_threshold=a.local_threshold,stage=a.stage,allow_web=a.allow_web,historical_as_known=a.historical_as_known,targeted=not a.exhaustive,extra_search=not a.no_extra_search,accept_unenforced_budget=a.accept_unenforced_budget)
            result={'comparison_id':created['id'],'status':created['status']}
        elif a.cmd=='blind': result=compare.blind(a.comparison_id)
        elif a.cmd=='assess-case': result=compare.assess_case(a.comparison_id,a.reviewer,a.answerability,a.rationale,a.references)
        elif a.cmd=='adjudicate': result=compare.adjudicate(a.comparison_id,a.review_id,a.reviewer,a.verdict,a.support,a.notes)
        elif a.cmd=='report': result=compare.report(a.comparison_id)
        else: result=compare.export_bundle(a.comparison_id)
    elif a.cmd in ('dataset-export','dataset-verify'):
        from . import archive
        result=archive.export_dataset(a.dataset_run_id) if a.cmd=='dataset-export' else archive.verify_dataset(json.loads(Path(a.file).read_text()))
    elif a.cmd in ('dataset-freeze','dataset-run','dataset-resume','dataset-status','dataset-score'):
        from . import datasets
        if a.cmd=='dataset-freeze': result=datasets.freeze(a.title,json.loads(Path(a.file).read_text()))
        elif a.cmd=='dataset-run': result=datasets.launch(a.dataset_id,a.share_sources,a.max_calls,a.judge_backend,a.local_threshold,a.stage,a.allow_web,not a.exhaustive,not a.no_extra_search,a.accept_unenforced_budget,on_started=lambda run: print(f'Dataset run: {run["id"]}',file=sys.stderr,flush=True))
        elif a.cmd=='dataset-resume': result=datasets.resume(a.dataset_run_id,a.share_sources)
        elif a.cmd=='dataset-status': result=datasets.status(a.dataset_run_id)
        else:
            result=datasets.score(a.dataset_run_id)
            if a.format=='markdown': print(datasets.render_markdown(result),end=''); return
    elif a.cmd=='verify-run':
        from .verify_run import verify
        result=verify(a.run_id)
    elif a.cmd=='list': result=core.records(a.kind)
    else: result=core.load(a.kind,a.id)
    print(json.dumps(result,indent=2,ensure_ascii=False))
    if a.cmd=='verify-run' and result['issues']: raise SystemExit(1)
    if a.cmd=='dataset-verify' and (not result['matches_exported_score'] or result.get('journal_status')=='inconsistent'): raise SystemExit(1)

class Handler(BaseHTTPRequestHandler):
    def respond(self,status,body,content_type='application/json'):
        data=body if isinstance(body,bytes) else json.dumps(body).encode()
        self.send_response(status); self.send_header('Content-Type',content_type); self.send_header('Content-Length',str(len(data))); self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff'); self.send_header('Referrer-Policy','no-referrer'); self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'"); self.end_headers(); self.wfile.write(data)
    def allowed_host(self):
        hosts=self.headers.get_all('Host') or []
        allowed={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
        if self.server.server_port==80: allowed.update(('127.0.0.1','localhost'))
        return len(hosts)==1 and hosts[0].lower() in allowed
    def do_GET(self):
        if not self.allowed_host(): return self.respond(403,{'error':'Host rejected'})
        if self.path=='/api/preflight':
            from .preflight import inspect
            return self.respond(200,inspect())
        if self.path.startswith('/api/verify-run/'):
            try:
                from .verify_run import verify
                return self.respond(200,verify(self.path.rsplit('/',1)[-1]))
            except (ValueError,FileNotFoundError,KeyError) as e: return self.respond(400,{'error':str(e)})
        if self.path=='/': return self.respond(200,(core.ROOT/'workbench'/'index.html').read_bytes(),'text/html; charset=utf-8')
        if self.path=='/datasets': return self.respond(200,(core.ROOT/'workbench'/'datasets.html').read_bytes(),'text/html; charset=utf-8')
        if self.path=='/programs': return self.respond(200,(core.ROOT/'workbench'/'programs.html').read_bytes(),'text/html; charset=utf-8')
        if self.path=='/review' or self.path.startswith('/review?'): return self.respond(200,(core.ROOT/'workbench'/'review.html').read_bytes(),'text/html; charset=utf-8')
        if self.path.startswith('/api/snapshot/'):
            try: return self.respond(200,core.load('snapshots',self.path.rsplit('/',1)[-1]))
            except (ValueError,FileNotFoundError,KeyError) as e: return self.respond(400,{'error':str(e)})
        if self.path.startswith('/api/run/'):
            try: return self.respond(200,core.load('runs',self.path.rsplit('/',1)[-1]))
            except (ValueError,FileNotFoundError,KeyError) as e: return self.respond(400,{'error':str(e)})
        if self.path.startswith(('/api/dataset-status/','/api/dataset-score/')):
            try:
                from . import datasets
                ident=self.path.rsplit('/',1)[-1]
                if self.path.startswith('/api/dataset-status/'):
                    from . import jobs
                    result=datasets.status(ident); result['worker']=jobs.status(ident)
                else: result=datasets.score(ident)
                return self.respond(200,result)
            except (ValueError,FileNotFoundError,KeyError) as e: return self.respond(400,{'error':str(e)})
        if self.path.startswith('/api/blind/'):
            try:
                from . import compare
                return self.respond(200,compare.blind(self.path.rsplit('/',1)[-1]))
            except (ValueError,FileNotFoundError) as e: return self.respond(400,{'error':str(e)})
        if self.path.startswith('/api/report/'):
            try:
                from . import compare
                return self.respond(200,compare.report(self.path.rsplit('/',1)[-1]))
            except (ValueError,FileNotFoundError) as e: return self.respond(400,{'error':str(e)})
        if self.path.startswith('/api/export-comparison/'):
            try:
                from . import compare
                return self.respond(200,compare.export_bundle(self.path.rsplit('/',1)[-1]))
            except (ValueError,FileNotFoundError) as e: return self.respond(400,{'error':str(e)})
        if self.path.startswith('/api/dataset-export/'):
            try:
                from . import archive
                return self.respond(200,archive.export_dataset(self.path.rsplit('/',1)[-1]))
            except (ValueError,FileNotFoundError,KeyError) as e: return self.respond(400,{'error':str(e)})
        if self.path=='/api/dataset-runs':
            from . import datasets
            return self.respond(200,[datasets.status(x['id']) for x in core.records('dataset_runs')])
        if self.path=='/api/source-options':
            keys=('id','title','scope','effective_from','effective_to','observed_at','sha256')
            return self.respond(200,[{**{k:x.get(k,'') for k in keys},'kind':'collection' if 'members' in x else 'source'} for x in core.records('snapshots')])
        if self.path=='/api/run-options':
            return self.respond(200,[{'id':x['id'],'created_at':x.get('created_at',''),'mode':x.get('mode',''),
                'question':x.get('request',{}).get('question',''),'status':x.get('result',{}).get('status','')}
                for x in core.records('runs')])
        if self.path=='/api/comparison-journal':
            starts=core.records('comparison_arm_intents'); receipts=core.records('comparison_arm_receipts')
            result=[]
            for intent in core.records('comparison_intents'):
                ident=intent['id']
                complete=(core.DATA/'comparisons'/(ident+'.json')).is_file()
                result.append({'id':ident,'created_at':intent.get('created_at',''),'question':intent.get('question',''),
                    'stage':intent.get('stage',''),'state':'completed' if complete else 'in progress or interrupted',
                    'started_arms':sum(x.get('comparison_id')==ident for x in starts),
                    'completed_arms':sum(x.get('comparison_id')==ident for x in receipts),
                    'total_arms':len(intent.get('arms',[]))})
            return self.respond(200,result)
        if self.path=='/api/run-journal':
            starts=core.records('run_call_intents'); receipts=core.records('run_call_receipts')
            result=[]
            for intent in core.records('run_intents'):
                ident=intent['id']; started={x['id'] for x in starts if x.get('run_id')==ident}
                recorded={x['id'] for x in receipts if x.get('run_id')==ident}
                final=(core.DATA/'runs'/(ident+'.json')).is_file()
                if final and started==recorded: continue
                result.append({'id':ident,'created_at':intent.get('created_at',''),
                    'question':intent.get('request',{}).get('question',''),'mode':intent.get('mode',''),
                    'state':'final run has unconfirmed calls' if final else 'in progress or interrupted',
                    'started_calls':len(started),'recorded_calls':len(recorded)})
            return self.respond(200,result)
        if self.path in ('/api/snapshots','/api/runs','/api/programs'): return self.respond(200,core.records(self.path.rsplit('/',1)[-1]))
        self.respond(404,{'error':'Not found'})
    def do_POST(self):
        if not self.allowed_host(): return self.respond(403,{'error':'Host rejected'})
        if self.headers.get('Origin') not in (None, 'http://'+self.headers['Host'].lower()):
            return self.respond(403,{'error':'Origin rejected'})
        if self.headers.get_content_type()!='application/json': return self.respond(415,{'error':'JSON content type required'})
        if self.headers.get('Transfer-Encoding'): return self.respond(400,{'error':'Transfer encoding unsupported'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length < 1 or length > 1000000: raise ValueError('Invalid request size')
            x=json.loads(self.rfile.read(length))
            if not isinstance(x,dict): raise ValueError('JSON object required')
            if self.path=='/api/snapshots': result=core.snapshot(x['title'],x['text'],x.get('scope',''),x.get('effective_from',''),x.get('effective_to',''),origin=x.get('origin','user supplied'),observed_at=x.get('observed_at',''))
            elif self.path=='/api/collection':
                from .collections import create
                result=create(x['title'],x['source_ids'])
            elif self.path=='/api/derive': result=core.derive_snapshot(x['parent_id'],x['title'],x['text'],x['reason'])
            elif self.path=='/api/dataset-freeze':
                from . import datasets
                result=datasets.freeze(x['title'],x['cases'])
            elif self.path=='/api/starter-development':
                from .starter import initialize_development
                result=initialize_development()
            elif self.path=='/api/dataset-resume':
                from . import datasets
                result=datasets.resume(x['dataset_run_id'],x.get('consent',False))
            elif self.path=='/api/dataset-resume-background':
                from . import jobs
                result=jobs.resume_dataset(x['dataset_run_id'],x.get('consent',False))
            elif self.path=='/api/dataset-run':
                from . import jobs
                result=jobs.start_dataset(x['dataset_id'],x.get('consent',False),x['max_calls'],x.get('judge_backend','remote'),x.get('local_threshold'),x.get('stage','shared-evidence'),x.get('allow_web',False),x.get('targeted',True),x.get('extra_search',True),x.get('accept_unenforced_budget',False))
            elif self.path=='/api/intervention-report':
                from .programs import intervention_report
                result=intervention_report(x['original_run_id'],x['intervention_run_id'])
            elif self.path=='/api/program-draft':
                from . import programs
                result=programs.draft(x['run_id'])
            elif self.path=='/api/program-revise':
                from . import programs
                result=programs.revise(x['program_id'],x['plan'],x['author'],x['rationale'])
            elif self.path=='/api/program-review':
                from . import programs
                result=programs.review(x['program_id'],x['reviewer'],x['rationale'])
            elif self.path=='/api/compare':
                from . import compare
                created=compare.create(x['question'],x['snapshot_id'],x.get('scope',''),x.get('as_of',''),x.get('consent',False),judge_backend=x.get('judge_backend','remote'),local_threshold=x.get('local_threshold'),stage=x.get('stage','shared-evidence'),allow_web=x.get('allow_web',False),historical_as_known=x.get('historical_as_known',False),targeted=x.get('targeted',True),extra_search=x.get('extra_search',True),accept_unenforced_budget=x.get('accept_unenforced_budget',False))
                result={'comparison_id':created['id'],'status':created['status']}
            elif self.path=='/api/assess-case':
                from . import compare
                result=compare.assess_case(x['comparison_id'],x['reviewer'],x['answerability'],x['rationale'],x.get('references',''))
            elif self.path=='/api/adjudicate':
                from . import compare
                result=compare.adjudicate(x['comparison_id'],x['review_id'],x['reviewer'],x['verdict'],x['support'],x['notes'])
            elif self.path=='/api/run': result=core.run(x['question'],x['snapshot_id'],x.get('scope',''),x.get('as_of',''),x.get('mode','fresh'),x.get('consent',False),program_id=x.get('program_id'),judge_backend=x.get('judge_backend','remote'),local_threshold=x.get('local_threshold'),evidence_mode=x.get('evidence_mode','shared'),intervention_reason=x.get('intervention_reason',''),historical_as_known=x.get('historical_as_known',False),targeted=x.get('targeted',True),extra_search=x.get('extra_search',True))
            else: return self.respond(404,{'error':'Not found'})
            self.respond(200,result)
        except (ValueError,KeyError,FileNotFoundError,json.JSONDecodeError) as e: self.respond(400,{'error':str(e)})

if __name__=='__main__':
    try: main()
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        print(f'Error: {exc}',file=sys.stderr)
        raise SystemExit(1)
