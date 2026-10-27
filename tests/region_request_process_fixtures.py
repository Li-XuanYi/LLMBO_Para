"""Importable network-free workers for request supervision tests."""
import time


def stalled_request_worker(spec, payload, run_path, connection):
    time.sleep(10)
    connection.send(('result', {'ok': True, 'response': {}}))


def _with_offline_provider(mode, spec, payload, run_path, connection):
    """Patch only the child's socket-opening boundary; run the real worker."""
    from io import BytesIO
    import json
    import os
    from unittest.mock import patch
    from urllib.error import HTTPError
    from llmbo_para.electrothermal_requests import _chat_request_worker

    class Response:
        status = 200

        def read(self, count):
            if mode == 'blocked_read':
                time.sleep(60)
            if mode == 'malformed_outer':
                return b'{invalid outer response'[:count]
            content = ('{invalid inner response' if mode == 'malformed_inner' else
                json.dumps({'region': {'kind': 'none', 'coordinate_space': 'normalized',
                    'confidence': 0., 'reason': os.environ[spec['api_key_env']]}}))
            return json.dumps({'model': 'offline-worker-model', 'choices': [
                {'finish_reason': 'stop', 'message': {'content': content}}]}).encode('utf8')[:count]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class Provider:
        def open(self, request, **kwargs):
            wire = json.loads(request.data)
            assert wire['stream'] is False
            assert any('json' in row['content'].lower() for row in wire['messages'])
            if mode == 'http_error':
                body = json.dumps({'error': {'message': os.environ[spec['api_key_env']],
                    'code': 'invalid_parameter_error'}}).encode('utf8')
                raise HTTPError(request.full_url, 400, 'offline provider rejection', {}, BytesIO(body))
            return Response()

    with patch('llmbo_para.llm.build_opener', return_value=Provider()):
        _chat_request_worker(spec, payload, run_path, connection)


def successful_request_worker(spec, payload, run_path, connection):
    _with_offline_provider('success', spec, payload, run_path, connection)


def http_error_request_worker(spec, payload, run_path, connection):
    _with_offline_provider('http_error', spec, payload, run_path, connection)


def malformed_inner_request_worker(spec, payload, run_path, connection):
    _with_offline_provider('malformed_inner', spec, payload, run_path, connection)


def malformed_outer_request_worker(spec, payload, run_path, connection):
    _with_offline_provider('malformed_outer', spec, payload, run_path, connection)


def blocked_http_request_worker(spec, payload, run_path, connection):
    _with_offline_provider('blocked_read', spec, payload, run_path, connection)
