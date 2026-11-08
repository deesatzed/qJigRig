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


def test_synthetic_quota_requires_semantic_review_and_valid_range():
    import os
    import subprocess
    import sys
    root=Path(__file__).resolve().parents[1]
    env={**os.environ,'PYTHONPATH':str(root/'src')}
    for args in (['--judge-pairs','2'],['--semantic','--judge-pairs','0'],['--semantic','--judge-pairs','13']):
        result=subprocess.run([sys.executable,str(root/'scripts'/'smoke_factorial_synthetic.py'),*args],
                              cwd=root,env=env,capture_output=True,text=True,timeout=10)
        assert result.returncode==2 and '--judge-pairs requires --semantic' in result.stderr
    for args in (['--outcome'],['--outcome','--semantic'],['--outcome','--judge-pairs','2']):
        result=subprocess.run([sys.executable,str(root/'scripts'/'smoke_factorial_synthetic.py'),*args],
                              cwd=root,env=env,capture_output=True,text=True,timeout=10)
        assert result.returncode==2 and '--outcome requires --semantic and --judge-pairs' in result.stderr


def test_synthetic_factorial_configuration_has_opt_in_outcome_review():
    path=Path(__file__).resolve().parents[1]/'scripts'/'smoke_factorial_synthetic.py'
    spec=importlib.util.spec_from_file_location('synthetic_factorial_outcome',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    stage={'provider':'stand-in'}
    configured=module.stage_configuration(stage,semantic=True,outcome=True)
    assert configured['outcome_reviewer']==stage and configured['outcome_reviewer'] is not stage
    import pytest
    with pytest.raises(ValueError):
        module.stage_configuration(stage,semantic=False,outcome=True)
