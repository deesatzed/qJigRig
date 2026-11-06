"""Replay binary decision policies; empirical results are not guarantees."""
import math


def _thresholds(low,high):
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (low,high)) or not 0 <= low < high <= 1:
        raise ValueError('thresholds must satisfy 0 <= low < high <= 1')


def replay_policy(rows,low,high):
    _thresholds(low,high)
    result = {'labeled':0,'unlabeled':0,'unknown':0,'unstable':0,'deferred':0,'acted':0,'true_positive':0,'true_negative':0,'false_positive':0,'false_negative':0}
    for row in rows:
        label = row.get('label')
        score = row.get('probability')
        if label is not None and type(label) is not bool:
            raise ValueError('label must be true, false or null')
        if score is not None and (isinstance(score,bool) or not isinstance(score,(int,float)) or not math.isfinite(score) or not 0 <= score <= 1):
            raise ValueError('probability must be in [0,1] or null')
        if label is None:
            result['unlabeled'] += 1
            continue
        result['labeled'] += 1
        if score is None or row.get('outcome') == 'unknown':
            result['unknown'] += 1
            continue
        stability = row.get('stability')
        if row.get('stability_required') is True and stability is None:
            result['unknown'] += 1
            continue
        if stability is not None:
            if not isinstance(stability,dict) or not isinstance(stability.get('stable_across_permutations'),bool):
                result['unknown'] += 1
                continue
            if not stability['stable_across_permutations']:
                result['unstable'] += 1
                continue
        if low < score < high:
            result['deferred'] += 1
            continue
        predicted = score >= high
        key = ('true_' if predicted == label else 'false_') + ('positive' if predicted else 'negative')
        result[key] += 1
        result['acted'] += 1
    errors = result['false_positive'] + result['false_negative']
    result['errors'] = errors
    result['error_rate'] = errors/result['acted'] if result['acted'] else None
    result['coverage'] = result['acted']/result['labeled'] if result['labeled'] else None
    return result


def select_policy(rows, threshold_pairs, *, max_error_rate=0.0, min_actions=3, label_provenance):
    """Select on development data only, then report untouched held-out outcomes."""
    if not isinstance(label_provenance,str) or not label_provenance.strip():
        raise ValueError('label provenance is required')
    if isinstance(min_actions,bool) or not isinstance(min_actions,int) or min_actions < 1 or not 0 <= max_error_rate <= 1:
        raise ValueError('invalid selection criteria')
    ids = [r.get('id') for r in rows]
    if any(not isinstance(i,str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('case IDs must be nonempty and unique across splits')
    if any(r.get('split') not in ('development','held_out') for r in rows):
        raise ValueError('case split must be development or held_out')
    for field in ('model','prompt_version','question'):
        values = [r.get(field) for r in rows]
        if not values or not all(isinstance(v,str) and v.strip() for v in values) or len(set(values)) != 1:
            raise ValueError(f'{field} must be specified and identical across cases')
    if not threshold_pairs:
        raise ValueError('threshold candidates are required')
    replay_policy(rows,0.0,1.0)  # validate all records without using held-out outcomes for selection
    development = [r for r in rows if r['split'] == 'development']
    held_out = [r for r in rows if r['split'] == 'held_out']
    candidates = []
    for low,high in threshold_pairs:
        report = replay_policy(development,low,high)
        if report['acted'] >= min_actions and report['error_rate'] is not None and report['error_rate'] <= max_error_rate:
            candidates.append((report['acted'],-report['errors'],-low,-high,low,high,report))
    if not candidates:
        return {'selected':None,'development':None,'held_out':None,'label_provenance':label_provenance,'reason':'no candidate met development constraints'}
    _,_,_,_,low,high,report = max(candidates,key=lambda x:x[:4])
    return {'selected':{'low':low,'high':high},'development':report,'held_out':replay_policy(held_out,low,high),'label_provenance':label_provenance,'selection':'development only; empirical error is not a guarantee'}
