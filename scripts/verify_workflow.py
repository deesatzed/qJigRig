#!/usr/bin/env python3
"""Run available local workflow checks without claiming a complete product journey."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_offline(*, run=subprocess.run):
    """Run real synthetic checks; skipped, malformed or missing evidence is incomplete."""
    checks = {
        'authored_browser_restart_export': [sys.executable, 'scripts/verify_saved_run_browser.py'],
        'review_browser_intervention': [sys.executable, 'scripts/verify_review_browser.py'],
        'fresh_browser_journey': [sys.executable, '-m', 'pytest', 'tests/test_workflow_browser.py::test_complete_synthetic_fresh_browser_journey', '-q'],
        'two_browser_clients': [sys.executable, '-m', 'pytest', 'tests/test_source_browser.py::test_two_browser_clients_show_cross_client_source_change', '-q'],
        'two_role_clients': [sys.executable, '-m', 'pytest', 'tests/test_agents.py::test_two_role_clients_share_actual_local_service', '-q'],
        'interruption_recovery': [sys.executable, '-m', 'pytest', 'tests/test_fresh_process_crash.py::test_process_exit_leaves_incomplete_fresh_run_without_retry', '-q'],
        'review_binding': [sys.executable, '-m', 'pytest', 'tests/test_programs.py::test_review_record_exact_binding', '-q'],
    }
    results = {}
    for name, command in checks.items():
        try:
            result = run(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, timeout=120, check=False)
            output = result.stdout or ''
            if result.returncode != 0:
                status = 'failed'
            elif '-m' in command:
                status = 'skipped' if re.search(r'\b\d+ skipped\b',output) else 'passed' if re.search(r'\b1 passed\b',output) else 'invalid_output'
            else:
                try:
                    payload = json.loads(output.strip().splitlines()[-1])
                    status = 'passed' if payload.get('status') == 'passed' else 'invalid_output'
                except (ValueError, TypeError, AttributeError, IndexError):
                    status = 'invalid_output'
            results[name] = {'status':status,'exit_code':result.returncode,'output':output[-4000:]}
        except (OSError, subprocess.TimeoutExpired) as exc:
            results[name] = {'status':'unavailable','exit_code':None,'output':str(exc)}
    unmet = [name for name, value in results.items() if value['status'] != 'passed']
    return {'status':'incomplete' if unmet else 'passed','checks':results,'unmet':unmet,
            'hosted_provider':'not_exercised','evidence':'synthetic_local_checks'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline',action='store_true',required=True,help='run synthetic local checks only')
    parser.parse_args()
    report=run_offline()
    print(json.dumps(report,sort_keys=True))
    return 0 if report['status']=='passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
