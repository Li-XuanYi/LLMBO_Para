"""Archived replies are replay evidence, not new language-model API results."""
import copy
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from llmbo_para.config import configuration_errors
from llmbo_para.runstore import sha256_file
from llmbo_para.synthetic import synthetic_config


def replay_class():
    assert importlib.util.find_spec("llmbo_para.llm_replay") is not None, "explicit group replay is not implemented"
    from llmbo_para.llm_replay import ArchivedGroupTransport
    return ArchivedGroupTransport


def make_packet(root, request, response):
    req=root/'original-request.json';rsp=root/'original-response.json'
    req.write_text(json.dumps(request),encoding='utf8');rsp.write_text(json.dumps(response),encoding='utf8')
    packet={'schema_version':1,'source_kind':'synthetic_software_fixture','task':'rate_parameter_groups',
        'model':'fixture','source_request':request,'source_response':response,
        'source_files':[{'path':str(p),'sha256':sha256_file(p)} for p in (req,rsp)]}
    file=root/'reply.json';file.write_text(json.dumps(packet,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    return {'path':str(file),'sha256':sha256_file(file)}


def test_replay_requires_signature_and_preserves_exact_response(tmp_path):
    Replay=replay_class()
    from llmbo_para.llm import LLMClient
    from llmbo_para.config import parameter_space_from_config
    space=parameter_space_from_config(synthetic_config())
    class Capture:
        def post(self,payload):
            self.payload=copy.deepcopy(payload)
            return {'groups':{r:[space.specs[0].name] for r in payload['rates']}}
    capture=Capture();original=LLMClient(capture).parameter_groups(space,[])
    evidence=make_packet(tmp_path,capture.payload,{'groups':{r:list(v) for r,v in original.items()}})
    replay=Replay(evidence,expected_model='fixture')
    assert LLMClient(replay).parameter_groups(space,[]) == original
    altered=copy.deepcopy(capture.payload);altered['observations']=[{'parameters':[1]*6}]
    with pytest.raises(ValueError,match='signature'):
        replay.post(altered)
    with pytest.raises(ValueError,match='task'):
        replay.post({'task':'warm_start'})
    Path(evidence['path']).write_text('{}',encoding='utf8')
    with pytest.raises(ValueError,match='hash'):
        Replay(evidence,expected_model='fixture')


def test_archived_reply_workflow_needs_no_live_credential_or_http(tmp_path):
    replay_class()
    from test_bo_repair import setup_problem,artificial_simulator
    from llmbo_para.workflow import run_experiment,prepare_experiment
    from llmbo_para.audit import audit_run
    config,space,_=setup_problem()
    config['optimization'].update(llm_enabled=True,llm_gp_groups_enabled=True,llm_warm_start_enabled=False,
        bo_repair={'training_data':'per_rate'},total_candidate_budget=5)
    config['llm'].update(transport='structured_json_service',endpoint='https://example.test/json',
        api_key_env='FG_REPLAY_TEST_KEY',model='fixture',timeout_s=30)
    def response(transport,payload):
        return {'groups':{r:[space.specs[0].name] for r in payload['rates']}}
    with patch.dict('os.environ',{'FG_REPLAY_TEST_KEY':'synthetic-test-only'}),patch('llmbo_para.llm.HttpJsonTransport.post',response):
        original=run_experiment(config,tmp_path/'original',simulator=artificial_simulator(space,all_valid=True))
    run=Path(original['run_directory'])
    evidence=make_packet(tmp_path,json.loads((run/'llm/rate_parameter_groups.request.json').read_text(encoding="utf-8")),
        json.loads((run/'llm/rate_parameter_groups.response.json').read_text(encoding="utf-8")))
    config['llm']['parameter_groups_replay']=evidence
    assert configuration_errors(config)==[]
    with patch.dict('os.environ',{'FG_REPLAY_TEST_KEY':''}),patch('llmbo_para.llm.HttpJsonTransport.post',side_effect=AssertionError('unexpected live HTTP')):
        report,prepared=prepare_experiment(config)
        assert report['ready'],report['errors']
        replayed=run_experiment(config,tmp_path/'replayed',simulator=artificial_simulator(space,all_valid=True))
    assert replayed['best_objective_v']==original['best_objective_v']
    target=Path(replayed['run_directory'])
    assert audit_run(target,deep=True)['passed']
    events=[json.loads(line) for line in (target/'events.jsonl').read_text(encoding="utf-8").splitlines()]
    assert sum(e['type']=='llm_archived_reply_replayed' for e in events)==1
    assert not any(e['type']=='llm_http_started' for e in events)
    assert (target/'inputs/parameter-groups-replay.json').exists()
    # The self-contained audit must not require the old source files after copying.
    Path(evidence['path']).unlink()
    assert audit_run(target,deep=True)['passed']


def test_packet_cannot_replace_the_verified_original_reply(tmp_path):
    Replay = replay_class()
    request = {"task": "rate_parameter_groups", "observations": []}
    response = {"groups": {"0.5C": [], "1C": [], "2C": [], "3C": []}}
    evidence = make_packet(tmp_path, request, response)
    file = Path(evidence["path"])
    packet = json.loads(file.read_text(encoding="utf-8"))
    packet["source_response"]["groups"]["3C"] = ["fabricated group"]
    file.write_text(json.dumps(packet), encoding="utf-8")
    evidence["sha256"] = sha256_file(file)
    with pytest.raises(ValueError, match="original|content"):
        Replay(evidence, expected_model="fixture")
