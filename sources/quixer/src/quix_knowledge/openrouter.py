"""OpenRouter Decisions adapter; scores are not calibrated task accuracy."""
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from urllib.request import Request, urlopen

@dataclass(frozen=True)
class Settings:
    api_key: str = field(repr=False)
    model: str

def load_settings(path, slot):
    if slot not in (1, 2, 3, 4):
        raise ValueError('model slot must be 1 through 4')
    try:
        lines = Path(path).read_text(encoding='utf-8').splitlines()
    except OSError as exc:
        raise ValueError('settings file unavailable') from exc
    values = {}
    wanted = {'OPENROUTER_API_KEY',f'OPENROUTER_DEC_MODEL_{slot}'}
    for line in lines:
        line = line.strip()
        if line.startswith('export '):
            line = line[7:]
        if '=' not in line or line.startswith('#'):
            continue
        key, value = line.split('=', 1)
        if key.strip() in wanted:
            values[key.strip()] = value.strip().strip('"\'')
    key, model = values.get('OPENROUTER_API_KEY'), values.get(f'OPENROUTER_DEC_MODEL_{slot}')
    if not key or not model:
        raise ValueError('OpenRouter key or configured model missing')
    return Settings(key,model)

def _request(request, timeout):
    with urlopen(request,timeout=timeout) as response:
        return json.load(response)

class OpenRouterDecision:
    prompt_version = 'quix-openrouter-noul-v1'
    def __init__(self, settings, transport=_request, timeout=30, thresholds=None):
        if thresholds is not None and (len(thresholds) != 2 or not 0 <= thresholds[0] < thresholds[1] <= 1):
            raise ValueError('thresholds must satisfy 0 <= low < high <= 1')
        self.settings, self.transport, self.timeout = settings, transport, timeout
        self.thresholds = thresholds

    def __call__(self, state, question):
        questions = {'relevant':'Is the supplied text relevant to the query?', 'topic supported':'Does the supplied text substantively support the proposed topic?', 'structure usable':'Do the supplied section titles and text provide useful navigational structure for this document?', 'role usefulness':'Would this text be useful for the supplied role and its defined purpose?'}
        if question not in questions:
            raise ValueError('unsupported decision question')
        payload = {'model':self.settings.model,'state':state,'questions':{'judgment':{'type':'noul','instructions':questions[question]}}}
        req = Request('https://openrouter.ai/api/alpha/decisions',data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+self.settings.api_key,'Content-Type':'application/json'},method='POST')
        data = self.transport(req,self.timeout)
        answer = data.get('answers',{}).get('judgment',{})
        probability = answer.get('noul')
        if answer.get('type') != 'noul' or isinstance(probability,bool) or not isinstance(probability,(int,float)) or not math.isfinite(probability) or not 0 <= probability <= 1:
            raise ValueError('invalid decision response')
        outcome = 'unclear'
        if self.thresholds is not None:
            low, high = self.thresholds
            outcome = 'unsuitable' if probability <= low else 'supported' if probability >= high else 'unclear'
        return {'outcome':outcome,'provider':'openrouter','model':data.get('model',self.settings.model),'probability':probability,'usage':data.get('usage'), 'request_id':data.get('id'),'thresholds':self.thresholds,'prompt_version':self.prompt_version}
