"""Database settings, and the one mistake that only fails in CI.

Supabase free projects have no dedicated IPv4 address. GitHub Actions runners
are IPv4-only. A connection string pointed at the direct database host
therefore works on the owner's machine and fails only in CI, which is the worst
failure shape this project has. The check lives here so it is caught by a test
rather than by a red workflow run.
"""

from __future__ import annotations

import pytest

from euroleague.config import DatabaseSettings, DirectHostError

POOLER_URL = (
    "postgresql://postgres.pctiewdpstnwcutrvegu:secret"
    "@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"
)
DIRECT_URL = "postgresql://postgres:secret@db.pctiewdpstnwcutrvegu.supabase.co:5432/postgres"


def test_a_pooler_url_is_accepted() -> None:
    settings = DatabaseSettings.from_url(POOLER_URL)
    assert settings.host == "aws-0-eu-central-1.pooler.supabase.com"
    assert settings.port == 6543


def test_the_direct_supabase_host_is_rejected() -> None:
    with pytest.raises(DirectHostError):
        DatabaseSettings.from_url(DIRECT_URL)


def test_the_rejection_explains_what_to_do_instead() -> None:
    """Error messages must suggest a concrete next step."""
    with pytest.raises(DirectHostError) as raised:
        DatabaseSettings.from_url(DIRECT_URL)
    message = str(raised.value)
    assert "pooler" in message.lower()
    assert "IPv4" in message


def test_a_non_postgres_url_is_rejected() -> None:
    with pytest.raises(ValueError):
        DatabaseSettings.from_url("https://example.com/not-a-database")


def test_an_empty_url_is_rejected_with_a_pointer_to_the_env_file() -> None:
    with pytest.raises(ValueError) as raised:
        DatabaseSettings.from_url("")
    assert ".env" in str(raised.value)


def test_the_password_is_not_exposed_by_repr() -> None:
    """A settings object gets printed in tracebacks and logs. The password must not
    travel with it, especially in a public repository's CI output."""
    settings = DatabaseSettings.from_url(POOLER_URL)
    rendered = repr(settings)
    assert "secret" not in rendered
    assert "aws-0-eu-central-1.pooler.supabase.com" in rendered


def test_the_url_is_still_recoverable_for_actually_connecting() -> None:
    settings = DatabaseSettings.from_url(POOLER_URL)
    assert settings.url() == POOLER_URL


def test_from_env_reads_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", POOLER_URL)
    settings = DatabaseSettings.from_env()
    assert settings.host == "aws-0-eu-central-1.pooler.supabase.com"


def test_from_env_without_the_variable_names_the_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError) as raised:
        DatabaseSettings.from_env()
    assert "DATABASE_URL" in str(raised.value)
