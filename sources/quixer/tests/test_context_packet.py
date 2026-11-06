import json
import pytest
from quix_knowledge.context import build_context_packet


def char_count(text):
    return len(text)


def test_packet_budget_covers_task_metadata_and_body():
    rows=[{'id':'s1','record_type':'section','title':'Retry','body':'retry ' * 100,'path':'/docs/a','revision':'abc','start_line':1,'end_line':4}]
    packet=build_context_packet('Review retry','reviewer','1',rows,budget=350,count_tokens=char_count,tokenizer_name='fixture-chars')
    serialized=json.dumps(packet,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    assert len(serialized) <= 350
    assert packet['results'][0]['revision'] == 'abc'
    assert packet['results'][0]['body_truncated'] is True
    assert packet['results'][0]['body']


def test_packet_reports_omitted_results_and_rejects_too_small_budget():
    rows=[{'id':'s','record_type':'section','title':'T','body':'abc','path':'/'+'x'*500}]
    packet=build_context_packet('task','reviewer','1',rows,budget=200,count_tokens=char_count,tokenizer_name='fixture-chars')
    assert packet['results'] == []
    assert packet['omitted_count'] == 1
    with pytest.raises(ValueError,match='budget'):
        build_context_packet('task','reviewer','1',rows,budget=5,count_tokens=char_count,tokenizer_name='fixture-chars')


def test_packet_preserves_unknown_and_stale_labels():
    rows=[{'id':'r','record_type':'agent_record','title':'finding','body':'claim','evidence':['old'],'evidence_status':'stale','fallback_reason':'decision_unknown','role_score_status':'proposed'}]
    packet=build_context_packet('task','reviewer','1',rows,budget=1000,count_tokens=char_count,tokenizer_name='fixture-chars')
    item=packet['results'][0]
    assert item['evidence_status'] == 'stale'
    assert item['fallback_reason'] == 'decision_unknown'
    assert item['role_score_status'] == 'proposed'
