"""In-process browser workers; durable recovery remains in the dataset journal."""
import threading
from . import core, datasets

_lock=threading.Lock()
_jobs={}

def _start_worker(ident):
    def worker():
        try:
            datasets.resume(ident,consent=True)
        except Exception as exc:
            with _lock: _jobs[ident]['state']='error'; _jobs[ident]['error']=str(exc)
        else:
            with _lock: _jobs[ident]['state']='finished'
    thread=threading.Thread(target=worker,daemon=True,name='dataset-'+ident)
    with _lock:
        if _jobs.get(ident,{}).get('state')=='running': raise ValueError('Dataset worker is already running')
        _jobs[ident]={'state':'running','thread':thread}
        try: thread.start()
        except Exception:
            del _jobs[ident]
            raise

def start_dataset(*args,**kwargs):
    run=datasets.prepare(*args,**kwargs)
    _start_worker(run['id'])
    return run

def resume_dataset(ident,consent=False):
    if consent is not True: raise ValueError('Source-sharing consent is required to resume')
    if not isinstance(ident,str): raise ValueError('Invalid dataset run ID')
    run=core.load('dataset_runs',ident)
    _start_worker(ident)
    return run

def status(ident):
    with _lock:
        job=_jobs.get(ident)
        return {k:v for k,v in job.items() if k!='thread'} if job else {'state':'not_tracked'}

def wait(ident,timeout=None):
    with _lock: thread=_jobs[ident]['thread']
    thread.join(timeout)
