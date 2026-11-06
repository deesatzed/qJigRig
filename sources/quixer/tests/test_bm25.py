from quix_knowledge.bm25 import score_documents
from quix_knowledge.ingest import ingest
from quix_knowledge.retrieve import search
from quix_knowledge.store import open_catalog


def test_bm25_prefers_focused_repeated_matches():
    scores=score_documents('retry',['retry retry recovery','retry ' + 'other '*100,'unrelated text'])
    assert scores[0] > scores[1] > scores[2]
    assert scores[2] == 0


def test_all_variants_can_use_common_bm25_ranker(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# A\nretry retry recovery\n# B\nretry ' + 'other '*100)
    ingest(db,path)
    for variant in ('baseline','topic','decision','role'):
        rows=search(db,'retry',variant=variant,ranking='bm25')
        assert rows[0]['title'] == 'A'
        assert all(row['ranking_method'] == 'bm25' for row in rows)

def test_generated_entries_do_not_change_bm25_corpus_statistics(tmp_path):
    from quix_knowledge.indexing import index_source
    db=open_catalog(':memory:')
    path=tmp_path/'doc.txt'
    path.write_text('retry handles failure.\n\nlogging records retry outcomes.')
    index_source(db,path)
    base=search(db,'retry',variant='baseline',ranking='bm25')[0]
    topic=search(db,'retry',variant='topic',ranking='bm25',include_proposed=True)
    original=next(row for row in topic if row['id'] == base['id'])
    assert original['lexical_score'] == base['lexical_score']
