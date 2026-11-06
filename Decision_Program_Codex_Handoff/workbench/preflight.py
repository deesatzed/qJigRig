"""Read-only configuration checks; no provider calls or model imports."""
import os
from pathlib import Path
from . import core


def inspect():
    config=core.config()
    small=config.get('OPENROUTER_PLANNER_MODEL') or config.get('OPENROUTER_DEC_MODEL_1')
    frontier=config.get('OPENROUTER_TOP_MODEL')
    def bounded_model(value):
        return isinstance(value,str) and bool(value.strip()) and ':online' not in value.lower()
    python=config.get('LOCAL_JUDGE_PYTHON') or str(core.ROOT/'.venv-judge'/'bin'/'python')
    worker=Path(python)
    worker_executable=worker.is_file() and os.access(worker,os.X_OK)
    dependencies=False
    if worker_executable:
        try:
            from .local_judge import inspect_worker_environment
            inspect_worker_environment(); dependencies=True
        except ValueError:
            pass
    try:
        from .web_research import parse_tool_budget
        parse_tool_budget(config.get('OPENROUTER_WEB_TOOL_BUDGET_USD'))
        budget=True
    except ValueError:
        budget=False
    key=config.get('OPENROUTER_API_KEY')
    endpoint=config.get('BASE_URL','https://openrouter.ai/api/v1')
    return {'api_key_present':isinstance(key,str) and bool(key.strip()),
            'provider_endpoint_supported':isinstance(endpoint,str) and endpoint.rstrip('/').startswith('https://openrouter.ai/'),
            'small_model_configured':bounded_model(small),
            'frontier_model_configured':bounded_model(frontier),
            'local_judge_python_executable':worker_executable,
            'local_judge_dependencies_present':dependencies,
            'web_tool_budget_configured':budget,
            'interpretation':'Checks local configuration, executable and dependency metadata only; credentials, package imports, model weights, hardware, provider limits, and costs are not verified.'}
