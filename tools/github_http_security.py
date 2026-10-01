"""Shared security primitives for GitHub REST transports."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse


GITHUB_API_ORIGIN = "https://api.github.com"
GITHUB_API_VERSION = "2026-03-10"
GITHUB_API_VERSION_HEADER = "X-GitHub-Api-Version"
MAX_GITHUB_JSON_BYTES = 1024 * 1024


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"GitHub JSON contains unsupported constant {value!r}.")


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key!r}.")
        result[key] = value
    return result


def parse_github_json(
    raw: bytes,
    *,
    label: str = "GitHub JSON response",
) -> Any:
    """Parse one already-bounded GitHub REST JSON response with strict semantics."""
    if not isinstance(raw, bytes):
        raise ValueError("GitHub JSON response body must be bytes.")
    if not raw:
        raise ValueError(f"{label} must not be empty.")
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_json_constant,
        )
    except ValueError as exc:
        raise ValueError(f"{label} is invalid: {exc}") from exc


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


def github_api_headers() -> dict[str, str]:
    """Return the mandatory baseline headers for credential-bearing GitHub REST calls."""
    return {
        "Accept": "application/vnd.github+json",
        GITHUB_API_VERSION_HEADER: GITHUB_API_VERSION,
    }


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
