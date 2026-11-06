"""Loopback-only adapter to a separately running JevEdge0 workbench."""
import ipaddress
import json
import math
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('local JevEdge0 redirects are not allowed')


def _transport(request, timeout):
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    with opener.open(request,timeout=timeout) as response:
        return json.load(response)


class JevEdgeDecision:
    prompt_version = 'quix-jevedge-choice-v1'
    def __init__(self, base_url='http://127.0.0.1:8090', *, transport=_transport, timeout=30, stability_trials=1, thresholds=None):
        parsed = urlsplit(base_url)
        host = parsed.hostname or ''
        try:
            loopback = host == 'localhost' or ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
        if parsed.scheme != 'http' or not loopback or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment:
            raise ValueError('JevEdge0 endpoint must be an HTTP loopback origin')
        if not isinstance(stability_trials,int) or isinstance(stability_trials,bool) or not 1 <= stability_trials <= 10:
            raise ValueError('stability_trials must be between 1 and 10')
        if thresholds is not None and (len(thresholds) != 2 or not 0 <= thresholds[0] < thresholds[1] <= 1):
            raise ValueError('invalid experimental thresholds')
        self.url = base_url.rstrip('/') + '/v1/decisions'
        self.transport, self.timeout, self.trials, self.thresholds = transport, timeout, stability_trials, thresholds

    def __call__(self,state,question):
        questions = {'relevant':'Is the supplied text relevant to the query?', 'topic supported':'Does the supplied text substantively support the proposed topic?', 'structure usable':'Do the supplied section titles and text provide useful navigational structure for this document?', 'role usefulness':'Would this text be useful for the supplied role and its defined purpose?'}
        if question not in questions:
            raise ValueError('unsupported decision question')
        payload = {'state':state, 'criterion':questions[question], 'options':[{'id':'yes','description':'Yes, the evidence supports this.'},{'id':'no','description':'No, the evidence does not support this.'}], 'stability_trials':self.trials}
        request = Request(self.url,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'},method='POST')
        data = self.transport(request,self.timeout)
        scores = data.get('probabilities')
        if not isinstance(scores,dict) or set(scores) != {'yes','no'}:
            raise ValueError('invalid option scores')
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in scores.values()) or not math.isclose(sum(scores.values()),1,abs_tol=0.0001):
            raise ValueError('invalid option scores')
        legal_mass = data.get('legal_mass')
        if legal_mass is not None and (isinstance(legal_mass,bool) or not isinstance(legal_mass,(int,float)) or not math.isfinite(legal_mass) or not 0 <= legal_mass <= 1):
            raise ValueError('invalid legal mass')
        stability = data.get('stability')
        stable = self.trials == 1 or (isinstance(stability,dict) and stability.get('stable_across_permutations') is True and stability.get('trials',0) >= self.trials)
        outcome = 'unclear'
        if self.thresholds and stable:
            low,high = self.thresholds
            outcome = 'unsuitable' if scores['yes'] <= low else 'supported' if scores['yes'] >= high else 'unclear'
        model = data.get('model')
        model_name = model.get('name') if isinstance(model,dict) else None
        return {'provider':'jevedge0','model':model_name,'outcome':outcome,'probability':scores['yes'],'probability_status':'conditional_option_score_uncalibrated','legal_mass':legal_mass,'stability':stability,'thresholds':self.thresholds,'prompt_version':self.prompt_version}
