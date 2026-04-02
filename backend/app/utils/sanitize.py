"""Input sanitization for LLM prompts to prevent prompt injection.

Mirrors agents/shared/sanitize.py — kept in sync for the backend package.
"""

import re
import unicodedata

# Zero-width characters used to smuggle hidden content
_ZERO_WIDTH_CHARS = re.compile("[\u200b\u200c\u200d\ufeff\u2060]")

# Patterns that could be used for prompt injection
_INJECTION_PATTERNS = [
    r"(?i)ignore\s+(all\s+)?previous\s+instructions",
    r"(?i)system\s*:\s*",
    r"(?i)you\s+are\s+now\s+",
    r"(?i)forget\s+(all\s+)?previous",
    r"(?i)disregard\s+(all\s+)?",
    r"(?i)new\s+instructions?\s*:",
    r"(?i)\[INST\]",
    r"(?i)<\|im_start\|>",
    r"(?i)<<SYS>>",
    r"(?i)<\|im_end\|>",
    r"(?i)\[/INST\]",
    r"(?i)</?system>",
    r"(?i)### (Human|Assistant|System):",
    r"(?i)<\|(user|assistant|system)\|>",
    r"(?i)IMPORTANT\s*SYSTEM\s*UPDATE",
]

_COMPILED = [re.compile(p) for p in _INJECTION_PATTERNS]


def sanitize_for_prompt(text: str, max_length: int = 10000) -> str:
    """Sanitize user-provided text before including in an LLM prompt.

    - Applies Unicode NFKC normalization
    - Strips zero-width characters
    - Truncates to max_length
    - Strips known injection patterns
    - Escapes delimiter-like sequences
    """
    if not text:
        return ""

    # Normalize Unicode to catch homoglyph/compatibility tricks
    text = unicodedata.normalize("NFKC", text)

    # Strip zero-width characters that can hide injections
    text = _ZERO_WIDTH_CHARS.sub("", text)

    text = text[:max_length]

    for pattern in _COMPILED:
        text = pattern.sub("[FILTERED]", text)

    return text


def sanitize_json_for_prompt(data: dict | list | str, max_length: int = 10000) -> str:
    """Sanitize and serialize data for inclusion in a prompt."""
    import json

    text = json.dumps(data, default=str) if not isinstance(data, str) else data
    return sanitize_for_prompt(text, max_length)
