"""Importable child fixture; HTTP boundary only, with all sockets forbidden."""
def _offline(mode, spec, payload, run_path, connection):
    import json
    import socket
    from unittest.mock import patch
    from llmbo_para.electrothermal_requests import _chat_request_worker
    reply = {}
    class Response:
        status = 200
        def read(self, count):
            return json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': [] if mode == 'invalid' else json.dumps(reply)}}],
                'usage': {'completion_tokens': 128, 'completion_tokens_details': {'reasoning_tokens': 0}}}).encode()[:count]
        def __enter__(self): return self
        def __exit__(self, *args): return False
    class Provider:
        def open(self, request, **kwargs):
            body = json.loads(request.data)
            assert body['thinking'] == {'type': 'disabled'}
            user = json.loads(body['messages'][1]['content'])
            reply.update(request_id=user['request_id'], region={'kind': 'none', 'coordinate_space': 'normalized',
                'confidence': .5, 'reason': 'offline integration fixture'})
            return Response()
    def forbidden(*args, **kwargs): raise AssertionError('offline fixture attempted a socket connection')
    with patch('llmbo_para.llm.build_opener', return_value=Provider()), patch.object(socket.socket, 'connect', forbidden):
        _chat_request_worker(spec, payload, run_path, connection)


def successful_compact_worker(spec, payload, run_path, connection):
    _offline('success', spec, payload, run_path, connection)


def invalid_content_worker(spec, payload, run_path, connection):
    _offline('invalid', spec, payload, run_path, connection)
