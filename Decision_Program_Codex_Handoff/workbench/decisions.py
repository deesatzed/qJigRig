"""OpenRouter typed Decisions API: experimental scores, not verified findings."""
import hashlib
import json
import time
import urllib.error
import urllib.request
from . import core

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def probe(state, question, model, consent):
    if consent is not True:
        raise ValueError('Explicit consent is required to send source text to OpenRouter')
    if not state.strip() or not question.strip() or not model:
        raise ValueError('State, question, and a decisions model are required')
    key = core.config().get('OPENROUTER_API_KEY')
    if not key:
        raise ValueError('OPENROUTER_API_KEY is required')
    # Ask about support only: a low score does not prove contradiction.
    request_body = {'model': model, 'state': state, 'questions': {'supported': {
        'type': 'noul', 'instructions': 'Does the state explicitly support the following proposition? '+question,
        'criteria': {'true': 'The state explicitly supports the proposition',
                     'false': 'The state does not explicitly support the proposition'}}}}
    req = urllib.request.Request('https://openrouter.ai/api/alpha/decisions',
        data=json.dumps(request_body).encode(), headers={'Authorization': 'Bearer '+key,
        'Content-Type': 'application/json'}, method='POST')
    start=time.monotonic()
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=90) as response:
            data=json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            message=json.loads(exc.read()).get('error',{}).get('message','')
        except (ValueError, AttributeError):
            message=''
        raise RuntimeError(f'OpenRouter HTTP {exc.code}: {message[:300]}') from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f'OpenRouter connection failed: {exc.reason}') from None
    answer=data.get('answers',{}).get('supported')
    if not isinstance(answer,dict) or answer.get('type') != 'noul' or not isinstance(answer.get('noul'),(int,float)) or isinstance(answer.get('noul'),bool) or not 0 <= answer['noul'] <= 1:
        raise ValueError('Invalid typed Decisions API response')
    return {'model':data.get('model',model),'question':question,'answer':answer,
            'state_sha256':hashlib.sha256(state.encode()).hexdigest(),
            'elapsed_seconds':round(time.monotonic()-start,3),'usage':data.get('usage'),
            'interpretation':'Experimental model score; not a verified fact, contradiction, or calibrated probability for this task.'}
