"""Tests for LLM output parsing utilities."""

import sys
import os

# Add the agents directory to the path so shared.llm can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.llm import parse_llm_json, strip_markdown_fences


class TestStripMarkdownFences:
    def test_no_fences(self):
        assert strip_markdown_fences('{"key": "value"}') == '{"key": "value"}'

    def test_json_fences(self):
        text = '```json\n{"key": "value"}\n```'
        assert strip_markdown_fences(text) == '{"key": "value"}'

    def test_plain_fences(self):
        text = '```\n{"key": "value"}\n```'
        assert strip_markdown_fences(text) == '{"key": "value"}'

    def test_fences_with_extra_whitespace(self):
        text = '  ```json\n{"key": "value"}\n```  '
        assert strip_markdown_fences(text) == '{"key": "value"}'


class TestParseLlmJson:
    def test_valid_json(self):
        result = parse_llm_json('{"name": "test", "count": 42}')
        assert result == {"name": "test", "count": 42}

    def test_valid_json_list(self):
        result = parse_llm_json("[1, 2, 3]")
        assert result == [1, 2, 3]

    def test_json_with_markdown_fences(self):
        text = '```json\n{"name": "test"}\n```'
        result = parse_llm_json(text)
        assert result == {"name": "test"}

    def test_invalid_json_returns_fallback(self):
        result = parse_llm_json("this is not json", fallback={"default": True})
        assert result == {"default": True}

    def test_invalid_json_returns_none_by_default(self):
        result = parse_llm_json("not json")
        assert result is None

    def test_empty_string_returns_fallback(self):
        result = parse_llm_json("", fallback=[])
        assert result == []

    def test_nested_json(self):
        text = '{"outer": {"inner": [1, 2, 3]}}'
        result = parse_llm_json(text)
        assert result == {"outer": {"inner": [1, 2, 3]}}

    def test_json_with_leading_text_fails_gracefully(self):
        # LLM sometimes adds preamble before JSON
        text = 'Here is the result:\n{"key": "value"}'
        result = parse_llm_json(text, fallback="failed")
        # This should fail because leading text makes it invalid JSON
        assert result == "failed"
