"""Run the isolated HITMCockpit planner executable as a bounded child process."""
import json
import copy
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

_STATUSES={'invalid_request','configuration_missing','agent_failure','intent_too_large','task_mismatch','source_changed','context_invalid','unsupported_or_stale_evidence'}


def validate_role_bindings(tasks, definitions):
    if not isinstance(tasks,list) or not isinstance(definitions,dict) or not definitions:
        raise ValueError('invalid role definitions')
    for role,definition in definitions.items():
        if not isinstance(role,str) or not role.strip() or not isinstance(definition,dict):
            raise ValueError('invalid role definition')
        version=definition.get('version'); purpose=definition.get('purpose')
        if not isinstance(version,str) or not version.strip() or not isinstance(purpose,str) or not purpose.strip() or len(purpose)>500:
            raise ValueError('invalid role definition')
        try: purpose.encode('utf-8')
        except UnicodeError: raise ValueError('invalid role purpose encoding') from None
    for task in tasks:
        if not isinstance(task,dict) or task.get('role') not in definitions or task.get('role_version')!=definitions[task['role']]['version']:
            raise ValueError('task role definition mismatch')


class PlannerProcess:
    def __init__(self, command, *, api_key, model, timeout=60, role_definitions=None):
        if not isinstance(command,list) or not command or not all(isinstance(x,str) and x for x in command) or not api_key or not model or not 0 < timeout <= 120:
            raise ValueError('invalid process configuration')
        self.command=list(command)
        resolved=shutil.which(self.command[0])
        if resolved is None:
            raise ValueError('planner executable unavailable')
        self.command[0]=str(Path(resolved).resolve())
        try:
            self.executable_sha256=hashlib.sha256(Path(self.command[0]).read_bytes()).hexdigest()
        except OSError as exc:
            raise ValueError('planner executable unavailable') from exc
        self._key=api_key
        self.model=model
        self.timeout=timeout
        if role_definitions is not None:
            validate_role_bindings([],role_definitions)
        self.role_definitions=copy.deepcopy(role_definitions)

    def __call__(self, request):
        payload={'task':request['query'],'role':request['role'],'role_version':request['role_version'],'packet':request['context']}
        if self.role_definitions is not None:
            definition=self.role_definitions.get(request['role'])
            if not definition or definition['version']!=request['role_version'] or request.get('role_purpose',definition['purpose'])!=definition['purpose']:
                return {'status':'role_definition_mismatch'}
            payload['role_purpose']=definition['purpose']
        raw=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()
        if len(raw)>500_000:
            return {'status':'input_budget_exceeded'}
        environment={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'OPENROUTER_API_KEY':self._key,'QUIX_STUDY_AGENT_MODEL':self.model}
        try:
            if hashlib.sha256(Path(self.command[0]).read_bytes()).hexdigest()!=self.executable_sha256:
                return {'status':'executable_changed'}
            with tempfile.TemporaryFile() as output:
                process=subprocess.run(self.command,input=raw,stdout=output,stderr=subprocess.DEVNULL,env=environment,timeout=self.timeout,check=False)
                if hashlib.sha256(Path(self.command[0]).read_bytes()).hexdigest()!=self.executable_sha256:
                    return {'status':'executable_changed'}
                if process.returncode != 0 or output.tell()>500_000:
                    return {'status':'process_failure'}
                output.seek(0); result=json.load(output)
        except subprocess.TimeoutExpired:
            raise TimeoutError() from None
        except (OSError,ValueError):
            return {'status':'process_failure'}
        if not isinstance(result,dict):
            return {'status':'invalid_response'}
        call=result.get('call') if isinstance(result.get('call'),dict) else None
        status=result.get('status')
        if status in _STATUSES:
            return {'status':status,'call':call}
        if status!='completed' or not isinstance(result.get('proposal'),dict):
            return {'status':'invalid_response','call':call}
        return {'output':json.dumps(result['proposal'],ensure_ascii=False,sort_keys=True),'usage':{'cost':call.get('costUSD')} if call else None,'call':call}
