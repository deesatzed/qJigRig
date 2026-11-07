"""Crash persistence with a synthetic transport; no hosted requests are made."""
import os
from pathlib import Path
import subprocess
import sys
import threading

from qjig.agents import RoleClient
from qjig.contracts import Budget
from qjig.fresh_service import FreshWorkbench
from qjig.goal_budget import GoalBudget
from qjig.providers import StandInTransport
from qjig.roles import RoleDefinition
from qjig.service import create_server


CRASH_WORKER = r'''
import os, sys
from pathlib import Path
from qjig.contracts import Budget
from qjig.fresh_service import FreshWorkbench
from qjig.goal_budget import GoalBudget
from qjig.providers import StandInTransport
root = Path(sys.argv[1])
model = {'id':'synthetic/model','context_length':10000,'top_provider':{'max_completion_tokens':1000},
         'pricing':{'prompt':'0.000001','completion':'0.000002'}}
spec = {'provider':'stand-in','model':model,'input_tokens':1000,'output_tokens':100,
        'max_price':{'prompt':2,'completion':3}}
limit,total=Budget(30,100000,1),Budget(60,200000,2)
class CrashTransport(StandInTransport):
    def send(self, request):
        os._exit(72)
backend=FreshWorkbench(root/'fresh',goal_factory=lambda:GoalBudget.open(root/'goal.sqlite',
    total=total,per_request=limit,allocations={'smoke':total}),transport_factory=lambda:CrashTransport([]),
    partition='smoke',planner=spec,judge=spec,reviewer=spec,budget=limit)
request={'schema_version':'qjig.request.v1','request_id':'crash','question':'Refund limit?',
         'role':'reviewer','role_version':'1','scope':'project'}
backend.run(root/'catalog.sqlite',{'request':request,'as_of':'2026-11-15','entities':[]})
os._exit(73)
'''


def test_process_exit_leaves_incomplete_fresh_run_without_retry(tmp_path):
    path = tmp_path/'catalog.sqlite'
    server = create_server(path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        client = RoleClient(server.server_address[1], RoleDefinition('reviewer','1','Review'))
        client.import_source({'source_id':'policy.md','text':'# Policy\nRefunds within 14 days.\n',
            'scope':'project','entities':[],'effective_from':'2026-01-01','effective_to':'open',
            'observed_at':None,'authority':None})
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
    env = {**os.environ, 'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src')}
    child = subprocess.run([sys.executable,'-c',CRASH_WORKER,str(tmp_path)], env=env,
                           capture_output=True, text=True, timeout=15)
    assert child.returncode == 72, child.stderr
    model = {'id':'synthetic/model','context_length':10000,'top_provider':{'max_completion_tokens':1000},
             'pricing':{'prompt':'0.000001','completion':'0.000002'}}
    spec = {'provider':'stand-in','model':model,'input_tokens':1000,'output_tokens':100,
            'max_price':{'prompt':2,'completion':3}}
    limit,total=Budget(30,100000,1),Budget(60,200000,2)
    transport = StandInTransport([])
    backend = FreshWorkbench(tmp_path/'fresh',goal_factory=lambda:GoalBudget.open(tmp_path/'goal.sqlite',
        total=total,per_request=limit,allocations={'smoke':total}),transport_factory=lambda:transport,
        partition='smoke',planner=spec,judge=spec,reviewer=spec,budget=limit)
    server = create_server(path, port=0, fresh_backend=backend)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        client = RoleClient(server.server_address[1],RoleDefinition('reviewer','1','Review'))
        runs=client.list_fresh_runs()
        assert len(runs)==1 and runs[0]['replay_status']=='incomplete'
        replay=client.get_fresh_run(runs[0]['run_id'])
        assert replay['result'] is None and replay['reconciliation']['status']=='required'
        assert replay['reconciliation']['unresolved'][0]['stage']=='planner'
        with GoalBudget.open(tmp_path/'goal.sqlite', total=total, per_request=limit, allocations={'smoke':total}) as goal:
            usage=goal.actual_usage()
            assert usage['calls']==1 and usage['unknown_calls']==1 and usage['cost_usd'] is None
        result=client.ask_fresh('new-id','Refund limit?','project',as_of='2026-11-15',entities=[])
        assert result['status']=='deferred' and result['plan_failure']=='budget_exceeded'
        assert transport.calls_made == 0
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
