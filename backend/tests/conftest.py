"""Shared test fixtures for the MARKAI backend test suite."""

import os

import pytest

# Override settings before importing the app so it doesn't try to connect
# to real databases or fail on production-only checks.
os.environ["MARKAI_ENV"] = "test"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["POSTGRES_PASSWORD"] = "test-password"
os.environ["MINIO_SECRET_KEY"] = "test-minio-secret"
os.environ.setdefault("AZURE_AD_TENANT_ID", "")
os.environ.setdefault("AZURE_AD_CLIENT_ID", "")
os.environ.setdefault("AZURE_AD_CLIENT_SECRET", "")


@pytest.fixture()
def anyio_backend():
    return "asyncio"
