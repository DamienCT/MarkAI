"""Regression tests for scripts/vps-redeploy.sh (audit N-13 / N-20).

N-20: the sudoers entry point /usr/local/bin/markai-deploy may be a bare
symlink to the script, so the script itself must reject flags and accept at
most one positional hex git SHA.

N-13: the generated Traefik dashboard password must never be echoed to
stdout (CI captures stdout into the public-ish deploy log).

The safe-stop wrapper (main(){...}; main "$@") is load-bearing: Step 1's
git pull rewrites the file mid-run and an unwrapped script resumes at a byte
offset inside the NEW file. These tests fail if the wrapper is removed.

Behavioral tests extract the main() function verbatim and run it with test
argv; validation happens before `cd /var/www/markai`, so on a dev machine a
VALID SHA proceeds past validation and then fails at the cd — which is the
expected marker that validation passed.

The whole module skips unless a *working* bash is found: on Windows,
shutil.which("bash") may return the WSL relay stub even with no distro
installed, where every invocation dies (see _find_bash/_bash_works).
"""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "vps-redeploy.sh"


def _find_bash() -> str | None:
    """Prefer Git Bash on Windows: shutil.which("bash") can return the WSL
    relay stub (C:\\WINDOWS\\system32\\bash.EXE), which exists even when no
    distro is installed and dies with `execvpe(/bin/bash) failed`."""
    git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    if git_bash.is_file():
        return str(git_bash)
    return shutil.which("bash")


BASH = _find_bash()


def _bash_works() -> bool:
    """Probe that BASH actually executes something — PATH presence is not
    enough (see _find_bash). Any exception, nonzero exit, or missing output
    means this host cannot run the behavioral tests."""
    if BASH is None:
        return False
    try:
        result = subprocess.run(
            [BASH, "-c", "echo ok"], capture_output=True, text=True, timeout=15
        )
    except Exception:
        return False
    return result.returncode == 0 and result.stdout.strip() == "ok"


if not _bash_works():
    pytest.skip(
        "no working bash on this host (none on PATH, or only the WSL relay stub)",
        allow_module_level=True,
    )


def _script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


# ── Static invariants ────────────────────────────────────────────────


def test_script_exists():
    assert SCRIPT.is_file()


def test_main_wrapper_intact():
    """The main(){...}; main "$@" wrapper survives (mid-run self-rewrite guard)."""
    text = _script_text()
    assert re.search(r"^main\(\) \{", text, re.M), "main() wrapper removed"
    last_code_line = [
        line for line in text.splitlines() if line.strip() and not line.strip().startswith("#")
    ][-1]
    assert 'main "$@"' in last_code_line, "main is no longer invoked on the last line"


def test_sha_regex_present():
    """Argv validation pins the first arg to a hex git SHA (N-20)."""
    assert "^[0-9a-f]{7,40}$" in _script_text()


def test_traefik_password_never_echoed():
    """No echo/log line interpolates the generated Traefik password (N-13)."""
    for line in _script_text().splitlines():
        if "TRAEFIK_PASS" not in line:
            continue
        stripped = line.strip()
        if stripped.startswith("echo") and "$TRAEFIK_PASS" not in stripped and "${TRAEFIK_PASS}" not in stripped:
            continue
        # Allowed sites: generation, htpasswd hashing, and the redirected
        # write into the root-only credentials file.
        assert (
            stripped.startswith("TRAEFIK_PASS=")
            or "htpasswd" in stripped
            or "openssl passwd" in stripped
            or 'echo "password: ${TRAEFIK_PASS}"' == stripped
        ), f"TRAEFIK_PASS leaks outside the credential file write: {line!r}"
    # The credential-file mechanism itself must still be there.
    assert "TRAEFIK_CRED_FILE" in _script_text()
    assert "umask 077" in _script_text()


def test_no_flag_style_toggles_remain():
    """Destructive toggles are env-only; no --force-wipe/--skip-backup parsing."""
    text = _script_text()
    assert "--force-wipe)" not in text
    assert "--skip-backup)" not in text
    assert "--expected-sha=" not in text


# ── Behavioral argv-contract tests (need bash) ───────────────────────


def _run_main(*args: str) -> subprocess.CompletedProcess:
    """Extract main() verbatim and invoke it with the given argv."""
    text = _script_text()
    # main() closes right before the entry-point section; a non-greedy regex
    # would stop at the first nested function's closing brace instead.
    head = text.split("# ── Entry point")[0]
    start = head.find("main() {")
    assert start != -1, "could not find main() definition"
    body = head[start:].rstrip()
    assert body.endswith("}"), "main() body does not end with its closing brace"
    # Safety: cd is the first post-validation command in main(); overriding it
    # to fail (with set -e) guarantees the harness can never run the real
    # git/docker steps, on any machine.
    harness = (
        "set -euo pipefail\n"
        'cd() { echo "CD-BLOCKED (validation passed)"; return 1; }\n'
        + body
        + '\nmain "$@"\n'
    )
    # Written to a file rather than `bash -c`: Windows argv quoting mangles
    # the multi-KB script text when passed as a single -c argument.
    with tempfile.TemporaryDirectory() as tmp:
        harness_file = Path(tmp) / "main_harness.sh"
        harness_file.write_text(harness, encoding="utf-8", newline="\n")
        return subprocess.run(
            [BASH, str(harness_file), *args],
            capture_output=True,
            text=True,
            timeout=30,
        )


# No per-test bash guard needed: the module-level probe above skips the whole
# module unless BASH is a working interpreter.


@pytest.mark.parametrize(
    "arg", ["--force-wipe", "--skip-backup", "-x", "--expected-sha=abc1234"]
)
def test_flags_rejected(arg):
    result = _run_main(arg)
    assert result.returncode == 1
    assert "flags are not accepted" in result.stdout


@pytest.mark.parametrize("arg", ["HELLO", "abc123", "g" * 10, "abc1234; rm -rf /", "A" * 41])
def test_non_sha_rejected(arg):
    result = _run_main(arg)
    assert result.returncode == 1
    assert "must be a lowercase hex git SHA" in result.stdout


def test_multiple_args_rejected():
    result = _run_main("abc1234", "def5678")
    assert result.returncode == 1
    assert "at most one argument" in result.stdout


def test_valid_sha_passes_validation():
    """A hex SHA clears validation: none of the rejection messages appear.

    On a dev machine the run then fails at `cd /var/www/markai`, which is
    fine — the assertion is only that validation itself accepted the SHA.
    """
    result = _run_main("d761a56" + "0" * 33)
    combined = result.stdout + result.stderr
    assert "flags are not accepted" not in combined
    assert "must be a lowercase hex git SHA" not in combined
    assert "at most one argument" not in combined
