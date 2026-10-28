"""Thin wrapper around the Claude API for structured JSON calls.

Claude is optional. When no credentials are configured, or a call fails or is refused,
callers get None and fall back to the deterministic path, so the app keeps working offline.
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache

import anthropic

from app.config import get_settings

log = logging.getLogger(__name__)


@lru_cache
def _client() -> anthropic.Anthropic | None:
    settings = get_settings()
    if not settings.use_llm:
        return None
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return None
    return anthropic.Anthropic()


def llm_available() -> bool:
    return _client() is not None


def structured_call(*, model: str, system: str, prompt: str, schema: dict, max_tokens: int = 4000, effort: str = "low") -> dict | None:
    """One request whose reply is constrained to `schema`. Returns the parsed object or None."""
    client = _client()
    if client is None:
        return None
    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        )
    except anthropic.RateLimitError as e:
        log.warning("Claude rate limited: %s", e)
        return None
    except anthropic.APIStatusError as e:
        log.warning("Claude API error %s: %s", e.status_code, e)
        return None
    except anthropic.APIConnectionError as e:
        log.warning("Claude connection error: %s", e)
        return None

    if response.stop_reason in ("refusal", "max_tokens"):
        log.warning("Claude stopped with %s; using deterministic fallback", response.stop_reason)
        return None
    text = "".join(block.text for block in response.content if block.type == "text")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.warning("Claude returned non-JSON output; using deterministic fallback")
        return None
