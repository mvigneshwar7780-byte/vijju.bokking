"""Connection settings: the parts that are easy to get silently wrong.

None of these touch a database. They guard three things that fail quietly
rather than loudly:

* a password that needs URL-escaping and doesn't get it,
* a TLS mode that looks configured but isn't passed to the driver,
* a pool that can open more connections than the plan allows.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings


def _settings(**overrides: object) -> Settings:
    """Settings built in isolation.

    `_env_file=None` matters: without it these would read the developer's real
    `.env`, so a test asserting a default would pass or fail depending on which
    database that machine happens to be pointed at.
    """
    base = {
        "postgres_host": "db.example.com",
        "postgres_port": 19798,
        "postgres_user": "avnadmin",
        "postgres_password": "s3cret",
        "postgres_db": "defaultdb",
    }
    return Settings(_env_file=None, **{**base, **overrides})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "password",
    [
        "p@ssword",            # @ would end the userinfo section
        "pa/ss",               # / would start the path
        "pa?ss",               # ? would start the query
        "pa#ss",               # # would start the fragment
        "pa:ss",               # : would split user:password
        "AVNS_x1Y-2z_A3b4C5d", # a realistic provider-generated secret
    ],
)
def test_password_special_characters_are_escaped(password: str) -> None:
    """Provider passwords routinely contain URL-significant characters.

    A hand-built DSN corrupts these silently -- the connection fails with a
    confusing auth or host error rather than anything pointing at escaping.
    """
    url = _settings(postgres_password=password).database_url
    assert url.startswith("postgresql+psycopg://avnadmin:")
    assert url.endswith("@db.example.com:19798/defaultdb")
    # The raw character must not appear unescaped in the credentials section.
    credentials = url.split("://", 1)[1].rsplit("@", 1)[0]
    for char in "@/?#":
        assert char not in credentials.split(":", 1)[1], (
            f"{char!r} left unescaped in the password"
        )


def test_sslmode_reaches_the_driver() -> None:
    args = _settings(postgres_sslmode="verify-full").db_connect_args
    assert args["sslmode"] == "verify-full"


def test_ca_certificate_is_passed_only_when_configured() -> None:
    assert "sslrootcert" not in _settings().db_connect_args
    args = _settings(postgres_sslrootcert="certs/aiven-ca.pem").db_connect_args
    assert args["sslrootcert"] == "certs/aiven-ca.pem"


def test_connection_string_never_leaks_the_password() -> None:
    """`database_host_summary` is logged and returned by /health."""
    summary = _settings(postgres_password="hunter2").database_host_summary
    assert "hunter2" not in summary
    assert "db.example.com" in summary


def test_pool_ceiling_stays_within_a_small_plan() -> None:
    """pool_size + max_overflow is what this process can actually open.

    Aiven's entry plan allows 20 *in total*, shared with migrations and psql.
    The default must leave room; exceeding it turns into connection errors
    under load rather than anything obviously pool-related.
    """
    s = _settings()
    assert s.db_pool_size + s.db_max_overflow <= 10


def test_application_name_is_set_for_pg_stat_activity() -> None:
    """So it is obvious which client holds a connection when near the cap."""
    assert "cineai" in _settings().db_connect_args["application_name"]
