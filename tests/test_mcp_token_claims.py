"""The rule deciding whether a token's claims authorise this server.

WHY THIS EXISTS. Read in `src/euroleague/mcp/http_app.py` on 2026-08-29 and
recorded in `docs/AUTH0_CONFIGURATION.md`: the server validated a bearer token's
signature and then accepted it, passing `verify_aud=False` and enforcing no
scope. **Any valid token the tenant issued, for any purpose, opened the
warehouse.** Client registration on that tenant is open by design, so "a token
from this tenant" was not a meaningful restriction.

An audience claim is what makes a token *this server's* token. `aud` names the
API the token was minted for; a token issued for some other API in the same
tenant carries a different one, and that is the whole check.

WHAT THIS DOES NOT PROVE. That the bearer is entitled to anything. These claims
say the token was issued by the expected authority, for this resource, carrying
the expected permission. Who may obtain such a token is decided in Auth0 - by
the post-login Action today - and nothing here can see that decision.
"""

from __future__ import annotations

import pytest

from euroleague.mcp.http_app import acceptable_claims, scopes_from_claims

RESOURCE = "https://euroleague-analytics-mcp.fly.dev/mcp"
ISSUER = "https://dev-ew0k6i4pmarjvgkn.us.auth0.com"


def claims(**overrides: object) -> dict[str, object]:
    """A claim set that passes, so each test changes exactly one thing."""
    base: dict[str, object] = {
        "aud": RESOURCE,
        "iss": ISSUER,
        "sub": "auth0|abc123",
        "scope": "read:warehouse",
    }
    base.update(overrides)
    return base


def test_a_token_minted_for_this_resource_is_accepted() -> None:
    assert (
        acceptable_claims(
            claims(), resource_url=RESOURCE, issuer_url=ISSUER, required_scope="read:warehouse"
        )
        is None
    )


def test_a_token_for_a_different_api_in_the_same_tenant_is_refused() -> None:
    """The exact hole this closes. Same issuer, same signature, different audience."""
    reason = acceptable_claims(
        claims(aud="https://some-other-api.example.com"),
        resource_url=RESOURCE,
        issuer_url=ISSUER,
        required_scope="read:warehouse",
    )
    assert reason is not None
    assert "audience" in reason


def test_a_token_with_no_audience_at_all_is_refused() -> None:
    """An OIDC token issued for signing in carries no API audience.

    This is why the `/userinfo` verification path had to go rather than be
    tightened: a userinfo response proves the bearer exists in the tenant and
    says nothing about which API the token was for.
    """
    without_audience = claims()
    del without_audience["aud"]
    reason = acceptable_claims(
        without_audience,
        resource_url=RESOURCE,
        issuer_url=ISSUER,
        required_scope="read:warehouse",
    )
    assert reason is not None
    assert "audience" in reason


def test_an_audience_list_is_accepted_when_it_contains_this_resource() -> None:
    """`aud` is a string or an array; Auth0 sends an array when userinfo is also
    requested, with the API identifier alongside the tenant's userinfo endpoint."""
    assert (
        acceptable_claims(
            claims(aud=[RESOURCE, f"{ISSUER}/userinfo"]),
            resource_url=RESOURCE,
            issuer_url=ISSUER,
            required_scope="read:warehouse",
        )
        is None
    )


@pytest.mark.parametrize(
    ("configured", "in_token"),
    [(RESOURCE, RESOURCE + "/"), (RESOURCE + "/", RESOURCE)],
)
def test_a_trailing_slash_on_the_audience_does_not_decide_who_gets_in(
    configured: str, in_token: str
) -> None:
    """A lockout caused by punctuation is still a lockout."""
    assert (
        acceptable_claims(
            claims(aud=in_token),
            resource_url=configured,
            issuer_url=ISSUER,
            required_scope=None,
        )
        is None
    )


def test_a_trailing_slash_on_the_issuer_does_not_decide_who_gets_in() -> None:
    """Auth0 publishes `iss` with a trailing slash while the configured issuer is
    conventionally written without one. Both spellings name the same tenant."""
    assert (
        acceptable_claims(
            claims(iss=ISSUER + "/"),
            resource_url=RESOURCE,
            issuer_url=ISSUER,
            required_scope=None,
        )
        is None
    )


def test_normalising_the_trailing_slash_does_not_admit_a_different_host() -> None:
    """The normalisation must not turn into a prefix match. This is the mistake
    the CodeQL rule `py/incomplete-url-substring-sanitization` describes, and it
    would be a real one here rather than the false positive found in a test."""
    reason = acceptable_claims(
        claims(aud=RESOURCE + ".attacker.example.com"),
        resource_url=RESOURCE,
        issuer_url=ISSUER,
        required_scope=None,
    )
    assert reason is not None
    assert "audience" in reason


def test_a_token_from_another_issuer_is_refused() -> None:
    reason = acceptable_claims(
        claims(iss="https://attacker.example.com"),
        resource_url=RESOURCE,
        issuer_url=ISSUER,
        required_scope=None,
    )
    assert reason is not None
    assert "issuer" in reason


def test_a_token_without_the_required_scope_is_refused() -> None:
    reason = acceptable_claims(
        claims(scope="openid profile email"),
        resource_url=RESOURCE,
        issuer_url=ISSUER,
        required_scope="read:warehouse",
    )
    assert reason is not None
    assert "read:warehouse" in reason


def test_no_required_scope_configured_means_the_scope_is_not_checked() -> None:
    """The audience check is what closes the hole. The scope is defence in depth,
    and an operator who has not confirmed their tokens carry one can turn it off
    without also turning off the audience check."""
    assert (
        acceptable_claims(
            claims(scope="openid"), resource_url=RESOURCE, issuer_url=ISSUER, required_scope=None
        )
        is None
    )


def test_the_reason_never_contains_the_token_or_the_subject() -> None:
    """The reason is written to the server log. A log line that carries the
    credential it rejected turns a rejection into a second disclosure."""
    reason = acceptable_claims(
        claims(aud="https://elsewhere.example.com", sub="auth0|secret-person"),
        resource_url=RESOURCE,
        issuer_url=ISSUER,
        required_scope="read:warehouse",
    )
    assert reason is not None
    assert "secret-person" not in reason


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"scope": "read:warehouse write:x"}, ["read:warehouse", "write:x"]),
        ({"scopes": ["read:warehouse"]}, ["read:warehouse"]),
        ({"scope": ""}, []),
        ({}, []),
        ({"scope": None}, []),
    ],
)
def test_scopes_are_read_from_either_spelling(raw: dict[str, object], expected: list[str]) -> None:
    """Introspection responses say `scope`, some identity providers say `scopes`,
    and one is a space-separated string while the other is a list."""
    assert scopes_from_claims(raw) == expected
