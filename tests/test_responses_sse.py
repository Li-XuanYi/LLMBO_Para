"""SSE completion framing and safety; no live network."""
from copy import deepcopy
import importlib
import importlib.util
import json

import pytest

from test_electrothermal_responses import feature, payload, response


def codec():
    name = 'llmbo_para.electrothermal_sse'
    assert importlib.util.find_spec(name) is not None, 'bounded SSE decoder missing'
    return importlib.import_module(name)


def entries(raw=None):
    raw = response({'answer':'温度🙂\u2028目标'}) if raw is None else raw
    return [{'event':'response.created','data':{'type':'response.created','sequence_number':0,
                'response':{'id':'resp-unit','status':'in_progress'}}},
            {'event':None,'data':{'type':'response.output_text.delta','sequence_number':4,
                'delta':'尚未完成🙂\u2028'}},
            {'event':'response.completed','data':{'type':'response.completed','sequence_number':20,
                'response':{'id':'resp-unit',**raw}}}]


def encode(items, newline='\n', *, event=True, multiline=False):
    frames = []
    for entry in items:
        body = json.dumps(entry['data'],ensure_ascii=False,indent=2 if multiline else None)
        frames.append((('event: '+entry['event']+newline) if event and entry['event'] else '')+
            newline.join('data: '+line for line in body.split('\n'))+newline+newline)
    return (': keep-alive'+newline+newline+newline.join(frames)).encode('utf8')


class Recorder:
    def __init__(self): self.entries, self.events = [], []
    def start_stream(self, task): pass
    def append_stream(self, task, entry): self.entries.append(deepcopy(entry))
    def append_event(self, event): self.events.append(deepcopy(event))


class ByteResponse:
    status = 200
    def __init__(self,chunks,mime='text/event-stream; charset=utf-8'):
        self.chunks=list(chunks); self.mime=mime; self.calls=0
    def getheader(self,name,default=None): return self.mime if name.lower()=='content-type' else default
    def read1(self,count):
        self.calls += 1
        if not self.chunks: return b''
        chunk = self.chunks.pop(0)
        if len(chunk)>count:
            self.chunks.insert(0,chunk[count:]); chunk=chunk[:count]
        return chunk


def read(chunks, **kwargs):
    archive = Recorder()
    result = codec().read_responses_sse(ByteResponse(chunks,**kwargs),archive=archive,task='request',redact=lambda value:value)
    return result, archive


@pytest.mark.parametrize('newline',['\n','\r\n','\r'])
@pytest.mark.parametrize('multiline',[False,True])
@pytest.mark.parametrize('size',[1,7,8192])
def test_arbitrary_chunks_utf8_unicode_and_sse_lines(newline,multiline,size):
    wire=encode(entries(),newline,multiline=multiline)
    raw,archive=read([wire[i:i+size] for i in range(0,len(wire),size)])
    assert feature().decode_responses_json(raw)==({'answer':'温度🙂\u2028目标'},None)
    assert len(archive.entries)==3
    assert codec().decode_sse_events(archive.entries)==raw


def test_bom_unknown_fields_no_event_field_and_no_extra_eof_wait():
    wire=b'\xef\xbb\xbf'+b'unknown: ignored\nretry: 10\nid: ignored\n'+encode(entries(),event=False)
    class NoExtraRead(ByteResponse):
        def read1(self,count):
            assert self.chunks, 'completed stream must not wait for socket EOF'
            return super().read1(count)
    result=codec().read_responses_sse(NoExtraRead([wire]),archive=Recorder(),task='request',redact=lambda v:v)
    assert feature().decode_responses_json(result)[1] is None


@pytest.mark.parametrize('damage',['no_terminal','no_blank_dispatch','done_marker','malformed_json','nonfinite',
    'repeated_sequence','boolean_sequence','wrong_event','unknown_type','tool','wrong_id','status_mismatch','invalid_utf8'])
def test_partial_or_invalid_stream_never_produces_a_completion(damage):
    items=entries()
    if damage=='no_terminal': items=items[:-1]
    elif damage=='repeated_sequence': items[-1]['data']['sequence_number']=4
    elif damage=='boolean_sequence': items[-1]['data']['sequence_number']=True
    elif damage=='wrong_event': items[-1]['event']='response.incomplete'
    elif damage=='unknown_type': items[-1]['event']=items[-1]['data']['type']='future.event'
    elif damage=='tool': items[-1]['event']=items[-1]['data']['type']='response.function_call_arguments.delta'
    elif damage=='wrong_id': items[-1]['data']['response']['id']='other'
    elif damage=='status_mismatch': items[-1]['data']['response']['status']='failed'
    wire=encode(items)
    if damage=='no_blank_dispatch': wire=wire[:-1]
    if damage=='done_marker': wire=b'data: [DONE]\n\n'
    if damage=='malformed_json': wire=b'data: {broken}\n\n'
    if damage=='nonfinite': wire=b'data: {"type":"response.created","sequence_number":NaN}\n\n'
    if damage=='invalid_utf8': wire=b'data: \xff\n\n'
    with pytest.raises(ValueError): read([wire])


@pytest.mark.parametrize('status',['failed','incomplete'])
def test_failed_terminal_retains_original_response_but_is_not_formal_success(status):
    items=entries()
    raw=response(status=status)
    if status=='failed': raw['error']={'code':'server_error','message':'failed'}
    else: raw['incomplete_details']={'reason':'max_output_tokens'}
    items[-1]['event']=items[-1]['data']['type']='response.'+status
    items[-1]['data']['response']={'id':'resp-unit',**raw}
    result,archive=read([encode(items)])
    assert result=={'id':'resp-unit',**raw}
    assert feature().decode_responses_json(result)[1]=='unfinished_completion'


@pytest.mark.parametrize('mode',['bytes','events','mime','error'])
def test_bounded_reader_rejects_oversize_or_wrong_protocol(mode):
    wire=encode(entries())
    kwargs={}
    if mode=='bytes': wire=b':'+b'x'*(1024*1024)+b'\n\n'+wire
    if mode=='events':
        wire=b''.join(('data: '+json.dumps({'type':'response.in_progress','sequence_number':i})+'\n\n').encode() for i in range(4097))
    if mode=='mime': kwargs['mime']='application/json'
    if mode=='error': wire=b'data: {"type":"error","sequence_number":0,"code":"server_error"}\n\n'
    with pytest.raises(ValueError): read([wire],**kwargs)


def test_actual_transport_uses_stream_decoder_and_original_formal_validator(monkeypatch,tmp_path):
    from test_electrothermal_responses import MemoryArchive
    sent=[]; archive=MemoryArchive(tmp_path)
    archive.start_stream=lambda task:None
    archive.append_stream=lambda task,item:archive.files.setdefault('stream',[]).append(deepcopy(item))
    class HTTP(ByteResponse):
        def __enter__(self): return self
        def __exit__(self,*args): return False
    class Provider:
        def open(self,request,**kwargs):
            sent.append(json.loads(request.data))
            events=entries(response({'answer':42}))
            events[1]['data']['delta']='sse-private-'
            events.insert(2,{'event':None,'data':{'type':'response.output_text.delta',
                'sequence_number':5,'delta':'unit-value'}})
            return HTTP([encode(events)])
    monkeypatch.setattr('llmbo_para.llm.build_opener',lambda *a:Provider())
    monkeypatch.setenv('SSE_UNIT_TOKEN','sse-private-unit-value')
    client=feature().ResponsesTransport('https://provider.invalid/v1/responses','SSE_UNIT_TOKEN',
        model='deepseek-v4-pro',max_tokens=8192,json_mode=True,responses_stream=True,run_store=archive)
    assert client.post(payload())=={'answer':42}
    assert len(sent)==1 and sent[0]['stream'] is True
    assert any(name.endswith('.response.json') for name in archive.files)
    assert 'sse-private-unit-value' not in json.dumps(archive.files)
    assert 'sse-private-' not in json.dumps(archive.files), 'stream delta fragments must not reconstruct a credential'
