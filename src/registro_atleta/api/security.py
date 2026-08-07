from __future__ import annotations

import os


def configured_api_token() -> str | None:
    token = os.environ.get("REGISTRO_ATLETA_API_TOKEN", "").strip()
    return token or None


def token_is_allowed(expected_token: str | None, provided_token: str | None) -> bool:
    if expected_token is None:
        return True
    return provided_token == expected_token
