import hashlib
import unittest

from src.rehearsal_fault import availability_failure_requested, validate_configuration


class RehearsalFaultTests(unittest.TestCase):
    def test_disabled_is_default_safe(self) -> None:
        validate_configuration('disabled', '', 'local')
        self.assertFalse(availability_failure_requested('disabled', '', 'secret'))
        self.assertFalse(availability_failure_requested('disabled', '', None))

    def test_exact_token_enables_only_reviewed_availability_failure(self) -> None:
        token = 'one-run-private-token'
        digest = hashlib.sha256(token.encode()).hexdigest()
        validate_configuration('availability-503', digest, 'local')
        self.assertTrue(availability_failure_requested('availability-503', digest, token))
        self.assertFalse(availability_failure_requested('availability-503', digest, 'wrong'))
        self.assertFalse(availability_failure_requested('availability-503', digest, None))

    def test_enabled_mode_is_local_only_and_requires_digest(self) -> None:
        digest = 'a' * 64
        for mode, value, environment in (
            ('other', '', 'local'),
            ('disabled', digest, 'local'),
            ('availability-503', '', 'local'),
            ('availability-503', digest, 'aws-dev'),
        ):
            with self.subTest(mode=mode, value=value, environment=environment):
                with self.assertRaises(RuntimeError):
                    validate_configuration(mode, value, environment)


if __name__ == '__main__':
    unittest.main()
