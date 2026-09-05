"""Local-only, default-off fault gate for reviewed candidate rejection rehearsals."""
import hashlib
import hmac
import re

DISABLED = 'disabled'
AVAILABILITY_503 = 'availability-503'


def validate_configuration(mode: str, token_sha256: str, environment: str) -> None:
    if mode not in (DISABLED, AVAILABILITY_503):
        raise RuntimeError('Unsupported rehearsal fault mode')
    if mode == DISABLED:
        if token_sha256:
            raise RuntimeError('Disabled rehearsal fault mode must not retain a token digest')
        return
    if environment != 'local':
        raise RuntimeError('Rehearsal fault mode is local-only')
    if not re.fullmatch(r'[0-9a-f]{64}', token_sha256):
        raise RuntimeError('Enabled rehearsal fault mode requires a lowercase SHA-256 token digest')


def availability_failure_requested(mode: str, token_sha256: str, supplied_token: str | None) -> bool:
    if mode != AVAILABILITY_503 or not supplied_token:
        return False
    supplied_digest = hashlib.sha256(supplied_token.encode('utf-8')).hexdigest()
    return hmac.compare_digest(supplied_digest, token_sha256)
