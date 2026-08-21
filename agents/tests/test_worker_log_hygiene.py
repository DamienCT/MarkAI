"""Worker logging never echoes request URLs (HTTPX-QUIET, mirror of backend).

httpx/httpcore log every request line at INFO — full URL, query string
included — which is how credential-bearing URLs reach stdout (N-01). The
worker's logging setup pins both loggers to WARNING, exactly as backend
main.py does.
"""

import logging

import worker


class TestHttpLoggersAreQuiet:
    def test_setup_pins_httpx_and_httpcore_to_warning(self):
        # Re-run the setup (import already ran it once) and assert the state.
        worker._setup_json_logging()
        assert logging.getLogger("httpx").level == logging.WARNING
        assert logging.getLogger("httpcore").level == logging.WARNING
        assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)
        assert not logging.getLogger("httpcore").isEnabledFor(logging.INFO)
