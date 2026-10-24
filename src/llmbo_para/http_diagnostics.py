"""Bounded machine diagnostics; exception messages never cross this boundary."""
from http.client import RemoteDisconnected
import socket
import ssl
from urllib.error import HTTPError, URLError


CATEGORIES = frozenset((
    'dns', 'connection_refused', 'connection_reset', 'connection_aborted',
    'broken_pipe', 'timeout', 'tls_certificate', 'tls_eof', 'tls_other',
    'remote_disconnected', 'other_os', 'unknown',
))
CAUSE_TYPES = frozenset((
    'gaierror', 'ConnectionRefusedError', 'ConnectionResetError',
    'ConnectionAbortedError', 'BrokenPipeError', 'TimeoutError',
    'SSLCertVerificationError', 'SSLEOFError', 'SSLError',
    'RemoteDisconnected', 'ConnectionError', 'OSError', 'other',
))
_NUMBERS = frozenset(('os_errno', 'winerror', 'tls_verify_code'))
_OS_CATEGORIES = {
    11001: 'dns', 11002: 'dns', 11003: 'dns', 11004: 'dns',
    10061: 'connection_refused', 111: 'connection_refused', 61: 'connection_refused',
    10054: 'connection_reset', 104: 'connection_reset', 54: 'connection_reset',
    10053: 'connection_aborted', 103: 'connection_aborted', 53: 'connection_aborted',
    10060: 'timeout', 110: 'timeout', 60: 'timeout', 32: 'broken_pipe',
}


def _integer(value: object) -> bool:
    return type(value) is int and -(2**31) <= value < 2**31


def public_network_diagnostic(value: object) -> dict | None:
    """Validate exact machine fields, including when read from untrusted JSON."""
    if type(value) is not dict or not {'category', 'cause_type'} <= value.keys():
        return None
    if value.keys() - {'category', 'cause_type', *_NUMBERS}:
        return None
    if (type(value['category']) is not str or value['category'] not in CATEGORIES
            or type(value['cause_type']) is not str or value['cause_type'] not in CAUSE_TYPES):
        return None
    for name in _NUMBERS & value.keys():
        if not _integer(value[name]) or name == 'tls_verify_code' and value[name] < 0:
            return None
    return dict(value)


def _unknown() -> dict:
    return {'network_diagnostic': {'category': 'unknown', 'cause_type': 'other'}}


def _classify(exc: BaseException) -> dict:
    category = None
    for cls, name in (
        (socket.gaierror, 'dns'),
        (ssl.SSLCertVerificationError, 'tls_certificate'),
        (ssl.SSLEOFError, 'tls_eof'),
        (ssl.SSLError, 'tls_other'),
        (RemoteDisconnected, 'remote_disconnected'),
        (TimeoutError, 'timeout'),
        (ConnectionRefusedError, 'connection_refused'),
        (ConnectionResetError, 'connection_reset'),
        (ConnectionAbortedError, 'connection_aborted'),
        (BrokenPipeError, 'broken_pipe'),
    ):
        if isinstance(exc, cls):
            category = name
            break
    if category is None:
        if not isinstance(exc, OSError):
            return {}
        winerror = getattr(exc, 'winerror', None)
        number = exc.errno
        category = (_OS_CATEGORIES.get(winerror) if _integer(winerror) else None)
        category = category or (_OS_CATEGORIES.get(number) if _integer(number) else None) or 'other_os'
    name = type(exc).__name__
    diagnostic = {'category': category, 'cause_type': name if name in CAUSE_TYPES else 'other'}
    for attribute, key in (('errno', 'os_errno'), ('winerror', 'winerror'), ('verify_code', 'tls_verify_code')):
        value = getattr(exc, attribute, None)
        if _integer(value) and (key != 'tls_verify_code' or value >= 0):
            diagnostic[key] = value
    return {'network_diagnostic': diagnostic}


def transport_error_fields(exc: BaseException) -> dict:
    """Unwrap at most four typed causes; string reasons and cycles stay unknown."""
    if isinstance(exc, HTTPError):
        return {}  # The HTTP status already identifies this failure class.
    seen = set()
    current = exc
    for _ in range(4):
        if id(current) in seen:
            return _unknown()
        seen.add(id(current))
        cause = current.reason if isinstance(current, URLError) else current.__cause__
        if isinstance(cause, BaseException):
            current = cause
            continue
        if isinstance(current, URLError):
            return _unknown()
        return _classify(current)
    return _unknown()
