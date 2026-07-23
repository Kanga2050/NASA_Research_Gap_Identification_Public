"""Per-user credentials for the third-party APIs pipeline functions call.

A pipeline function declares which secrets it needs in its registry entry
(``Function.secrets``); every queueing surface -- the dashboard form, the Studio,
the REST API and MCP -- resolves them here and attaches them as keyword
arguments, exactly the way storage roots are attached. The backend function
itself stays Django-free: it just receives an ``api_key``.

A user who has not set a key simply gets nothing attached, and the backend falls
back to its environment-variable default (or to anonymous access).
"""

from __future__ import annotations

from .models import ExternalApiSettings

# secret name -> (ExternalApiSettings field, backend keyword argument)
SECRETS = {
    "openalex": ("openalex_api_key", "api_key"),
}


def get_secret(user, name: str) -> str:
    """One user's stored key for a named secret, or "" if they have not set one."""
    field, _ = SECRETS[name]
    row = ExternalApiSettings.objects.filter(user=user).first()
    return getattr(row, field, "") if row is not None else ""


def secret_kwargs(user, fn) -> dict[str, str]:
    """The keyword arguments a function's declared secrets contribute, for the
    given user. Blank keys are omitted so the backend default still applies."""
    resolved = {}
    for name in fn.secrets:
        value = get_secret(user, name)
        if value:
            resolved[SECRETS[name][1]] = value
    return resolved
