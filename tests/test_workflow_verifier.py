"""The workflow gate must not promote skipped checks or an incomplete journey."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace


def load_verifier():
    path=Path(__file__).resolve().parents[1]/'scripts'/'verify_workflow.py'
    spec=importlib.util.spec_from_file_location('qjig_workflow_verifier',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_workflow_verifier_rejects_skips_and_keeps_unproved_journey_open():
    verifier=load_verifier()
    def fake_run(command, **kwargs):
        if 'test_source_browser.py' in ' '.join(command):
            return SimpleNamespace(returncode=0,stdout='1 skipped in 0.02s\n')
        if command[-1].endswith('.py'):
            return SimpleNamespace(returncode=0,stdout='{"status":"passed"}\n')
        return SimpleNamespace(returncode=0,stdout='1 passed in 0.02s\n')
    report=verifier.run_offline(run=fake_run)
    assert report['status']=='incomplete'
    assert report['checks']['two_browser_clients']['status']=='skipped'
    assert 'complete_fresh_browser_journey_unverified' in report['unmet']
    assert report['hosted_provider']=='not_exercised'
