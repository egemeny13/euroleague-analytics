"""Optional OpenAI directory submission routes, separate from the MCP core."""

from __future__ import annotations

from collections.abc import Mapping

from starlette.responses import PlainTextResponse
from starlette.routing import Route

OPENAI_CHALLENGE_PATH = "/.well-known/openai-apps-challenge"


def openai_submission_routes(environment: Mapping[str, str]) -> list[Route]:
    """Return the domain challenge route only while a non-blank token is configured."""
    token = environment.get("OPENAI_APPS_CHALLENGE_TOKEN", "")
    if not token.strip():
        return []

    async def domain_challenge(request: object) -> PlainTextResponse:
        return PlainTextResponse(token)

    return [Route(OPENAI_CHALLENGE_PATH, domain_challenge, methods=["GET"])]
