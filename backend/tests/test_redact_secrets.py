"""Regression tests for app.utils.redact (audit N-01 — tokens leaking into logs)."""

from app.utils.redact import redact, redact_url


class TestRedactUrl:
    def test_strips_access_token_keeps_other_params(self):
        url = (
            "https://graph.facebook.com/v25.0/123/insights"
            "?metric=reach&access_token=EAABsbCS1234SECRET"
        )
        out = redact_url(url)
        assert "EAABsbCS1234SECRET" not in out
        assert "access_token=***" in out
        assert "metric=reach" in out

    def test_strips_code_sig_key_params(self):
        url = "https://x.example/cb?code=abc123&sig=deadbeef&key=sk-999&state=ok"
        out = redact_url(url)
        assert "abc123" not in out
        assert "deadbeef" not in out
        assert "sk-999" not in out
        assert "code=***" in out and "sig=***" in out and "key=***" in out
        assert "state=ok" in out  # non-sensitive params survive

    def test_url_without_query_string_unchanged(self):
        url = "https://api.linkedin.com/v2/socialActions/urn:li:share:1/statistics"
        assert redact_url(url) == url

    def test_similar_but_safe_param_names_untouched(self):
        url = "https://x.example/?design=flat&monkey=1&author=jane&zipcode=75001"
        assert redact_url(url) == url


class TestRedact:
    def test_redacts_httpx_status_error_style_message(self):
        # Shape of str(httpx.HTTPStatusError) — URL in single quotes.
        msg = (
            "Client error '401 Unauthorized' for url "
            "'https://graph.facebook.com/v25.0/1/insights"
            "?metric=reach&access_token=EAABtokLIVE'\n"
            "For more information check: https://developer.mozilla.org/x/401"
        )
        out = redact(msg)
        assert "EAABtokLIVE" not in out
        assert "access_token=***" in out
        assert "metric=reach" in out

    def test_redacts_bare_name_value_pairs(self):
        out = redact("retrying access_token=EAAB123 after failure")
        assert "EAAB123" not in out
        assert "access_token=***" in out

    def test_leaves_status_code_alone(self):
        assert redact("request failed status_code=401") == (
            "request failed status_code=401"
        )

    def test_redacts_dict_style_reprs(self):
        out = redact("{'access_token': 'EAABxyz', 'fields': 'id,name'}")
        assert "EAABxyz" not in out
        assert "'fields': 'id,name'" in out

    def test_redacts_bearer_header_values(self):
        out = redact("Authorization: Bearer EAABlongtokenvalue123")
        assert "EAABlongtokenvalue123" not in out

    def test_accepts_exception_objects(self):
        exc = ValueError("bad url https://g.example/?token=supersecret&a=1")
        out = redact(exc)
        assert "supersecret" not in out
        assert "a=1" in out
