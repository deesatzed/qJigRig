"""In-memory Okapi BM25 for a small immutable set of candidate texts."""
from collections import Counter
import math
import re


def score_documents(query, documents, k1=1.5, b=0.75, corpus=None):
    if k1 <= 0 or not 0 <= b <= 1:
        raise ValueError('invalid BM25 parameters')
    tokenized = [re.findall(r'\w+',doc.lower()) for doc in documents]
    corpus_tokenized = tokenized if corpus is None else [re.findall(r'\w+',doc.lower()) for doc in corpus]
    if not corpus_tokenized:
        return [0.0] * len(tokenized)
    average = sum(map(len,corpus_tokenized))/len(corpus_tokenized)
    if not average:
        return [0.0] * len(tokenized)
    counts = [Counter(doc) for doc in tokenized]
    corpus_counts = [Counter(doc) for doc in corpus_tokenized]
    terms = set(re.findall(r'\w+',query.lower()))
    frequencies = {term:sum(term in doc for doc in corpus_counts) for term in terms}
    idf = {term:math.log1p((len(corpus_counts)-df+0.5)/(df+0.5)) for term,df in frequencies.items()}
    result = []
    for words,doc in zip(tokenized,counts):
        norm = k1*(1-b+b*len(words)/average)
        result.append(sum(idf[t]*doc[t]*(k1+1)/(doc[t]+norm) for t in terms if doc[t]))
    return result
