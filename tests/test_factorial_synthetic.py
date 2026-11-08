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


def test_synthetic_rubric_design_rebinds_without_mutating_draft():
    import copy
    import hashlib
    import pytest
    from qjig.evaluation import validate_evaluation_design
    from qjig.evaluation_cases import case_lock_digest
    path=Path(__file__).resolve().parents[1]/'scripts'/'smoke_factorial_synthetic.py'
    spec=importlib.util.spec_from_file_location('synthetic_factorial_rubric',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    from test_evaluation import _sample_design
    design=_sample_design()
    lock={'schema':'qjig.evaluation-case.v1','case_id':'dev',
          'design_sha256':validate_evaluation_design(design),'question':'Do checks pass?',
          'role':'reviewer','role_version':'1','scope':'project','as_of':'2026-11-07',
          'entities':[],'historical_as_known':False,
          'sources':[{'path':'synthetic.txt','sha256':hashlib.sha256(b'synthetic').hexdigest()}],
          'reference_sha256':hashlib.sha256(b'fictional reference').hexdigest()}
    locks={'dev':{'lock':lock,'sha256':case_lock_digest(lock)}}
    original_design=copy.deepcopy(design);original_locks=copy.deepcopy(locks)
    new_design,new_locks=module.synthetic_rubric_design(design,locks)
    digest=validate_evaluation_design(new_design)
    assert digest != validate_evaluation_design(design)
    assert new_design['criteria']['retain']['threshold']==0.6
    assert all(v['lock']['design_sha256']==digest and v['sha256']==case_lock_digest(v['lock']) for v in new_locks.values())
    assert design==original_design and locks==original_locks
    altered=copy.deepcopy(locks);next(iter(altered.values()))['lock']['question']='changed'
    with pytest.raises(ValueError): module.synthetic_rubric_design(design,altered)
