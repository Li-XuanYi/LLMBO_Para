"""Offline Responses archives, including independent raw-reply tamper replay."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json

import numpy as np
import pytest

from test_electrothermal_responses import response, feature


def read(path): return json.loads(path.read_text(encoding='utf8'))
def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf8')


@pytest.fixture(scope='module')
def cache(): return {}


def fixture_run(cache, tmp_path_factory, *, kind='region', wire='compact_v1', catalog=True):
    key = (kind, wire, catalog)
    if key in cache: return cache[key]
    from electrothermal_fixtures import et_config
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment, prepare_electrothermal_experiment
    from llmbo_para.electrothermal_region_wire import region_wire_payload
    from llmbo_para.informed import InformedSettings
    from test_region_failure_audit import _shared_initialization
    from test_electrothermal_llm import Proposed
    root = tmp_path_factory.mktemp('responses_audit')
    cfg = et_config() if kind == 'warm' else _shared_initialization(root)
    cfg['llm'].update(transport='openai_responses', enabled=False, endpoint='https://provider.invalid/v1/responses',
                      api_key_env='RESPONSES_AUDIT_UNUSED_KEY', model='deepseek-v4-pro', region_wire_format=wire)
    captured = []
    if kind == 'warm':
        cfg['optimization'].update(mode='warmstart_only', total_candidate_budget=2)
        _, prepared = prepare_electrothermal_experiment(cfg, base_dir=root)
        assert prepared is not None
        proposed = Proposed(prepared.space, [[.2]*6, [.8]*6, [.21]*6, [.7]*6])
    else:
        cfg['optimization'].update(region_evidence='dynamic_decision_v3', region_proposal='catalog_v1' if catalog else 'bounds_v1',
            region_advice='candidate_aware_v1', region_selection='fair_region_v1')
        cfg['optimization']['region'].update(max_plain_log_ei_gap=100., min_sigma_ratio=0.)
    class Advice:
        def post(self, p):
            if kind == 'warm':
                formal = proposed.post(p)
            else:
                region = {'kind': 'none' if kind == 'none' else 'region', 'coordinate_space': 'normalized',
                          'confidence': 0. if kind=='low' else .9, 'reason': 'controlled offline hypothesis'}
                if catalog:
                    region['proposal_binding'] = p['proposal_binding']
                    if region['kind'] == 'region':
                        region.update(region_id=p['region_catalog']['entries'][0]['region_id'],
                                      evidence_ids=[p['history'][0]['evaluation_id']])
                elif region['kind'] == 'region':
                    row = next(r for r in p['candidate_advice']['candidates'] if r['eligible_alternative'])
                    width = InformedSettings.parse(cfg['optimization']['region']).min_width
                    lower = np.clip(np.asarray(row['normalized_parameters'])-width/2, 0, 1-width)
                    region.update(lb=lower.tolist(), ub=(lower+width).tolist())
                formal = {**{k: deepcopy(p[k]) for k in ('schema_version','parameter_profile','fit_rates','signatures','context_id')}, 'region': region}
            # A socket JSON response contains native lists/numbers, not host tuples.
            formal=json.loads(json.dumps(formal))
            captured.append(deepcopy(formal))
            if kind == 'failure': raise ValueError('offline protocol failure')
            return formal
    summary = run_electrothermal_experiment(cfg, root, base_dir=root,
        llm_controller=ElectrothermalLLMController(transport=Advice(), is_mock=True))
    run = Path(summary['run_directory'])
    # These are explicit HTTP-shaped software fixtures, not evidence of a live call.
    for n, path in enumerate(sorted((run/'llm').glob('*.payload.json'))):
        p = read(path)
        from llmbo_para.runstore import canonical_json
        frozen=json.loads(canonical_json(p)) if p.get('region_proposal')=='catalog_v1' else p
        sent = region_wire_payload(frozen); formal = captured[n]
        if p['task']=='region_preference_electrothermal' and wire=='compact_v1':
            formal = {'request_id': sent['request_id'], 'region': formal['region']}
        raw = response(formal, usage={'input_tokens': 50, 'output_tokens': 20, 'total_tokens': 70})
        if kind == 'failure': raw['status'] = 'incomplete'
        body = feature().responses_request_body(sent, model=cfg['llm']['model'], max_tokens=cfg['llm']['max_tokens'], json_mode=True)
        artifact = p['artifact_task']
        put(run/'http'/(artifact+'.request.json'), {'endpoint':cfg['llm']['endpoint'], 'headers':{}, 'body':body})
        put(run/'http'/(artifact+'.response.json'), raw)
        outcome_path = run/f'llm/{n:06d}.outcome.json'; outcome = read(outcome_path)
        completion = feature().responses_completion_summary(raw, cfg['llm']['max_tokens'])
        outcome.update(hard_deadline_enforced=True, http_request_started=True,
                       response_protocol='openai_responses', completion=completion)
        supervision = {'configured_timeout_s':cfg['llm']['timeout_s'], 'effective_timeout_s':cfg['llm']['timeout_s'],
            'max_tokens':cfg['llm']['max_tokens'], 'response_protocol':'openai_responses',
            'http_status':200, 'http_request_started':True, 'completion':completion,
            'status':'failed' if kind=='failure' else 'completed'}
        if kind == 'failure':
            outcome['protocol_issue'] = supervision['protocol_issue'] = 'unfinished_completion'
            put(run/'http'/(artifact+'.parse-error.json'), {'protocol_issue':'unfinished_completion'})
        put(outcome_path, outcome)
        put(run/'http'/(artifact+'.supervision.json'), supervision)
        for round_path in (run/'mo-rounds').glob('*.json'):
            event=read(round_path)
            if event.get('region',{}).get('request_outcome',{}).get('ordinal')==n:
                event['region']['request_outcome']=deepcopy(outcome);put(round_path,event)
    cache[key] = run
    return run


@pytest.mark.parametrize('wire', ['full_v1', 'compact_v1'])
@pytest.mark.parametrize('kind,catalog', [('warm',False), ('region',True), ('none',True), ('low',True), ('failure',True), ('region',False)])
def test_responses_full_and_compact_archives_replay(cache, tmp_path_factory, wire, kind, catalog):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    run=fixture_run(cache,tmp_path_factory,kind=kind,wire=wire,catalog=catalog)
    result=audit_electrothermal_run(run,deep=True)
    assert result['passed'],result['issues']
    if kind!='failure':
        assert list((run/'llm').glob('*.responses-formal.json'))
    if kind=='low':
        assert all(read(path)['region']['fallback_reason']=='low_confidence' for path in (run/'mo-rounds').glob('*.json'))


@pytest.mark.parametrize('damage', ['endpoint','model','store','input','instructions','max_output_tokens',
                                  'status','usage','supervision','formal'])
def test_responses_audit_rebuilds_wire_and_completion(cache,tmp_path_factory,damage):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    run=fixture_run(cache,tmp_path_factory)
    p=read(next((run/'llm').glob('*.payload.json')));artifact=p['artifact_task']
    request=run/'http'/(artifact+'.request.json');raw=run/'http'/(artifact+'.response.json')
    formal=run/'llm/000000.responses-formal.json'
    target = formal if damage=='formal' else raw if damage in ('status','usage') else run/'http'/(artifact+'.supervision.json') if damage=='supervision' else request
    assert target.exists(), 'new Responses formal evidence is required'
    original=target.read_bytes();value=read(target)
    try:
        if damage=='endpoint':value['endpoint']='https://other.invalid/v1/responses'
        elif damage=='input':value['body']['input']='{}'
        elif damage=='model':value['body']['model']='other-model'
        elif damage=='store':value['body']['store']=True
        elif damage=='instructions':value['body']['instructions']='forged'
        elif damage=='max_output_tokens':value['body']['max_output_tokens']+=1
        elif damage=='status':value['status']='incomplete'
        elif damage=='usage':value['usage']['output_tokens']+=1
        elif damage=='supervision':value['response_protocol']='openai_chat_completions'
        else:value['response_json']='{}'
        put(target,value)
        assert not audit_electrothermal_run(run,deep=True)['passed']
    finally:target.write_bytes(original)


def test_joint_response_and_resolution_tamper_rejected(cache,tmp_path_factory):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    run=fixture_run(cache,tmp_path_factory);p=read(next((run/'llm').glob('*.payload.json')))
    paths=[run/'http'/(p['artifact_task']+'.response.json'),run/'llm/000000.catalog-response.json',
           run/'llm/000000.catalog-resolution.json',run/'llm/000000.responses-formal.json']
    assert all(path.exists() for path in paths)
    originals={path:path.read_bytes() for path in paths}
    try:
        raw=read(paths[0]);formal=json.loads(raw['output'][0]['content'][0]['text']);formal['region']['region_id']='unknown-forged-ID'
        raw['output'][0]['content'][0]['text']=json.dumps(formal);put(paths[0],raw)
        for path in (paths[1],paths[3]):
            value=read(path);decoded=json.loads(value['response_json']);decoded['region']['region_id']='unknown-forged-ID'
            value['response_json']=json.dumps(decoded);put(path,value)
        value=read(paths[2]);value['region_id']='unknown-forged-ID';put(paths[2],value)
        assert not audit_electrothermal_run(run,deep=True)['passed']
    finally:
        for path,original in originals.items():path.write_bytes(original)


def test_protocol_is_not_guessed_from_body(cache,tmp_path_factory):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    run=fixture_run(cache,tmp_path_factory);p=read(next((run/'llm').glob('*.payload.json')))
    path=run/'http'/(p['artifact_task']+'.response.json');original=path.read_bytes()
    try:
        put(path,{'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]})
        assert not audit_electrothermal_run(run,deep=True)['passed']
    finally:path.write_bytes(original)


def test_bounds_protocol_failure_cannot_be_relabelled_after_joint_raw_tamper(cache,tmp_path_factory):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    run=fixture_run(cache,tmp_path_factory,kind='failure',wire='full_v1',catalog=False)
    p=read(run/'llm/000000.payload.json');artifact=p['artifact_task']
    paths=[run/'http'/(artifact+'.response.json'),run/'http'/(artifact+'.supervision.json'),
           run/'llm/000000.outcome.json']
    rounds=[path for path in (run/'mo-rounds').glob('*.json')
            if read(path)['region']['request_outcome'].get('ordinal')==0]
    originals={path:path.read_bytes() for path in paths+rounds}
    try:
        raw=read(paths[0]);raw['status']='completed';put(paths[0],raw)
        completion=feature().responses_completion_summary(raw,2048)
        for path in paths[1:]:
            value=read(path);value.pop('protocol_issue',None);value['completion']=completion;put(path,value)
        for path in rounds:
            value=read(path);value['region']['request_outcome']=read(paths[2]);put(path,value)
        # This is now a valid, bound reply with an impossible protocol_error claim.
        assert not audit_electrothermal_run(run,deep=True)['passed']
    finally:
        for path,original in originals.items():path.write_bytes(original)


def test_same_formal_proposal_keeps_region_numbers():
    from test_region_catalog import payload,reply,context_advice
    from llmbo_para.electrothermal_region_catalog import decode_catalog_http_response,resolve_catalog_region
    from llmbo_para.electrothermal_llm import apply_electrothermal_region
    from llmbo_para.electrothermal_config import electrothermal_space_from_config
    from llmbo_para.informed import InformedSettings
    from llmbo_para.surrogate import Matern52GP
    from llmbo_para.runstore import digest_value
    from electrothermal_fixtures import et_config
    p=payload();formal=reply(p);c,_=context_advice()
    a,issue=decode_catalog_http_response(response(formal),payload=p,transport='openai_responses')
    assert issue is None
    b,issue=decode_catalog_http_response({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(formal)}}]},payload=p)
    assert issue is None
    a,_=resolve_catalog_region(a,payload=p);b,_=resolve_catalog_region(b,payload=p)
    # numeric_context deliberately carries a minimal placeholder gp_state.
    gp=Matern52GP(max_sweeps=0).fit(c.scalarization.x,c.scalarization.labels)
    before=digest_value(gp.state_dict())
    options={'settings':InformedSettings.parse({}),'trust':.5,'space':electrothermal_space_from_config(et_config())}
    assert apply_electrothermal_region(gp,c,c.pool,a,**options)==apply_electrothermal_region(gp,c,c.pool,b,**options)
    assert digest_value(gp.state_dict())==before


def test_live_response_receipt_requires_raw_evidence_even_if_flags_removed(monkeypatch,tmp_path_factory):
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    from test_region_failure_audit import _shared_initialization
    from test_electrothermal_responses_requests import successful_responses_worker,ENV
    module=feature();monkeypatch.setattr(module,'_responses_request_worker',successful_responses_worker)
    monkeypatch.setenv(ENV,'offline-responses-unit-credential')
    root=tmp_path_factory.mktemp('live_shaped_responses');cfg=_shared_initialization(root)
    cfg['llm'].update(transport='openai_responses',enabled=True,endpoint='https://provider.invalid/v1/responses',
        api_key_env=ENV,model='deepseek-v4-pro',region_wire_format='compact_v1')
    cfg['budgets']['max_llm_requests']=2
    cfg['optimization'].update(region_evidence='dynamic_decision_v3',region_proposal='catalog_v1',
        region_advice='candidate_aware_v1',region_selection='fair_region_v1')
    cfg['optimization']['region'].update(max_plain_log_ei_gap=100.,min_sigma_ratio=0.)
    # Exercise real controller/worker/ledger code; the child HTTP boundary is fake.
    run=Path(run_electrothermal_experiment(cfg,root,base_dir=root)['run_directory'])
    report=audit_electrothermal_run(run,deep=True)
    assert report['passed'],report['issues']
    assert list((run/'http').glob('*.response.json'))
    paths=[*(run/'http').glob('*'),*(run/'llm').glob('*.responses-formal.json'),
           *(run/'llm').glob('*.outcome.json'),*(run/'mo-rounds').glob('*.json'),run/'events.jsonl']
    originals={p:p.read_bytes() for p in paths}
    try:
        for p in paths:
            assert p.is_relative_to(run)
            if p.parent==run/'http' or p.name.endswith('.responses-formal.json'):p.unlink()
            elif p.name.endswith('.outcome.json'):
                value=read(p);value.update(http_request_started=False,hard_deadline_enforced=False)
                value.pop('completion',None);value.pop('response_protocol',None);put(p,value)
        for p in (run/'mo-rounds').glob('*.json'):
            value=read(p);outcome=value['region']['request_outcome']
            value['region']['request_outcome']=read(run/f'llm/{outcome["ordinal"]:06d}.outcome.json');put(p,value)
        events=[json.loads(s) for s in (run/'events.jsonl').read_text().splitlines()]
        (run/'events.jsonl').write_text('\n'.join(json.dumps(e) for e in events if not e['type'].startswith('llm_http_'))+'\n')
        assert not audit_electrothermal_run(run,deep=True)['passed']
    finally:
        for p,original in originals.items():p.write_bytes(original)
