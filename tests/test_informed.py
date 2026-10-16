"""Scientific invariants for LLM regional guidance and its offline audit."""
from dataclasses import asdict, replace
from pathlib import Path
import copy
import json

import numpy as np
import pytest

from llmbo_para.audit import audit_run
from llmbo_para.config import configuration_errors, parameter_space_from_config
from llmbo_para.informed import InformedSettings, region_decision, validate_region_response, trust_feedback
from llmbo_para.llm import LLMClient
from llmbo_para.metrics import LogRMSETransform
from llmbo_para.runstore import RunStore
from llmbo_para.surrogate import Matern52GP
from llmbo_para.workflow import run_experiment
from test_single_objective import scalar_config


def preference(lo=.3, hi=.7):
    return dict(kind="region",coordinate_space="normalized",lb=[lo]*6,ub=[hi]*6,confidence=.8,reason="fixture regional preference")


class RegionTransport:
    def __init__(self, mode="region"):
        self.mode, self.calls = mode, []

    def post(self, payload):
        self.calls.append(copy.deepcopy(payload))
        if self.mode == "error":
            raise RuntimeError("fixture unavailable")
        if self.mode == "malformed_content":
            return {"content":"not JSON"}
        if self.mode == "invalid" or self.mode == "repair" and len(self.calls) % 2:
            return {**preference(), "lb":[0.1]*5}
        if self.mode == "none":
            return dict(kind="none",coordinate_space="normalized",confidence=0.,reason="fixture abstention")
        return preference()


def informed_config():
    config = scalar_config()
    config["optimization"].update(llm_enabled=True,llm_informed_enabled=True,
        llm_informed=asdict(InformedSettings(active_until=3)))
    config["llm"].update(endpoint="https://api.example.test/v1",api_key_env="LLMBO_TEST_REGION_KEY",model="fixture-region-model")
    return config


def execute(tmp_path, monkeypatch, mode="region", enabled=True):
    config = informed_config() if enabled else scalar_config()
    transport = RegionTransport(mode)
    monkeypatch.setenv("LLMBO_TEST_REGION_KEY", "fixture-key-not-a-secret")
    monkeypatch.setattr("llmbo_para.workflow.build_llm", lambda c,s,**kw: LLMClient(transport,run_store=s) if enabled else None)
    result = run_experiment(config,tmp_path,command="informed deterministic fixture")
    return result, transport


def test_posterior_covariance_is_conditioned_latent_psd_and_matches_variance():
    rng=np.random.default_rng(3)
    x=rng.random((8,6)); q=rng.random((10,6))
    gp=Matern52GP(max_sweeps=3).fit(x,np.sin(x[:,0]*3))
    cov=gp.posterior_covariance(q)
    np.testing.assert_allclose(cov,cov.T,atol=1e-13)
    assert np.linalg.eigvalsh(cov).min() > -1e-10
    np.testing.assert_allclose(cov.diagonal(),gp.predict(q)[1]**2,atol=1e-12)
    np.testing.assert_allclose(gp.posterior_covariance(q[:3],q[3:]),cov[:3,3:],atol=1e-12)
    assert np.mean(gp.posterior_covariance(x).diagonal()) < np.mean(cov.diagonal())


@pytest.mark.parametrize("change",[{"lb":[.1]*5},{"confidence":True},{"coordinate_space":"raw"},{"ub":[float("nan")]*6},{"lb":[.8]*6},{"extra":0}])
def test_no_silent_schema_repair_or_default_parameters(change):
    with pytest.raises(ValueError): validate_region_response({**preference(),**change})


def test_shift_can_change_selection_without_changing_gp_or_variance():
    # A PSD kernel fixture isolates the acquisition mechanism: point 0 starts
    # with a slightly better mean; point 1 correlates with the suggested region.
    class GP:
        x=np.full((2,6),.05)
        def predict(self,x):
            return .01*np.asarray(x)[:,0],np.full(len(x),.5)
        def posterior_covariance(self,a,b=None):
            a=np.asarray(a); b=a if b is None else np.asarray(b)
            return .25*np.exp(-np.sum((a[:,None]-b[None,:])**2,axis=2)/.04)
    space=parameter_space_from_config(scalar_config())
    pool=np.array([[.1]*6,[.55]*6])
    settings=replace(InformedSettings(),min_sigma_ratio=0.,max_plain_log_ei_gap=1.)
    args=dict(space=space,settings=settings,trust=1.,iteration=0,seed=4,candidate_id=2)
    gp=GP(); transform=LogRMSETransform(-3,1)
    before=gp.predict(pool)
    decision=region_decision(gp,transform,.06,pool,[True,True],preference(.4,.7),**args)
    assert decision["accepted"] and decision["plain_index"]==0 and decision["selected_index"]==1
    assert np.max(decision["shift_z"])<=settings.max_shift_std
    assert np.min(decision["shift_z"])>=0
    np.testing.assert_array_equal(decision["std_z"],before[1])
    np.testing.assert_array_equal(gp.predict(pool)[0],before[0])
    restricted=region_decision(gp,transform,.06,pool,[True,False],preference(.4,.7),**args)
    assert restricted["selected_index"]==0 and not restricted["accepted"]
    inactive=region_decision(gp,transform,.06,pool,[True,True],preference(),**{**args,"iteration":12})
    assert inactive["fallback_reason"]=="inactive"
    no_strength=region_decision(gp,transform,.06,pool,[True,True],preference(),**{**args,"trust":0.})
    assert no_strength["selected_index"]==0


def test_informed_config_and_feedback_are_explicit():
    config=informed_config()
    assert not configuration_errors(config)
    for bad in ({"llm_enabled":False},{"surrogate_mode":"per_rate"},{"llm_informed":{"n_anchors":True}},{"llm_informed":{"typo":1}}):
        c=copy.deepcopy(config); c["optimization"].update(bad)
        assert configuration_errors(c)
    s=InformedSettings()
    assert trust_feedback(.5,False,True,.01,.02,s)["trust_after"]==.5
    assert trust_feedback(.5,True,False,None,.02,s)["trust_after"]==.4
    assert trust_feedback(.5,True,True,.01,.02,s)["trust_after"]==pytest.approx(.6)


@pytest.mark.parametrize("mode",["region","repair","none","invalid","error","malformed_content"])
def test_full_workflow_archives_all_calls_fallbacks_and_replays(tmp_path,monkeypatch,mode):
    result,transport=execute(tmp_path,monkeypatch,mode)
    root=Path(result["run_directory"])
    assert audit_run(root,deep=True)["passed"]
    stats=result["llm_informed"]
    assert stats["requested_iterations"]==3
    assert stats["request_attempts"]==len(transport.calls)
    assert all(p["task"]=="region_preference" for p in transport.calls)
    assert stats["fallback_counts"]["inactive"]==2
    if mode in {"error","invalid","malformed_content"}:
        assert stats["error_iterations"]==3 and stats["adopted"]==0
    if mode=="repair": assert stats["request_attempts"]==6
    text=json.dumps(transport.calls)
    assert "simulation_voltage_v" not in text and "aligned_voltage_v" not in text
    assert transport.calls[0]["bounds"][2][0]==1e-16
    assert all(len(r["parameters_normalized"])==6 for r in transport.calls[0]["observations"])
    if mode=="region":
        artifact=sorted((root/"informed").glob("*.json"))[0]
        row=json.loads(artifact.read_text()); row["decision"]["mean_z"][0]+=.1
        artifact.write_text(json.dumps(row))
        assert not audit_run(root,deep=True)["passed"]


def test_disabled_module_and_abstention_match_plain_single_gp(tmp_path,monkeypatch):
    plain,_=execute(tmp_path/"plain",monkeypatch,enabled=False)
    none,transport=execute(tmp_path/"none",monkeypatch,mode="none")
    a=Path(plain["run_directory"]); b=Path(none["run_directory"])
    assert not (a/"informed").exists()
    for pa,pb in zip(sorted((a/"plans").glob("*.json")),sorted((b/"plans").glob("*.json"))):
        assert json.loads(pa.read_text())==json.loads(pb.read_text())
    assert plain["best_objective_v"]==none["best_objective_v"]


def test_fixed_candidate_replay_disables_informed_without_credentials(tmp_path,monkeypatch):
    from llmbo_para.workflow import run_fixed_candidates
    config=informed_config()
    space=parameter_space_from_config(config)
    monkeypatch.delenv("LLMBO_TEST_REGION_KEY",raising=False)
    result=run_fixed_candidates(config,tmp_path,[(None,space.denormalize([.5]*6))],mode="smoke")
    root=Path(result["run_directory"])
    assert audit_run(root,deep=True)["passed"]
    assert json.loads((root/"original-config.json").read_text())["optimization"]["llm_informed_enabled"]
    assert not json.loads((root/"manifest.json").read_text())["config"]["optimization"]["llm_informed_enabled"]
