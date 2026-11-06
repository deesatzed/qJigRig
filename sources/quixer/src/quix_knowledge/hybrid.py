"""Validate dense vectors and compute cosine similarities without numpy."""
import math
import hashlib
import importlib.util
from pathlib import Path


def _file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda:file.read(1024*1024),b''):
            digest.update(block)
    return digest.hexdigest()


class JevEdgeEmbedder:
    """Load JevEdge0's encoder with an explicit existing local checkpoint."""
    def __init__(self, jevedge_root, model_dir):
        root = Path(jevedge_root).resolve()
        model = Path(model_dir).resolve()
        source = root/'jevedge0'/'rag'/'embed.py'
        required = [source,model/'config.json',model/'tokenizer.json',model/'model.safetensors']
        if not model.is_dir() or any(not path.is_file() for path in required):
            raise ValueError('JevEdge0 source and local model files are required; downloads are not attempted')
        spec = importlib.util.spec_from_file_location('_quix_jevedge_embed',source)
        if spec is None or spec.loader is None:
            raise ValueError('unable to load JevEdge0 encoder')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._encoder = module.BertEmbedder(model=str(model))
        self.metadata = {'name':'JevEdge0 BertEmbedder','backend':'mlx','source_sha256':_file_hash(source),'config_sha256':_file_hash(model/'config.json'),'tokenizer_sha256':_file_hash(model/'tokenizer.json'),'weights_sha256':_file_hash(model/'model.safetensors'),'max_input_tokens':self._encoder.max_length,'input_policy':'model tokenizer truncates input at max_input_tokens'}

    def encode(self,texts):
        return self._encoder.encode(texts)


def similarities(embedder, query, texts):
    vectors = embedder.encode([query,*texts])
    if len(vectors) != len(texts)+1:
        raise ValueError('embedder returned wrong vector count')
    converted = []
    dimension = None
    for vector in vectors:
        values = [float(value) for value in vector]
        if not values or any(not math.isfinite(value) for value in values):
            raise ValueError('embedder returned invalid vector')
        if dimension is None:
            dimension = len(values)
        if len(values) != dimension:
            raise ValueError('embedder returned inconsistent dimensions')
        norm = math.sqrt(sum(value*value for value in values))
        if not math.isfinite(norm):
            raise ValueError('embedder returned an invalid vector norm')
        converted.append(None if norm == 0 else [value/norm for value in values])
    if converted[0] is None:
        raise ValueError('embedder returned zero query vector')
    if texts and not any(vector is not None for vector in converted[1:]):
        raise ValueError('embedder returned only zero document vectors')
    return [None if doc is None else sum(a*b for a,b in zip(converted[0],doc)) for doc in converted[1:]]
