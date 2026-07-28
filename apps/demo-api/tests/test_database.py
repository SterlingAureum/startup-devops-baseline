import os
import unittest
from unittest.mock import patch

from src import database


class DatabaseConfigurationTests(unittest.TestCase):
    def test_database_enabled_accepts_explicit_true_values(self) -> None:
        for value in ("1", "true", "TRUE", "yes", "on"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"DATABASE_ENABLED": value}, clear=False):
                    self.assertTrue(database.database_enabled())

    def test_database_enabled_defaults_to_false(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(database.database_enabled())

    def test_database_url_requires_a_configured_value(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                RuntimeError,
                "DATABASE_URL is not configured",
            ):
                database._database_url()

    def test_retry_returns_after_a_transient_operating_system_error(self) -> None:
        attempts = 0

        def operation() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OSError("temporary failure")
            return "ok"

        with patch.dict(
            os.environ,
            {
                "DATABASE_RETRY_ATTEMPTS": "2",
                "DATABASE_RETRY_DELAY_SECONDS": "0.001",
            },
            clear=False,
        ):
            with patch("src.database.time.sleep"):
                self.assertEqual(database._run_with_retry(operation), "ok")

        self.assertEqual(attempts, 2)


if __name__ == "__main__":
    unittest.main()
