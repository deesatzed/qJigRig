"""Build a bounded, provenance-carrying agent context packet."""
import json

_FIELDS = ('id','record_type','title','path','source_id','source_section_id','revision','source_status','index_status','topic_annotations','start_line','end_line','page_start','page_end','start_offset','end_offset','evidence','evidence_sources','evidence_status','unsupported','output_ref','output_ref_status','source_warning_pages','fallback_reason','lexical_fallback_reason','ranking_method','requested_ranking','embedding_fallback_reason','embedding_issue','embedding_zero_vector_count','dense_similarity','embedding_metadata','embedding_text_truncated','embedding_query_truncated','embedding_may_token_truncate','role_score','role_score_status','role_score_method','role_score_model','role_score_scope')


def serialize_packet(packet):
    """This exact JSON representation is the unit the token counter measures."""
    return json.dumps(packet,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def build_context_packet(task, role, role_version, rows, *, budget, count_tokens, tokenizer_name, catalog_fingerprint=None):
    if not all(isinstance(x,str) and x.strip() for x in (task,role,role_version,tokenizer_name)):
        raise ValueError('task, role, role version and tokenizer name are required')
    if isinstance(budget,bool) or not isinstance(budget,int) or budget < 0 or not callable(count_tokens):
        raise ValueError('a nonnegative token budget and counter are required')
    def count(packet):
        n = count_tokens(serialize_packet(packet))
        if isinstance(n,bool) or not isinstance(n,int) or n < 0:
            raise ValueError('token counter must return a nonnegative integer')
        return n
    packet = {'task':task,'role':role,'role_version':role_version,'tokenizer':tokenizer_name,'catalog_fingerprint':catalog_fingerprint,'results':[],'omitted_count':len(rows)}
    if count(packet) > budget:
        raise ValueError('budget is too small for packet metadata')
    for row in rows:
        if not isinstance(row.get('id'),str) or not isinstance(row.get('body'),str):
            raise ValueError('each result needs an ID and body')
        item = {key:row[key] for key in _FIELDS if key in row}
        if isinstance(row.get('decision'),dict):
            item['decision'] = {key:row['decision'].get(key) for key in ('outcome','provider','model','probability','probability_status','legal_mass','stability','thresholds','prompt_version','reason') if key in row['decision']}
        item['body'] = row['body']
        item['body_truncated'] = bool(row.get('context_truncated',False))
        packet['results'].append(item)
        packet['omitted_count'] -= 1
        if count(packet) <= budget:
            continue
        original = item['body']
        item['body_truncated'] = True
        item['body'] = ''
        if not original or count(packet) > budget:
            packet['results'].pop()
            packet['omitted_count'] += 1
            continue
        lo, hi = 0, len(original)
        while lo < hi:
            mid = (lo+hi+1)//2
            item['body'] = original[:mid]
            if count(packet) <= budget:
                lo = mid
            else:
                hi = mid-1
        item['body'] = original[:lo]
        if not item['body']:
            packet['results'].pop()
            packet['omitted_count'] += 1
    if count(packet) > budget:
        raise ValueError('packet exceeded budget')
    return packet
