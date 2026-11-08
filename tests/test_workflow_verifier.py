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
        if 'test_source_browser.py' in ' '.join(command) or 'test_workflow_browser.py' in ' '.join(command):
            return SimpleNamespace(returncode=0,stdout='1 skipped in 0.02s\n')
        if command[-1].endswith('.py'):
            return SimpleNamespace(returncode=0,stdout='{"status":"passed"}\n')
        return SimpleNamespace(returncode=0,stdout='1 passed in 0.02s\n')
    report=verifier.run_offline(run=fake_run)
    assert report['status']=='incomplete'
    assert report['checks']['two_browser_clients']['status']=='skipped'
    assert report['checks']['fresh_browser_journey']['status']=='skipped'
    assert 'fresh_browser_journey' in report['unmet']
    assert report['hosted_provider']=='not_exercised'


def test_workflow_verifier_can_pass_when_each_required_check_passes():
    verifier=load_verifier()
    def fake_run(command, **kwargs):
        output='1 passed in 0.02s\n' if '-m' in command else '{"status":"passed"}\n'
        return SimpleNamespace(returncode=0,stdout=output)
    report=verifier.run_offline(run=fake_run)
    assert report['status']=='passed' and report['unmet']==[]
    assert report['checks']['fresh_browser_journey']['status']=='passed'
    assert report['hosted_provider']=='not_exercised'


def test_clean_install_verifier_cannot_pass_without_browser_configuration(monkeypatch):
    path=Path(__file__).resolve().parents[1]/'scripts'/'verify_clean_install.py'
    spec=importlib.util.spec_from_file_location('qjig_clean_install_verifier',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.delenv('QJIG_CHROMIUM_PATH',raising=False)
    monkeypatch.setattr(module.subprocess,'run',lambda *args,**kwargs:SimpleNamespace(returncode=0))
    assert module.main() != 0
