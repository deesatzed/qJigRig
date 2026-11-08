"""The full draft harness must explicitly reserve its separate review stage."""
import importlib.util
from pathlib import Path


def test_synthetic_factorial_configuration_has_opt_in_semantic_review():
    path=Path(__file__).resolve().parents[1]/'scripts'/'smoke_factorial_synthetic.py'
    spec=importlib.util.spec_from_file_location('synthetic_factorial',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stage={'provider':'stand-in'}
    legacy=module.stage_configuration(stage,semantic=False)
    reviewed=module.stage_configuration(stage,semantic=True)
    assert 'semantic_reviewer' not in legacy and reviewed['semantic_reviewer']==stage
    assert reviewed['semantic_reviewer'] is not stage
