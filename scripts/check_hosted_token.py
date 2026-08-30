"""Ask whether a real access token would still be accepted after R-6.

WHY THIS EXISTS. On 2026-08-30 the hosted server stopped accepting a bearer
token whose audience does not name it (`src/euroleague/mcp/http_app.py`,
`acceptable_claims`). Every test behind that change uses a constructed claim
set whose shape was taken from documentation, not from an observed token. If the
deployed Auth0 configuration disagrees - a different audience, or no
`read:warehouse` in the token - the merge that deploys the change is the moment
the owner loses access to their own server.

This script answers that question **without deploying anything**. It runs the
new rule against a real token on the owner's machine. A failure here is a
configuration finding; a failure after a merge is an outage.

HOW THE TOKEN REACHES IT, and this is not negotiable. Set it as an environment
variable in your own shell, for that shell only:

    $env:EL_MCP_TOKEN = "<paste the token>"      # PowerShell
    export EL_MCP_TOKEN='<paste the token>'      # bash

It is deliberately NOT a command-line argument: arguments land in shell history
and in the process list, where other programs can read them. It must never be
written to a file, committed, or pasted into a chat. `ROADMAP.md` P2-1 states
the same rule for the load test.

WHAT THIS PRINTS. The verdict, and the three claim values the decision turns on:
audience, issuer and scopes. It never prints the token, and it never prints
`email`, `name` or any other personal claim that Auth0 may include.

WHAT THIS DOES NOT ESTABLISH. That the deployed server behaves this way - it
does not yet, because the change is unmerged. It establishes only that a real
token satisfies, or does not satisfy, the rule that is about to be deployed.
"""

from __future__ import annotations

import os
import sys

import requests

from euroleague.mcp.http_app import DEFAULT_REQUIRED_SCOPE, acceptable_claims, scopes_from_claims

TOKEN_VARIABLE = "EL_MCP_TOKEN"
DEFAULT_SERVER = "https://euroleague-analytics-mcp.fly.dev"


def discovery(server: str) -> tuple[str, str]:
    """Read the issuer and resource the server itself publishes.

    Taken from the server rather than typed here so the check cannot pass
    against values that only exist in this file.
    """
    url = f"{server.rstrip('/')}/.well-known/oauth-protected-resource/mcp"
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    document = response.json()
    resource = str(document["resource"])
    issuers = document.get("authorization_servers") or []
    if not issuers:
        raise SystemExit(f"{url} lists no authorization_servers; cannot check the issuer.")
    return str(issuers[0]), resource


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    server = arguments[0] if arguments else DEFAULT_SERVER

    token = os.environ.get(TOKEN_VARIABLE, "").strip()
    if not token:
        print(
            f"Set {TOKEN_VARIABLE} in this shell first. It is read from the "
            f"environment and never from an argument, because an argument is "
            f"visible in shell history and in the process list.",
            file=sys.stderr,
        )
        return 2

    issuer, resource = discovery(server)
    print(f"server        {server}")
    print(f"issuer        {issuer}")
    print(f"resource      {resource}")

    if token.count(".") != 2:
        print(
            "\nThis token is not a JWT, so its claims cannot be read locally. "
            "That is itself the finding: the audience check needs claims, and an "
            "opaque token only carries them through the introspection endpoint. "
            "Request the token with an audience so Auth0 issues a JWT.",
            file=sys.stderr,
        )
        return 1

    import jwt

    signing_key = jwt.PyJWKClient(
        f"{issuer.rstrip('/')}/.well-known/jwks.json"
    ).get_signing_key_from_jwt(token)
    # verify_aud is False here for the same reason it is False in the server:
    # the audience is compared afterwards, by the function actually being tested.
    claims = jwt.decode(token, signing_key.key, algorithms=["RS256"], options={"verify_aud": False})

    required = os.environ.get("MCP_REQUIRED_SCOPE", DEFAULT_REQUIRED_SCOPE).strip() or None
    audience = claims.get("aud")
    print(f"token aud     {audience!r}")
    print(f"token iss     {claims.get('iss')!r}")
    print(f"token scopes  {scopes_from_claims(claims)}")
    print(f"scope needed  {required!r}")

    refusal = acceptable_claims(
        claims, resource_url=resource, issuer_url=issuer, required_scope=required
    )
    if refusal is None:
        print("\nVERDICT: this token is accepted by the new rule. R-6 is safe to merge.")
        return 0

    print(
        f"\nVERDICT: this token would be REFUSED - {refusal}."
        f"\nDo not merge R-6 until this is explained. Compare the values above: the "
        f"token's audience must equal the resource the server publishes, and the "
        f"scope must be present or MCP_REQUIRED_SCOPE must be set empty.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
