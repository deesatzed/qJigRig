"""Freeze non-secret model identities and prompt revisions for an experiment."""
import hashlib
from . import core

RUNTIME_FILES=('core.py','collections.py','retrieval.py','local_retrieval.py','local_judge.py',
               'local_worker.py','programs.py','compare.py','datasets.py','jobs.py','experiments.py','web_research.py','verify_run.py')

def runtime_hashes():
    return {name:hashlib.sha256((core.ROOT/'workbench'/name).read_bytes()).hexdigest() for name in RUNTIME_FILES}

def prompt_hashes():
    prompts={'planner':core.PLAN_PROMPT,'predicate_judge':core.JUDGE_PROMPT,'predicate_repair':core.JUDGE_REPAIR_PROMPT,
             'repair':core.PLAN_PROMPT+core.REPAIR_SUFFIX,'answer_check':core.ANSWER_CHECK_PROMPT,'answer_check_repair':core.ANSWER_CHECK_REPAIR_PROMPT,'direct':core.DIRECT_PROMPT,'direct_repair':core.DIRECT_REPAIR_PROMPT,'search':core.SEARCH_PROMPT}
    return {name:hashlib.sha256(value.encode()).hexdigest() for name,value in prompts.items()}

def freeze_config(config):
    small=config.get('OPENROUTER_PLANNER_MODEL') or config.get('OPENROUTER_DEC_MODEL_1')
    frontier=config.get('OPENROUTER_TOP_MODEL')
    for model in (small,frontier):
        if not isinstance(model,str) or not model.strip(): raise ValueError('Both small and frontier models must be configured')
        if ':online' in model.lower(): raise ValueError('Online model variants are not permitted in bounded comparisons')
    return {'small_model':small,'frontier_model':frontier,'prompt_hashes':prompt_hashes(),'runtime_hashes':runtime_hashes(),
            'web_plugin':'explicitly disabled for bounded calls',
            'provider_revision':'resolved model and provider are recorded per call when returned'}

def validate_config(frozen):
    if frozen.get('runtime_hashes')!=runtime_hashes(): raise ValueError('Runtime code changed or runtime fingerprint missing since experiment launch')
    if frozen.get('prompt_hashes')!=prompt_hashes(): raise ValueError('Prompt configuration changed since experiment launch')
    for key in ('small_model','frontier_model'):
        model=frozen.get(key)
        if not isinstance(model,str) or not model.strip() or ':online' in model.lower(): raise ValueError('Invalid frozen model configuration')
    return frozen
