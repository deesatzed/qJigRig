"""Build a small, source-anchored packet for HITMCockpit's bounded planner."""
from .context import build_context_packet, serialize_packet


def make_agent_packet(task, rows, *, fingerprint, body_characters=300, result_limit=1):
    if type(body_characters) is not int or body_characters < 1 or type(result_limit) is not int or not 1 <= result_limit <= 100:
        raise ValueError('invalid body budget or result limit')
    selected=[]
    for original in rows[:result_limit]:
        row=dict(original)
        text=row.get('body','')
        if not isinstance(text,str):
            raise ValueError('invalid evidence body')
        row['body']=text[:body_characters]
        row['context_truncated']=bool(row.get('context_truncated') or row.get('body_truncated')) or len(text)>body_characters
        selected.append(row)
    packet=build_context_packet(task['query'],task['role'],task['role_version'],selected,budget=10000,
        count_tokens=len,tokenizer_name='json-characters',catalog_fingerprint=fingerprint)
    packet['omitted_count']+=max(0,len(rows)-len(selected))
    if len(serialize_packet(packet))>10000:
        raise ValueError('packet exceeded budget after omitted results')
    return packet


def build_agent_packets(db, comparison, tasks, *, body_characters=300, result_limit=1):
    """Construct condition packets from a source-validated comparison report."""
    fingerprint=comparison['manifest']['corpus_revision']
    packets={}
    for task in tasks:
        for condition in ('baseline','role','switch'):
            query=comparison['variants'][condition]['queries'][task['id']]
            rows=[dict(item) for item in query['results']]
            if rows and query.get('fallback_reason'):
                rows[0]['fallback_reason']=query['fallback_reason']
            for row in rows:
                if row['record_type']=='agent_record':
                    row['evidence_sources']=[dict(item) for item in db.execute('''SELECT s.id AS section_id,x.path,x.revision,x.status AS source_status,s.start_line,s.end_line,p.page_start,p.page_end FROM evidence e JOIN sections s ON s.id=e.section_id JOIN sources x ON x.id=s.source_id LEFT JOIN section_pages p ON p.section_id=s.id WHERE e.record_id=? ORDER BY s.id''',(row['id'],))]
            packets[(task['id'],condition)]=make_agent_packet(task,rows,fingerprint=fingerprint,body_characters=body_characters,result_limit=result_limit)
    return packets
