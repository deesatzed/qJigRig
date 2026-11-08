"""Require the browser portion of the synthetic fresh-workflow acceptance check."""
import os

import pytest

from test_fresh_service import test_configured_service_runs_fresh_pipeline_and_preserves_deferral as _run_fresh_journey


def test_complete_synthetic_fresh_browser_journey(tmp_path):
    if not os.environ.get('QJIG_CHROMIUM_PATH'):
        pytest.skip('QJIG_CHROMIUM_PATH is required for the fresh browser journey')
    pytest.importorskip('playwright.sync_api')
    _run_fresh_journey(tmp_path)
