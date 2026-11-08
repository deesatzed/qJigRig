#!/usr/bin/env python3
"""Run the isolated, synthetic installed-package smoke test.

This is one clean-install check, not a claim of final product acceptance.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    env = os.environ.copy()
    env['QJIG_VERIFY_CLEAN_INSTALL'] = '1'
    env.pop('PYTHONPATH', None)
    env.pop('PYTHONHOME', None)
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', '-q', '-s', str(ROOT / 'tests/test_clean_install.py')],
        cwd=ROOT, env=env, check=False,
    )
    if result.returncode:
        return result.returncode
    if not env.get('QJIG_CHROMIUM_PATH'):
        print('INCOMPLETE: QJIG_CHROMIUM_PATH is required for isolated browser and full-suite verification')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
