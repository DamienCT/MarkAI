"""Regression for N-04: production startup must refuse to run without the
aux-service secrets (MEDIA_PROXY_TOKEN, BROWSER_WORKER_API_KEY,
NOTIFICATIONS_AUTH_TOKEN) via the _REQUIRED_PROD guard in app/config.py.

app.config raises at import time, so each case runs in a subprocess with a
hand-built environment — the shared ``settings`` singleton of this test
process is never touched, and the repo's real .env can't leak in (cwd is a
temp dir, so the module's relative env_file paths resolve to nothing).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Everything a production import needs to pass the earlier guards.
_FULL_PROD_ENV = {
    "MARKAI_ENV": "production",
    "SECRET_KEY": "unit-test-secret-key-not-a-default",
    "POSTGRES_PASSWORD": "unit-test-strong-password",
    "MINIO_SECRET_KEY": "unit-test-strong-minio-key",
    "AZURE_AD_TENANT_ID": "tenant",
    "AZURE_AD_CLIENT_ID": "client",
    "AZURE_AD_CLIENT_SECRET": "secret",
    "N8N_WEBHOOK_SECRET": "webhook-secret",
    "FRONTEND_URL": "https://markai.example.com",
    "MEDIA_PROXY_TOKEN": "media-proxy-token",
    "BROWSER_WORKER_API_KEY": "browser-worker-key",
    "NOTIFICATIONS_AUTH_TOKEN": "notifications-token",
}

# Process plumbing the interpreter needs on Windows (APPDATA locates the
# user site-packages where the deps are installed).
_PASSTHROUGH = (
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "PATH",
    "PATHEXT",
    "COMSPEC",
    "TEMP",
    "TMP",
    "APPDATA",
    "LOCALAPPDATA",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
)


def _import_config(tmp_path: Path, *, drop: tuple[str, ...] = (), overrides: dict | None = None):
    env = {k: v for k, v in _FULL_PROD_ENV.items() if k not in drop}
    env.update(overrides or {})
    for key in _PASSTHROUGH:
        if key in os.environ:
            env[key] = os.environ[key]
    env["PYTHONPATH"] = str(BACKEND_DIR)
    return subprocess.run(
        [sys.executable, "-c", "import app.config"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_production_starts_with_all_required_settings(tmp_path):
    result = _import_config(tmp_path)
    assert result.returncode == 0, result.stderr


def test_production_refuses_without_aux_service_secrets(tmp_path):
    missing = ("MEDIA_PROXY_TOKEN", "BROWSER_WORKER_API_KEY", "NOTIFICATIONS_AUTH_TOKEN")
    result = _import_config(tmp_path, drop=missing)
    assert result.returncode != 0
    for name in missing:
        assert name in result.stderr, f"{name} not reported in: {result.stderr}"


def test_production_refuses_without_each_single_secret(tmp_path):
    for name in ("MEDIA_PROXY_TOKEN", "BROWSER_WORKER_API_KEY", "NOTIFICATIONS_AUTH_TOKEN"):
        result = _import_config(tmp_path, drop=(name,))
        assert result.returncode != 0, f"started without {name}"
        assert name in result.stderr


def test_development_has_safe_defaults(tmp_path):
    # Local dev must keep working with none of the new vars set.
    result = _import_config(
        tmp_path,
        drop=tuple(_FULL_PROD_ENV),
        overrides={"MARKAI_ENV": "development"},
    )
    assert result.returncode == 0, result.stderr
