"""Offline synthetic exception fixture; no model calls and no network."""
from . import core

RULE = 'Events above 50 attendees require a permit unless they are school events.'
BASE = RULE + '\nAttendance: 75\nSchool event: yes'
CHANGED = RULE + '\nAttendance: 75\nSchool event: no'
MISSING = RULE + '\nAttendance: 75'

def evaluate(text):
    """Only explicit fixture records are meaningful. Missing facts are unknown."""
    if RULE not in text.splitlines():
        return {'status':'deferred','answer':None,'reason':'Governing rule missing','trace':[]}
    lines=text.splitlines()
    attendance=None
    vals=[x.removeprefix('Attendance: ') for x in lines if x.startswith('Attendance: ')]
    if len(vals)==1 and vals[0].isdigit(): attendance=int(vals[0])>50
    schools=[x.removeprefix('School event: ') for x in lines if x.startswith('School event: ')]
    school={'yes':True,'no':False}.get(schools[0]) if len(schools)==1 else None
    expr={'op':'and','args':[{'ref':'above'},{'op':'not','args':[{'ref':'school'}]}]}
    outcome=core.compose(expr,{'above':attendance,'school':school})
    return {'status':'deferred' if outcome is None else 'decided',
            'answer':None if outcome is None else ('permit required' if outcome else 'permit not required'),
            'reason':'Material input missing or conflicting' if outcome is None else 'Synthetic exact-rule composition',
            'trace':[{'predicate':'above','value':attendance}, {'predicate':'school','value':school}],
            'expression':expr,'evidence':[x for x in lines if x==RULE or x.startswith(('Attendance: ','School event: '))],
            'mode':'offline synthetic fixture','network_calls':0}

def demo():
    return {'label':'offline synthetic fixture; not model results',
            'cases':{'original':evaluate(BASE),'exception_withdrawn':evaluate(CHANGED),
                     'exception_unknown':evaluate(MISSING)}}
