"""Isolated, resident JSON-lines worker for synthetic or user-supplied support probes."""
import contextlib
import importlib.metadata
import json
import platform
import sys
import time
from .local_judge import MODEL, REVISION, MAX_TOKENS, QUESTION

def worker_environment():
    packages={}
    for name in ('unsloth','mlx','transformers','huggingface-hub'):
        try: packages[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: packages[name]=None
    return {'python':platform.python_version(),'packages':packages}

def main():
    if sys.argv[1:]==['--environment']:
        print(json.dumps(worker_environment()))
        return
    with contextlib.redirect_stdout(sys.stderr):
        from unsloth import FastDecisionModel
        from unsloth._decision_mlx import _clef_question
        model,tokenizer=FastDecisionModel.from_pretrained(MODEL,revision=REVISION,max_seq_length=MAX_TOKENS,load_in_4bit=False,local_files_only=True)
        FastDecisionModel.for_inference(model)
    pipeline=model._unsloth_pipeline
    environment=worker_environment()
    for line in sys.stdin:
        start=time.monotonic()
        try:
            request=json.loads(line)
            state={'authoritative_context':request['source'],'assistant_response':request['claim']}
            # encode() without a max_length is essential: the bounded form silently truncates state.
            parsed=pipeline._parse_questions({str(name):_clef_question(question) for name,question in QUESTION.items()})
            token_ids,_,_=pipeline.encode(state,parsed,max_length=None)
            count=len(token_ids)
            if count > MAX_TOKENS: raise ValueError(f'Input exceeds local judge limit: {count} > {MAX_TOKENS} tokens')
            with contextlib.redirect_stdout(sys.stderr):
                prediction=FastDecisionModel.predict(model,tokenizer,json.dumps(state),QUESTION)
            response={'prediction':prediction,'input_tokens':count,'elapsed_seconds':round(time.monotonic()-start,3),'environment':environment}
        except Exception as exc:
            response={'error':str(exc) if isinstance(exc,ValueError) else f'Local judge inference failed: {type(exc).__name__}'}
        print(json.dumps(response),flush=True)

if __name__=='__main__': main()
