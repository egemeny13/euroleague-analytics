"""Database settings, and the one mistake that only fails in CI.

Supabase free projects have no dedicated IPv4 address. GitHub Actions runners
are IPv4-only. A connection string pointed at the direct database host
therefore works on the owner's machine and fails only in CI, which is the worst
failure shape this project has. The check lives here so it is caught by a test
rather than by a red workflow run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from euroleague.config import (
    DatabaseSettings,
    DirectHostError,
    StorageSettings,
    TransactionPoolerError,
    load_env_file,
)

# Session mode: the pooler host on port 5432. The one this project uses.
POOLER_URL = (
    "postgresql://postgres.pctiewdpstnwcutrvegu:secret"
    "@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"
)
# Transaction mode: same host, port 6543. No prepared statements.
TRANSACTION_POOLER_URL = (
    "postgresql://postgres.pctiewdpstnwcutrvegu:secret"
    "@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"
)
DIRECT_URL = "postgresql://postgres:secret@db.pctiewdpstnwcutrvegu.supabase.co:5432/postgres"


def test_the_session_pooler_url_is_accepted() -> None:
    settings = DatabaseSettings.from_url(POOLER_URL)
    assert settings.host == "aws-0-eu-central-1.pooler.supabase.com"
    assert settings.port == 5432


def test_the_transaction_pooler_is_rejected() -> None:
    """Port 6543 has no prepared statements, and psycopg prepares them on its own."""
    with pytest.raises(TransactionPoolerError):
        DatabaseSettings.from_url(TRANSACTION_POOLER_URL)


def test_the_transaction_pooler_rejection_explains_the_failure_and_the_fix() -> None:
    with pytest.raises(TransactionPoolerError) as raised:
        DatabaseSettings.from_url(TRANSACTION_POOLER_URL)
    message = str(raised.value)
    assert "prepared statement" in message.lower()
    assert "5432" in message
    assert "session" in message.lower()


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
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError) as raised:
        DatabaseSettings.from_env(env_file=tmp_path / "absent.env")
    assert "DATABASE_URL" in str(raised.value)


# --- reading the .env file -------------------------------------------------


def test_load_env_file_reads_a_simple_assignment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    path = tmp_path / ".env"
    path.write_text(f"DATABASE_URL={POOLER_URL}\n", encoding="utf-8")
    assert load_env_file(path) == {"DATABASE_URL": POOLER_URL}


def test_load_env_file_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text(
        "# a comment\n\n   \nDATABASE_URL=value\n# trailing comment\n", encoding="utf-8"
    )
    assert load_env_file(path) == {"DATABASE_URL": "value"}


def test_load_env_file_strips_quotes_and_an_export_prefix(tmp_path: Path) -> None:
    """Both forms are common in .env files copied from shell snippets."""
    path = tmp_path / ".env"
    path.write_text("export DATABASE_URL=\"quoted value\"\nOTHER='single'\n", encoding="utf-8")
    assert load_env_file(path) == {"DATABASE_URL": "quoted value", "OTHER": "single"}


def test_load_env_file_keeps_characters_that_appear_in_passwords(tmp_path: Path) -> None:
    """Passwords contain '=' and '#'. Splitting on every '=' or stripping every
    '#' would silently truncate the password and produce an auth failure that
    looks like a wrong password rather than a parsing bug."""
    path = tmp_path / ".env"
    path.write_text("DATABASE_URL=postgresql://u:pa=ss#word@host:5432/db\n", encoding="utf-8")
    assert load_env_file(path) == {"DATABASE_URL": "postgresql://u:pa=ss#word@host:5432/db"}


def test_load_env_file_returns_nothing_when_the_file_is_absent(tmp_path: Path) -> None:
    assert load_env_file(tmp_path / "nope.env") == {}


def test_from_env_falls_back_to_the_env_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    path = tmp_path / ".env"
    path.write_text(f"DATABASE_URL={POOLER_URL}\n", encoding="utf-8")
    settings = DatabaseSettings.from_env(env_file=path)
    assert settings.host == "aws-0-eu-central-1.pooler.supabase.com"


def test_a_real_environment_variable_beats_the_env_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """In CI the value comes from a secret, and a stray .env must never win."""
    monkeypatch.setenv("DATABASE_URL", POOLER_URL)
    path = tmp_path / ".env"
    path.write_text(
        "DATABASE_URL=postgresql://wrong:wrong@wrong.pooler.supabase.com:5432/postgres\n",
        encoding="utf-8",
    )
    settings = DatabaseSettings.from_env(env_file=path)
    assert settings.host == "aws-0-eu-central-1.pooler.supabase.com"


def test_storage_settings_hide_the_service_key() -> None:
    settings = StorageSettings(
        project_url="https://project.supabase.co",
        _service_key="service-secret",
        bucket="euroleague-api-archive",
    )

    assert "service-secret" not in repr(settings)
    assert settings.service_key() == "service-secret"


def test_storage_settings_read_the_same_env_file_without_printing_it(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text(
        "SUPABASE_URL=https://project.supabase.co\n"
        "SUPABASE_SERVICE_ROLE_KEY=service-secret\n"
        "SUPABASE_STORAGE_BUCKET=private-bucket\n",
        encoding="utf-8",
    )

    settings = StorageSettings.from_env(env_file=path)

    assert settings.project_url == "https://project.supabase.co"
    assert settings.bucket == "private-bucket"
    assert settings.service_key() == "service-secret"


SENTINEL_PASSWORD = "S3cr3t-P4ssw0rd!"
SENTINEL_USER = "sentinel_user"


@pytest.mark.parametrize(
    ("invalid_url", "expected_exception", "correction_keyword"),
    [
        (
            f"postgresql://{SENTINEL_USER}:{SENTINEL_PASSWORD}@:5432/postgres",
            ValueError,
            "Supabase dashboard",
        ),
        (
            f"postgresql://{SENTINEL_USER}:{SENTINEL_PASSWORD}@/postgres",
            ValueError,
            "Supabase dashboard",
        ),
        (
            f"postgresql://{SENTINEL_USER}:{SENTINEL_PASSWORD}@",
            ValueError,
            "Supabase dashboard",
        ),
        (
            f"https://{SENTINEL_USER}:{SENTINEL_PASSWORD}@example.com/db",
            ValueError,
            "postgresql://",
        ),
        (
            f"mysql://{SENTINEL_USER}:{SENTINEL_PASSWORD}@localhost:3306/db",
            ValueError,
            "postgresql://",
        ),
        (
            (
                f"postgresql://{SENTINEL_USER}:{SENTINEL_PASSWORD}"
                "@db.pctiewdpstnwcutrvegu.supabase.co:5432/postgres"
            ),
            DirectHostError,
            "pooler",
        ),
        (
            (
                f"postgresql://{SENTINEL_USER}:{SENTINEL_PASSWORD}"
                "@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"
            ),
            TransactionPoolerError,
            "5432",
        ),
        (
            "",
            ValueError,
            ".env",
        ),
        (
            "   ",
            ValueError,
            ".env",
        ),
    ],
)
def test_invalid_urls_never_expose_credentials_or_raw_url_and_provide_guidance(
    invalid_url: str,
    expected_exception: type[Exception],
    correction_keyword: str,
) -> None:
    """Invalid database URLs must never interpolate raw connection strings or secrets,
    and must provide actionable guidance."""
    with pytest.raises(expected_exception) as exc_info:
        DatabaseSettings.from_url(invalid_url)

    message = str(exc_info.value)
    if SENTINEL_PASSWORD in invalid_url:
        assert SENTINEL_PASSWORD not in message
    if invalid_url.strip():
        assert invalid_url not in message
    assert correction_keyword.lower() in message.lower()
