"""Shared security primitives for GitHub REST transports."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


GITHUB_API_ORIGIN = "https://api.github.com"
MAX_GITHUB_JSON_BYTES = 1024 * 1024


def validate_github_api_base_url(value: str) -> str:
    """Require the exact GitHub.com API origin before sending credentials."""
    if not isinstance(value, str) or value != value.strip() or not value:
        raise ValueError(
            "GitHub API base URL must be exactly https://api.github.com."
        )

    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "api.github.com"
        or parsed.path not in ("", "/")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "GitHub API base URL must be exactly https://api.github.com."
        )
    return GITHUB_API_ORIGIN


def read_bounded_response(
    response: Any,
    *,
    limit: int = MAX_GITHUB_JSON_BYTES,
) -> bytes:
    """Read an HTTP response body without allowing unbounded memory growth."""
    if not isinstance(limit, int) or limit <= 0:
        raise ValueError("GitHub response size limit must be positive.")

    raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(
            f"GitHub JSON response exceeds the {limit}-byte download limit."
        )
    return raw
