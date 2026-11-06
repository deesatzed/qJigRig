import pytest
from quix_knowledge.ingest import ingest
from quix_knowledge.retrieve import search
from quix_knowledge.store import open_catalog


class FakeEmbedder:
    metadata={'name':'synthetic fixture','revision':'v1'}
    def encode(self,texts):
        return [[1.0,0.0] if 'feline' in text.lower() or 'cat' in text.lower() else [0.0,1.0] for text in texts]


def test_hybrid_can_retrieve_semantic_candidate_without_exact_word(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Pets\nA cat sleeps on a mat.\n# Engines\nA motor drives a wheel.')
    ingest(db,path)
    assert search(db,'feline',ranking='bm25') == []
    result=search(db,'feline',ranking='hybrid',embedder=FakeEmbedder(),limit=1)
    assert result[0]['title'] == 'Pets'
    assert result[0]['ranking_method'] == 'hybrid'
    assert result[0]['dense_similarity'] == pytest.approx(1.0)
    assert result[0]['embedding_metadata']['name'] == 'synthetic fixture'


def test_hybrid_failure_falls_back_and_reports_it(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetry after failure.')
    ingest(db,path)
    class Broken:
        def encode(self,texts):
            raise TimeoutError()
    result=search(db,'retry',ranking='hybrid',embedder=Broken())
    assert result[0]['ranking_method'] == 'bm25'
    assert result[0]['embedding_fallback_reason'] == 'embedding_unavailable'


def test_hybrid_failure_with_no_lexical_result_is_not_silent(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetry after failure.')
    ingest(db,path)
    class Broken:
        def encode(self,texts):
            raise TimeoutError()
    with pytest.raises(RuntimeError,match='embedding'):
        search(db,'feline',ranking='hybrid',embedder=Broken())

def test_zero_document_vectors_are_reported_as_embedding_failure(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetry after failure.')
    ingest(db,path)
    class ZeroDocuments:
        def encode(self,texts):
            return [[1.0,0.0]] + [[0.0,0.0] for _ in texts[1:]]
    result=search(db,'retry',ranking='hybrid',embedder=ZeroDocuments())
    assert result[0]['embedding_fallback_reason'] == 'embedding_unavailable'

def test_local_jevedge_loader_requires_explicit_files_and_records_hashes(tmp_path):
    from quix_knowledge.hybrid import JevEdgeEmbedder
    root=tmp_path/'jev'
    source=root/'jevedge0'/'rag'/'embed.py'
    source.parent.mkdir(parents=True)
    source.write_text('class BertEmbedder:\n    def __init__(self, model): self.max_length = 256\n    def encode(self, texts): return [[1.0] for _ in texts]\n')
    model=tmp_path/'model'
    model.mkdir()
    with pytest.raises(ValueError):
        JevEdgeEmbedder(root,model)
    for filename in ('config.json','tokenizer.json','model.safetensors'):
        (model/filename).write_text('fixture')
    embedder=JevEdgeEmbedder(root,model)
    assert embedder.encode(['a']) == [[1.0]]
    assert len(embedder.metadata['weights_sha256']) == 64
    assert embedder.metadata['max_input_tokens'] == 256
    assert str(tmp_path) not in str(embedder.metadata)

def test_hybrid_marks_inputs_that_are_character_truncated(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nretry '+('long '*2000))
    ingest(db,path)
    result=search(db,'retry',ranking='hybrid',embedder=FakeEmbedder())
    assert result[0]['embedding_text_truncated'] is True

def test_catalog_change_during_embedding_is_not_returned_as_current(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetry allowed.')
    ingest(db,path)
    class ChangingEmbedder:
        def encode(self,texts):
            path.write_text('# Retry\nRetry prohibited.')
            ingest(db,path)
            return [[1.0,0.0] for _ in texts]
    with pytest.raises(RuntimeError,match='catalog changed'):
        search(db,'retry',ranking='hybrid',embedder=ChangingEmbedder())

def test_zero_similarity_without_lexical_match_is_not_a_candidate(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Engines\nA motor drives a wheel.')
    ingest(db,path)
    assert search(db,'feline',ranking='hybrid',embedder=FakeEmbedder()) == []

def test_partial_zero_vectors_are_visible_on_lexical_results(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetry failure.\n# Other\nDifferent content.')
    ingest(db,path)
    class Partial:
        def encode(self,texts):
            return [[1.0,0.0],[0.0,0.0],[1.0,0.0]]
    rows=search(db,'retry',ranking='hybrid',embedder=Partial())
    assert next(row for row in rows if row['title']=='Retry')['embedding_issue'] == 'zero_document_vector'
    assert all(row['embedding_zero_vector_count'] == 1 for row in rows)
