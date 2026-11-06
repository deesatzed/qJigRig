"""Minimal local command-line entry point."""
import argparse
import json
from pathlib import Path
from .store import open_catalog
from .ingest import ingest
from .retrieve import search

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('hitm-context',help='read one bounded context request from standard input')
    sub.add_parser('hitm-recovery-context',help='read one bounded source-recovering context request')
    ingest_parser = sub.add_parser('ingest')
    ingest_parser.add_argument('path')
    sub.add_parser('refresh',help='reconcile known source files with the catalog')
    index_parser = sub.add_parser('index')
    index_parser.add_argument('path')
    index_parser.add_argument('--env-file')
    index_parser.add_argument('--model-slot', type=int, choices=(1,2,3,4))
    index_parser.add_argument('--max-decisions', type=int, default=10)
    list_index = sub.add_parser('list-index')
    list_index.add_argument('--status',choices=('proposed','accepted','rejected','stale'))
    review_index = sub.add_parser('review-index')
    review_index.add_argument('entry_id')
    review_index.add_argument('decision',choices=('accepted','rejected'))
    review_index.add_argument('--reviewer',required=True)
    list_topics = sub.add_parser('list-topics')
    list_topics.add_argument('--status',choices=('proposed','accepted','rejected','stale'))
    review_topic_parser = sub.add_parser('review-topic')
    review_topic_parser.add_argument('link_id',type=int)
    review_topic_parser.add_argument('decision',choices=('accepted','rejected'))
    review_topic_parser.add_argument('--reviewer',required=True)
    add_record_parser = sub.add_parser('add-record')
    add_record_parser.add_argument('record_id')
    add_record_parser.add_argument('kind',choices=('finding','decision','test_result'))
    add_record_parser.add_argument('--body-file',required=True)
    add_record_parser.add_argument('--producer',required=True)
    add_record_parser.add_argument('--evidence',action='append',default=[])
    add_record_parser.add_argument('--output-ref')
    add_record_parser.add_argument('--supersedes')
    review_record_parser = sub.add_parser('review-record')
    review_record_parser.add_argument('record_id')
    review_record_parser.add_argument('decision',choices=('accepted','rejected'))
    review_record_parser.add_argument('--reviewer',required=True)
    list_records_parser = sub.add_parser('list-records')
    list_records_parser.add_argument('--status',choices=('proposed','current','superseded','invalidated'))
    role_parser = sub.add_parser('assess-role')
    role_parser.add_argument('section_id')
    role_parser.add_argument('--role',required=True)
    role_parser.add_argument('--role-version',required=True)
    role_parser.add_argument('--role-purpose',required=True)
    role_parser.add_argument('--env-file')
    role_parser.add_argument('--model-slot',type=int,choices=(1,2,3,4))
    record_topic_parser = sub.add_parser('assess-record-topic')
    record_topic_parser.add_argument('record_id')
    record_topic_parser.add_argument('topic')
    record_topic_parser.add_argument('--env-file')
    record_topic_parser.add_argument('--model-slot',type=int,choices=(1,2,3,4))
    topic_map_parser = sub.add_parser('map-topics')
    topic_map_parser.add_argument('topics',help='JSON array of topic names')
    topic_map_parser.add_argument('--max-decisions',type=int,required=True)
    topic_map_parser.add_argument('--include-proposed',action='store_true')
    topic_map_parser.add_argument('--env-file')
    topic_map_parser.add_argument('--model-slot',type=int,choices=(1,2,3,4))
    experiment_parser = sub.add_parser('experiment')
    experiment_parser.add_argument('tasks', help='JSON array of task records')
    exp_budget = experiment_parser.add_mutually_exclusive_group()
    exp_budget.add_argument('--context-chars', type=int)
    exp_budget.add_argument('--context-tokens', type=int)
    exp_budget.add_argument('--packet-tokens', type=int)
    experiment_parser.add_argument('--tokenizer')
    experiment_parser.add_argument('--include-proposed', action='store_true')
    experiment_parser.add_argument('--matched-candidates',action='store_true',help='compare variants using sections and agent records only')
    experiment_parser.add_argument('--indexing-receipts', help='JSON array of indexing receipt IDs from this catalog')
    experiment_parser.add_argument('--limit', type=int, default=10)
    experiment_parser.add_argument('--ranking',choices=('overlap','bm25','hybrid'),default='overlap')
    experiment_parser.add_argument('--label-provenance')
    experiment_parser.add_argument('--env-file')
    experiment_parser.add_argument('--model-slot', type=int, choices=(1,2,3,4))
    calibrate_parser = sub.add_parser('calibrate')
    calibrate_parser.add_argument('spec',help='JSON labeled decisions and candidate thresholds')
    review_prepare_parser = sub.add_parser('prepare-review')
    review_prepare_parser.add_argument('tasks',help='JSON array of tasks')
    review_prepare_parser.add_argument('--include-proposed',action='store_true')
    review_prepare_parser.add_argument('--matched-candidates',action='store_true')
    review_compile_parser = sub.add_parser('compile-review')
    review_compile_parser.add_argument('packet',help='reviewed JSON packet')
    experiment_parser.add_argument('--reviewed',action='store_true',help='tasks input is a compiled review artifact')
    search_parser = sub.add_parser('search')
    search_parser.add_argument('query')
    search_parser.add_argument('--variant', choices=('baseline','topic','decision','role'), default='baseline')
    search_parser.add_argument('--ranking',choices=('overlap','bm25','hybrid'),default='overlap')
    search_parser.add_argument('--role')
    search_parser.add_argument('--role-version')
    budget = search_parser.add_mutually_exclusive_group()
    budget.add_argument('--context-chars', type=int)
    budget.add_argument('--context-tokens', type=int)
    search_parser.add_argument('--tokenizer')
    search_parser.add_argument('--include-proposed', action='store_true')
    search_parser.add_argument('--env-file')
    search_parser.add_argument('--model-slot', type=int, choices=(1,2,3,4))
    context_parser = sub.add_parser('context')
    context_parser.add_argument('task')
    context_parser.add_argument('--role',required=True)
    context_parser.add_argument('--role-version',required=True)
    context_parser.add_argument('--budget',type=int,required=True)
    context_parser.add_argument('--tokenizer',required=True)
    context_parser.add_argument('--variant',choices=('baseline','topic','decision','role'),default='role')
    context_parser.add_argument('--ranking',choices=('overlap','bm25','hybrid'),default='overlap')
    context_parser.add_argument('--limit',type=int,default=10)
    context_parser.add_argument('--include-proposed',action='store_true')
    context_parser.add_argument('--env-file')
    context_parser.add_argument('--model-slot',type=int,choices=(1,2,3,4))
    for rank_parser in (experiment_parser,search_parser,context_parser):
        rank_parser.add_argument('--jevedge-root',help='trusted JevEdge0 source checkout')
        rank_parser.add_argument('--embedding-model-path',help='existing local embedding checkpoint')
    for provider_parser in (index_parser, role_parser, record_topic_parser, topic_map_parser, experiment_parser, search_parser, context_parser):
        provider_parser.add_argument('--jev-url',help='HTTP loopback JevEdge0 workbench origin')
        provider_parser.add_argument('--stability-trials',type=int,default=1)
        provider_parser.add_argument('--thresholds',type=float,nargs=2,metavar=('LOW','HIGH'),help='explicit experimental decision thresholds')
    args = parser.parse_args()
    if args.command in ('index','assess-role','assess-record-topic','map-topics','experiment','search','context'):
        if bool(args.env_file) != bool(args.model_slot):
            parser.error('--env-file and --model-slot must be provided together')
        if args.jev_url and args.env_file:
            parser.error('choose one decision provider')
        if args.thresholds and not (args.jev_url or args.env_file):
            parser.error('thresholds require a decision provider')
        if args.thresholds and not 0 <= args.thresholds[0] < args.thresholds[1] <= 1:
            parser.error('thresholds must satisfy 0 <= LOW < HIGH <= 1')
        if args.command in ('assess-role','assess-record-topic','map-topics') and not (args.jev_url or args.env_file):
            parser.error(f'{args.command} requires a decision provider')
    if args.command == 'experiment' and bool(args.tokenizer) != (args.context_tokens is not None or args.packet_tokens is not None):
        parser.error('--context-tokens or --packet-tokens and --tokenizer must be provided together')
    if args.command == 'experiment' and args.reviewed and (args.label_provenance or args.include_proposed):
        parser.error('reviewed labels supply their own provenance and proposal scope')
    if args.command in ('search','context') and (args.env_file or args.jev_url) and args.variant not in ('decision','role'):
        parser.error('a model requires the decision or role variant')
    if args.command == 'search' and bool(args.tokenizer) != (args.context_tokens is not None):
        parser.error('--context-tokens and --tokenizer must be provided together')
    if args.command in ('search','context','experiment'):
        if args.ranking == 'hybrid' and not (args.jevedge_root and args.embedding_model_path):
            parser.error('hybrid ranking requires --jevedge-root and --embedding-model-path')
        if args.ranking != 'hybrid' and (args.jevedge_root or args.embedding_model_path):
            parser.error('embedding paths require hybrid ranking')
    if args.command == 'hitm-context':
        from .hitm import cli_context
        return cli_context(args.db)
    if args.command == 'hitm-recovery-context':
        from .hitm import cli_context
        return cli_context(args.db,recovery=True)
    db = open_catalog(args.db)
    try:
        def configured_provider():
            if args.jev_url:
                from .jevedge import JevEdgeDecision
                return JevEdgeDecision(args.jev_url,stability_trials=args.stability_trials,thresholds=args.thresholds)
            if args.env_file:
                from .openrouter import load_settings, OpenRouterDecision
                return OpenRouterDecision(load_settings(args.env_file,args.model_slot),thresholds=args.thresholds)
            return None
        def configured_embedder():
            if args.ranking != 'hybrid':
                return None
            from .hybrid import JevEdgeEmbedder
            return JevEdgeEmbedder(args.jevedge_root,args.embedding_model_path)
        if args.command == 'refresh':
            from .refresh import refresh_sources
            report=refresh_sources(db)
            print(json.dumps(report))
            return 0 if report['failed'] == 0 else 1
        if args.command == 'calibrate':
            from .calibration import select_policy
            spec = json.loads(Path(args.spec).read_text(encoding='utf-8'))
            result = select_policy(spec['rows'],spec['threshold_pairs'],max_error_rate=spec.get('max_error_rate',0.0),min_actions=spec.get('min_actions',3),label_provenance=spec['label_provenance'])
            print(json.dumps(result))
            return 0
        if args.command == 'prepare-review':
            from .labeling import prepare_review
            tasks = json.loads(Path(args.tasks).read_text(encoding='utf-8'))
            print(json.dumps(prepare_review(db,tasks,include_proposed=args.include_proposed,candidate_scope='sections_and_records' if args.matched_candidates else 'variant_specific')))
            return 0
        if args.command == 'compile-review':
            from .labeling import compile_review
            packet = json.loads(Path(args.packet).read_text(encoding='utf-8'))
            print(json.dumps(compile_review(db,packet)))
            return 0
        if args.command == 'assess-record-topic':
            from .decisions import assess_record_topic
            result = assess_record_topic(db,args.record_id,args.topic,configured_provider())
            print(json.dumps(result))
            return 0 if result['outcome'] != 'unknown' else 1
        if args.command == 'map-topics':
            from .indexing import map_topics
            topics = json.loads(Path(args.topics).read_text(encoding='utf-8'))
            result = map_topics(db,topics,configured_provider(),max_decisions=args.max_decisions,include_proposed=args.include_proposed)
            print(json.dumps(result))
            return 0 if result['target_changed'] == 0 else 1
        if args.command == 'context':
            import tiktoken
            from .context import build_context_packet, serialize_packet
            from .experiment import corpus_fingerprint
            encoding = tiktoken.get_encoding(args.tokenizer)
            before = corpus_fingerprint(db)
            count_tokens = lambda text:len(encoding.encode_ordinary(text))
            build_context_packet(args.task,args.role,args.role_version,[],budget=args.budget,count_tokens=count_tokens,tokenizer_name=args.tokenizer,catalog_fingerprint=before)
            rows = search(db,args.task,variant=args.variant,role=args.role,role_version=args.role_version,provider=configured_provider(),limit=args.limit,include_proposed=args.include_proposed,ranking=args.ranking,embedder=configured_embedder())
            if corpus_fingerprint(db) != before:
                raise RuntimeError('catalog changed while preparing context')
            packet = build_context_packet(args.task,args.role,args.role_version,rows,budget=args.budget,count_tokens=count_tokens,tokenizer_name=args.tokenizer,catalog_fingerprint=before)
            print(serialize_packet(packet))
            return 0
        if args.command == 'list-topics':
            query = 'SELECT t.*,s.path,s.revision,x.title AS section_title FROM topic_links t LEFT JOIN sections x ON x.id=t.section_id LEFT JOIN sources s ON s.id=x.source_id'
            params = ()
            if args.status:
                query += ' WHERE t.status=?'
                params = (args.status,)
            print(json.dumps([dict(row) for row in db.execute(query+' ORDER BY t.id',params)]))
            return 0
        if args.command == 'review-topic':
            from .records import review_topic
            review_topic(db,args.link_id,args.decision,args.reviewer)
            print(json.dumps({'link_id':args.link_id,'decision':args.decision,'reviewer':args.reviewer}))
            return 0
        if args.command == 'add-record':
            from .records import add_record
            body = Path(args.body_file).read_text(encoding='utf-8')
            add_record(db,args.record_id,args.kind,body,args.producer,evidence=args.evidence,output_ref=args.output_ref,supersedes=args.supersedes)
            print(json.dumps({'record_id':args.record_id,'status':'proposed'}))
            return 0
        if args.command == 'review-record':
            from .records import review_record
            review_record(db,args.record_id,args.decision,args.reviewer)
            print(json.dumps({'record_id':args.record_id,'decision':args.decision,'reviewer':args.reviewer}))
            return 0
        if args.command == 'list-records':
            query = 'SELECT * FROM records'
            params = ()
            if args.status:
                query += ' WHERE status=?'
                params = (args.status,)
            records = []
            for row in db.execute(query+' ORDER BY id',params):
                item=dict(row)
                item['evidence']=[r[0] for r in db.execute('SELECT section_id FROM evidence WHERE record_id=? ORDER BY section_id',(item['id'],))]
                item['reviews']=[dict(r) for r in db.execute('SELECT reviewer,decision,reviewed_at FROM record_reviews WHERE record_id=? ORDER BY id',(item['id'],))]
                records.append(item)
            print(json.dumps(records))
            return 0
        if args.command == 'assess-role':
            from .decisions import assess_role
            provider = configured_provider()
            result = assess_role(db,args.section_id,args.role,args.role_version,args.role_purpose,provider)
            print(json.dumps(result))
            return 0 if result['outcome'] != 'unknown' else 1
        if args.command == 'list-index':
            query = 'SELECT g.*,s.path,s.revision,p.page_start,p.page_end FROM generated_index g JOIN sections x ON x.id=g.section_id JOIN sources s ON s.id=x.source_id LEFT JOIN section_pages p ON p.section_id=x.id'
            params = ()
            if args.status:
                query += ' WHERE g.status=?'
                params = (args.status,)
            print(json.dumps([dict(row) for row in db.execute(query+' ORDER BY s.path,g.start_offset',params)]))
            return 0
        if args.command == 'review-index':
            from .indexing import review_generated_entry
            review_generated_entry(db,args.entry_id,args.decision,args.reviewer)
            print(json.dumps({'entry_id':args.entry_id,'decision':args.decision,'reviewer':args.reviewer}))
            return 0
        if args.command == 'ingest':
            source_id = ingest(db,args.path)
            print(json.dumps({'source_id':source_id}))
            return 0 if source_id else 1
        if args.command == 'index':
            from .indexing import index_source
            provider = configured_provider()
            result = index_source(db,args.path,provider=provider,max_decisions=args.max_decisions)
            print(json.dumps(result))
            return 0 if result['source_id'] and result.get('status') != 'source_changed' else 1
        if args.command == 'experiment':
            from .experiment import run_experiment, run_reviewed_experiment
            provider = configured_provider()
            tasks = json.loads(Path(args.tasks).read_text(encoding='utf-8'))
            indexing_receipts = json.loads(Path(args.indexing_receipts).read_text(encoding='utf-8')) if args.indexing_receipts else None
            count_tokens = None
            if args.tokenizer:
                import tiktoken
                encoding = tiktoken.get_encoding(args.tokenizer)
                count_tokens = lambda text: len(encoding.encode_ordinary(text))
            context_chars = args.context_chars if args.context_chars is not None else (None if args.context_tokens is not None or args.packet_tokens is not None else 4000)
            options = dict(provider=provider,context_chars=context_chars,context_tokens=args.context_tokens,packet_tokens=args.packet_tokens,count_tokens=count_tokens,tokenizer_name=args.tokenizer,limit=args.limit,indexing_receipt_ids=indexing_receipts,ranking=args.ranking,embedder=configured_embedder(),matched_candidates=args.matched_candidates)
            if args.reviewed:
                result = run_reviewed_experiment(db,tasks,**options)
            else:
                result = run_experiment(db,tasks,label_provenance=args.label_provenance,include_proposed=args.include_proposed,**options)
            print(json.dumps(result))
            return 0
        provider = configured_provider()
        count_tokens = None
        if args.tokenizer:
            import tiktoken
            encoding = tiktoken.get_encoding(args.tokenizer)
            count_tokens = lambda text: len(encoding.encode_ordinary(text))
        print(json.dumps(search(db,args.query,variant=args.variant,role=args.role,role_version=args.role_version,provider=provider,context_chars=args.context_chars,include_proposed=args.include_proposed,context_tokens=args.context_tokens,count_tokens=count_tokens,ranking=args.ranking,embedder=configured_embedder())))
        return 0
    finally:
        db.close()

if __name__ == '__main__':
    raise SystemExit(main())
