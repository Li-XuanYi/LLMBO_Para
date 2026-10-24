"""A stream's complete terminal response must independently bind to its use."""
from copy import deepcopy
from functools import partial
import json
from pathlib import Path
import shutil

import pytest

from test_responses_stream_controls import stream_worker, ENV
from test_network_diagnostic_audit import read, put, synchronize_round_outcome


@pytest.fixture(scope='module')
def archives(): return {}


def fixture_run(archives,monkeypatch,tmp_path_factory,stream=True,kind='success'):
    from test_region_failure_audit import _shared_initialization
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para import electrothermal_responses as module
    key=(stream,kind)
    if key in archives: return archives[key]
    if 'shared' not in archives:
        archives['shared']=_shared_initialization(tmp_path_factory.mktemp('si'))
    cfg=deepcopy(archives['shared'])
    cfg['optimization'].pop('region')
    cfg['optimization'].update(region_method='lgbo_v1',gp_sweeps=0,mode='full_llmbo_mo')
    cfg['llm'].update(transport='openai_responses',enabled=False,
        endpoint='https://provider.invalid/v1/responses',api_key_env=ENV,
        model='deepseek-v4-pro',max_tokens=2048,timeout_s=15.)
    if stream is not None: cfg['llm']['responses_stream']=stream
    monkeypatch.setenv(ENV,'offline-stream-audit-placeholder')
    monkeypatch.setattr(module,'_responses_request_worker',partial(stream_worker,kind))
    client=module.BoundedResponsesTransport(cfg['llm']['endpoint'],ENV,
        model=cfg['llm']['model'],max_tokens=2048,json_mode=True,timeout_s=15.)
    controller=ElectrothermalLLMController(transport=client,is_mock=True)
    root=tmp_path_factory.mktemp('sr')
    summary=run_electrothermal_experiment(cfg,root,base_dir=root,llm_controller=controller)
    archives[key]=Path(summary['run_directory'])
    return archives[key]


@pytest.mark.parametrize('stream',[None,False,True])
def test_complete_stream_and_old_nonstream_deep_replay(archives,monkeypatch,tmp_path_factory,stream):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    run=fixture_run(archives,monkeypatch,tmp_path_factory,stream)
    result=audit_electrothermal_run(run,deep=True)
    assert result['passed'],result['issues']
    assert bool(list((run/'http').glob('*.stream.jsonl'))) is (stream is True)
    assert all(read(path)['status']=='received' for path in (run/'llm').glob('*.outcome.json'))


@pytest.mark.parametrize('damage',['delete_stream','delete_terminal','bad_sequence','wrong_id',
    'derived_response','outcome_control','supervision_control','delete_all_controls'])
def test_stream_tampering_cannot_hide_behind_derived_response(archives,monkeypatch,tmp_path_factory,tmp_path,damage):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    run=tmp_path/'copy'
    original=fixture_run(archives,monkeypatch,tmp_path_factory)
    baseline=audit_electrothermal_run(original,deep=True)
    assert baseline['passed'],baseline['issues']
    shutil.copytree(original,run)
    raw=sorted((run/'http').glob('*.stream.jsonl'))[0]
    outcome_path=sorted((run/'llm').glob('*.outcome.json'))[0]
    outcome=read(outcome_path)
    p=read(run/'llm'/f'{outcome["ordinal"]:06d}.payload.json')
    if damage=='delete_stream': raw.unlink()
    elif damage in ('delete_terminal','bad_sequence','wrong_id'):
        events=[json.loads(line) for line in raw.read_text().splitlines()]
        if damage=='delete_terminal': events.pop()
        elif damage=='bad_sequence': events[-1]['data']['sequence_number']=True
        else: events[-1]['data']['response']['output'][0]['content'][0]['text']='{"request_id":"wrong"}'
        raw.write_text(''.join(json.dumps(event)+'\n' for event in events),encoding='utf8')
    elif damage=='derived_response':
        path=raw.with_name(raw.name.replace('.stream.jsonl','.response.json'))
        value=read(path);value['output'][0]['content'][0]['text']='{"request_id":"wrong"}';put(path,value)
    else:
        supervision=run/'http'/(p['artifact_task']+'.supervision.json')
        targets=([outcome_path,supervision] if damage=='delete_all_controls' else
                 [outcome_path] if damage=='outcome_control' else [supervision])
        for path in targets:
            value=read(path)
            if damage=='delete_all_controls': value.pop('responses_stream')
            else: value['responses_stream']=False
            put(path,value)
        synchronize_round_outcome(run,read(outcome_path))
    result=audit_electrothermal_run(run,deep=True)
    assert not result['passed'],result


def test_partial_stream_is_diagnostic_not_a_zero_objective_or_formal_reply(archives,monkeypatch,tmp_path_factory):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    run=fixture_run(archives,monkeypatch,tmp_path_factory,kind='partial')
    assert list((run/'http').glob('*.stream.jsonl'))
    assert not list((run/'http').glob('*.response.json'))
    assert not list((run/'llm').glob('*.responses-formal.json'))
    for path in (run/'mo-rounds').glob('*.json'):
        assert read(path)['region']['tilt_applied'] is False
    result=audit_electrothermal_run(run,deep=True)
    assert result['passed'],result['issues']


def test_stream_changes_config_signature_without_relaxing_initialization_compatibility(archives,monkeypatch,tmp_path_factory):
    from llmbo_para.electrothermal_provenance import build_electrothermal_signatures
    from llmbo_para.electrothermal_data import load_electrothermal_dataset
    run=fixture_run(archives,monkeypatch,tmp_path_factory,None)
    cfg=deepcopy(read(run/'manifest.json')['config'])
    dataset=load_electrothermal_dataset(cfg,run)
    before=build_electrothermal_signatures(cfg,dataset)
    cfg['llm']['responses_stream']=True
    after=build_electrothermal_signatures(cfg,dataset)
    assert before.config!=after.config and before.algorithm!=after.algorithm
    assert before.data==after.data and before.initialization_compatibility==after.initialization_compatibility


def test_stream_archive_jsonl_only_splits_actual_newlines(tmp_path):
    from llmbo_para.electrothermal_json import audit_responses_stream
    from test_electrothermal_responses import response
    raw=response({'answer':42})
    raw['output'][0]['content'][0]['text']=json.dumps({'answer':'温度\u2028目标'},ensure_ascii=False)
    folder=tmp_path/'http';folder.mkdir()
    event={'event':'response.completed','data':{'type':'response.completed','sequence_number':2,'response':raw}}
    (folder/'request.stream.jsonl').write_text(json.dumps(event,ensure_ascii=False)+'\n',encoding='utf8')
    put(folder/'request.response.json',raw)
    audit_responses_stream(tmp_path,'request',responses_stream=True,needs_complete=True,headers_received=True)


def test_stream_template_is_disabled_with_zero_live_budget():
    from llmbo_para.electrothermal_config import electrothermal_configuration_errors
    path=Path(__file__).resolve().parents[1]/'configs/electrothermal-sub2api-stream-software-template.json'
    assert path.is_file(), 'zero-budget stream template missing'
    cfg=read(path)
    assert electrothermal_configuration_errors(cfg)==[]
    assert cfg['llm']['responses_stream'] is True and cfg['llm']['reasoning_effort']=='none'
    assert cfg['llm']['enabled'] is False and cfg['optimization']['mode']=='parego'
    assert cfg['budgets']['max_llm_requests']==cfg['budgets']['max_solver_calls']==0
