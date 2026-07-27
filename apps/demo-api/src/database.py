import argparse
import json
import os
import time
from typing import Any, Callable, Dict, Optional, TypeVar

import psycopg


T = TypeVar("T")
MARKER_TABLE = "public.platform_failover_validation"


def _enabled(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def database_enabled() -> bool:
    return _enabled(os.getenv("DATABASE_ENABLED", "false"))


def _database_url() -> str:
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    return database_url


def _positive_number(name: str, default: str, cast: Callable[[str], T]) -> T:
    value = cast(os.getenv(name, default))
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero")
    return value


def _connect_timeout() -> int:
    return _positive_number("DATABASE_CONNECT_TIMEOUT_SECONDS", "3", int)


def _retry_attempts() -> int:
    return _positive_number("DATABASE_RETRY_ATTEMPTS", "3", int)


def _retry_delay() -> float:
    return _positive_number("DATABASE_RETRY_DELAY_SECONDS", "1", float)


def _run_with_retry(operation: Callable[[], T]) -> T:
    last_error: Optional[Exception] = None

    for attempt in range(1, _retry_attempts() + 1):
        try:
            return operation()
        except (psycopg.Error, OSError) as error:
            last_error = error
            if attempt < _retry_attempts():
                time.sleep(_retry_delay())

    raise RuntimeError("PostgreSQL operation failed after bounded retries") from last_error


def _connect() -> psycopg.Connection[Any]:
    return psycopg.connect(
        _database_url(),
        connect_timeout=_connect_timeout(),
        application_name="startup-devops-baseline-demo-api",
    )


def database_health() -> Dict[str, Any]:
    def query() -> Dict[str, Any]:
        with _connect() as connection:
            row = connection.execute(
                """
                SELECT current_database(),
                       current_user,
                       inet_server_addr()::text,
                       inet_server_port(),
                       pg_is_in_recovery()
                """
            ).fetchone()

        if row is None:
            raise RuntimeError("PostgreSQL health query returned no row")

        database, username, server_address, server_port, in_recovery = row
        return {
            "status": "ok",
            "database": database,
            "user": username,
            "server_address": server_address,
            "server_port": server_port,
            "in_recovery": in_recovery,
        }

    return _run_with_retry(query)


def write_marker(marker_id: str, marker_value: str) -> Dict[str, str]:
    def write() -> Dict[str, str]:
        with _connect() as connection:
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {MARKER_TABLE} (
                    id text PRIMARY KEY,
                    value text NOT NULL,
                    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
                )
                """
            )
            connection.execute(
                f"""
                INSERT INTO {MARKER_TABLE} (id, value)
                VALUES (%s, %s)
                ON CONFLICT (id) DO UPDATE
                SET value = EXCLUDED.value,
                    updated_at = clock_timestamp()
                """,
                (marker_id, marker_value),
            )

        return {"id": marker_id, "value": marker_value}

    return _run_with_retry(write)


def read_marker(marker_id: str) -> Dict[str, Optional[str]]:
    def read() -> Dict[str, Optional[str]]:
        with _connect() as connection:
            row = connection.execute(
                f"SELECT value FROM {MARKER_TABLE} WHERE id = %s",
                (marker_id,),
            ).fetchone()

        return {"id": marker_id, "value": None if row is None else row[0]}

    return _run_with_retry(read)


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Internal PostgreSQL validation commands for demo-api."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("health")

    write_parser = subparsers.add_parser("write-marker")
    write_parser.add_argument("--id", required=True)
    write_parser.add_argument("--value", required=True)

    read_parser = subparsers.add_parser("read-marker")
    read_parser.add_argument("--id", required=True)

    arguments = parser.parse_args()

    if arguments.command == "health":
        result = database_health()
    elif arguments.command == "write-marker":
        result = write_marker(arguments.id, arguments.value)
    else:
        result = read_marker(arguments.id)

    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
