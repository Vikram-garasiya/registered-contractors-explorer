"""Shared fixtures.

APP_BASE_URL is the root of the OutSystems environment, e.g.
  https://<env>.outsystemscloud.com
The UI module (RegisteredContractors) is served at {APP_BASE_URL}/RegisteredContractors. Tests that need the
deployed app are skipped when APP_BASE_URL is not set, so the suite runs anywhere.
"""
import os

import pytest

UI_MODULE = "RegisteredContractors"


@pytest.fixture(scope="session")
def base_url() -> str:
    url = os.environ.get("APP_BASE_URL", "").rstrip("/")
    if not url:
        pytest.skip("APP_BASE_URL not set; skipping tests against the deployed app")
    return url


@pytest.fixture(scope="session")
def ui_url(base_url) -> str:
    return f"{base_url}/{UI_MODULE}"
