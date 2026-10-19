"""A self-consistent edited summary must not hide missing Region evidence."""
from collections import Counter
import json
from pathlib import Path

import pytest


def synchronize_summary(root):
    events = [json.loads(f.read_text(encoding='utf8')) for f in sorted((root/'mo-rounds').glob('*.json'))]
    regions = [e['region'] for e in events if e['region'] is not None]
    outcomes = [r.get('request_outcome') or {} for r in regions]
    diagnostics = {'rounds':len(regions),'request_attempts':sum('ordinal' in o for o in outcomes),
        'responses':sum(o.get('status')=='received' or not o and r['response'] is not None for r,o in zip(regions,outcomes)),
        'accepted':sum(r['accepted'] for r in regions),'request_failures':sum(o.get('status')=='failed' for o in outcomes),
        'fallback_counts':dict(Counter(r['fallback_reason'] for r in regions if r['fallback_reason'] is not None))}
    file = root/'electrothermal-summary.json'
    summary = json.loads(file.read_text(encoding='utf8'))
    summary['region_diagnostics'] = diagnostics
    file.write_text(json.dumps(summary), encoding='utf8')
    file = root/'terminal.json'
    terminal = json.loads(file.read_text(encoding='utf8'))
    terminal['summary'] = summary
    file.write_text(json.dumps(terminal), encoding='utf8')


def test_deleting_whole_region_cannot_bypass_precheck_audit(tmp_path, monkeypatch):
    from test_region_failure_audit import _shared_initialization
    from llmbo_para.mo_optimizer import MOOptimizer
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    cfg = _shared_initialization(tmp_path)
    cfg['optimization']['region_advice'] = 'candidate_aware_v1'
    original = MOOptimizer.candidate_pool
    monkeypatch.setattr(MOOptimizer, 'candidate_pool', lambda self, center: original(self, center)[:1])
    class Forbidden:
        def post(self, payload): pytest.fail('zero alternative must skip')
    result = run_electrothermal_experiment(cfg, tmp_path, base_dir=tmp_path,
        llm_controller=ElectrothermalLLMController(transport=Forbidden(), is_mock=True))
    root = Path(result['run_directory'])
    assert audit_electrothermal_run(root, deep=True)['passed']
    for file in (root/'mo-rounds').glob('*.json'):
        event = json.loads(file.read_text(encoding='utf8'))
        event['region'] = None
        event['feedback'].pop('trust')
        file.write_text(json.dumps(event), encoding='utf8')
    synchronize_summary(root)
    audit = audit_electrothermal_run(root, deep=True)
    assert not audit['passed'], 'whole Region deletion must fail independently of summary consistency'


def test_unknown_request_status_cannot_be_replayed_as_valid(tmp_path):
    from test_region_candidate_advice import candidate_run
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    root = candidate_run(tmp_path)
    file = next((root/'mo-rounds').glob('*.json'))
    event = json.loads(file.read_text(encoding='utf8'))
    outcome = event['region']['request_outcome']
    outcome['status'] = 'invented'
    file.write_text(json.dumps(event), encoding='utf8')
    (root/'llm'/f"{outcome['ordinal']:06d}.outcome.json").write_text(json.dumps(outcome), encoding='utf8')
    synchronize_summary(root)
    assert not audit_electrothermal_run(root, deep=True)['passed']


def test_apply_rejects_pool_different_from_frozen_advice_context(tmp_path):
    from test_region_candidate_advice import real_context
    from test_electrothermal_region import response
    from llmbo_para.electrothermal_llm import apply_electrothermal_region
    from llmbo_para.informed import InformedSettings
    opt, prepared, context = real_context(tmp_path)
    with pytest.raises(ValueError, match='pool'):
        apply_electrothermal_region(opt.gp, context, context.pool[:1], response(context),
            settings=InformedSettings(), trust=.5, space=prepared.space, advice_mode='candidate_aware_v1')


@pytest.mark.parametrize('mean', [[10.,11.,12.], [100.,100.,100.]])
def test_reading_ratio_is_actual_ratio_or_explicitly_undefined(tmp_path, monkeypatch, mean):
    from test_region_candidate_advice import advice_fixture
    from llmbo_para.electrothermal_region_advice import build_region_candidate_advice
    prepared, context, settings = advice_fixture(tmp_path, monkeypatch, mean=mean)
    advice = build_region_candidate_advice(context, space=prepared.space, settings=settings)
    plain = advice['candidates'][0]
    assert plain['relative_plain_ei'] == (1. if plain['plain_ei'] > 0 else None)
    # Ratios are display information; the floored guard stays unchanged.
    assert advice['eligible_alternative_count'] == 2
