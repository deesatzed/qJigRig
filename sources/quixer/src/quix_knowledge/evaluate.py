"""Small evaluation primitives; labels must be independently prepared for claims."""
def evaluate(labels, results, missing_source_ids=(), unavailable_label_ids=()):
    if set(labels) != set(results):
        raise ValueError('query IDs differ')
    recalls=[]
    precisions=[]
    unsupported=0
    stale=0
    unlabeled=0
    unanswerable=0
    missing_source=0
    unavailable_labels=0
    missing_source_ids=set(missing_source_ids)
    unavailable_label_ids=set(unavailable_label_ids)
    if not (missing_source_ids | unavailable_label_ids).issubset(labels):
        raise ValueError('excluded task IDs must exist in labels')
    for query, relevant in labels.items():
        rows=results[query]
        unsupported += sum(bool(row.get('unsupported')) for row in rows)
        stale += sum(row.get('evidence_status') == 'stale' or row.get('source_status') in ('superseded','invalidated') for row in rows)
        if relevant is not None and (not isinstance(relevant,list) or any(not isinstance(x,str) or not x for x in relevant)):
            raise ValueError('labels must be null or a list of nonempty IDs')
        if query in missing_source_ids:
            missing_source += 1
        elif query in unavailable_label_ids:
            unavailable_labels += 1
        elif relevant is None:
            unlabeled += 1
        elif not relevant:
            unanswerable += 1
            if rows:
                precisions.append(0.0)
        else:
            matched = len(set(relevant) & {row['id'] for row in rows})
            recalls.append(matched / len(set(relevant)))
            precisions.append(matched / len(rows) if rows else 0.0)
    return {'answerable':len(recalls),'unanswerable':unanswerable,'unlabeled':unlabeled,'missing_source':missing_source,'unavailable_labels':unavailable_labels,'mean_recall':sum(recalls)/len(recalls) if recalls else None,'mean_precision':sum(precisions)/len(precisions) if precisions else None,'unsupported_returned':unsupported,'stale_returned':stale}

def compare_runs(labels, runs):
    if not runs:
        raise ValueError('no runs')
    revisions = {run['corpus_revision'] for run in runs.values()}
    if len(revisions) != 1:
        raise ValueError('corpus revisions differ')
    return {'corpus_revision':revisions.pop(),'variants':{name:evaluate(labels,run['results']) for name,run in runs.items()}}
