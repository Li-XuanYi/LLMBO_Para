"""Software-only LGBO requests backed by real archived-format evaluations."""
import json
from dataclasses import asdict

from electrothermal_fixtures import et_config


def lgbo_config():
    cfg = et_config(('0.5C', '1C'))
    cfg['optimization'].pop('region')
    cfg['optimization']['region_method'] = 'lgbo_v1'
    return cfg


def prepared_request(tmp_path):
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from llmbo_para.electrothermal_synthetic import SyntheticElectrothermalSimulator
    from llmbo_para.electrothermal_llm import build_electrothermal_payload
    from llmbo_para.scalarization import build_scalarization_context
    from llmbo_para.mo_optimizer import MORoundContext
    from llmbo_para.runstore import digest_value
    cfg = lgbo_config()
    report, prepared = prepare_electrothermal_experiment(cfg, base_dir=tmp_path)
    assert prepared is not None, report['errors']
    ev = ElectrothermalEvaluator(prepared.space, SyntheticElectrothermalSimulator(),
                                 fit_rates=prepared.dataset.fit_rates)
    rows = [ev.evaluate(prepared.space.denormalize([v]*6), prepared.dataset) for v in (.2, .8)]
    scalar = build_scalarization_context(
        [prepared.space.normalize(r.parameters) for r in rows], [r.objectives for r in rows],
        [r.evaluation_id for r in rows], weights=(.8, .2), objective_scales=(.1, 1.),
        rho_aug=.05, protocol_signature=prepared.signatures.comparison_protocol)
    fields = dict(scalarization=scalar.to_dict(), fit_rates=prepared.dataset.fit_rates,
                  signatures=asdict(prepared.signatures), gp_state={}, pool=((.1,)*6, (.55,)*6), ordinal=13)
    context = MORoundContext(scalar, prepared.dataset.fit_rates, json.dumps(fields['signatures']),
                            '{}', fields['pool'], 13, digest_value(fields))
    payload = build_electrothermal_payload('region_preference_electrothermal',
        prepared=prepared, history=rows, context=context)
    return prepared, rows, context, payload


def region_action(payload, *, kind='region', confidence=.65):
    from llmbo_para.electrothermal_lgbo_wire import lgbo_request_id
    region = {'kind': kind}
    if kind == 'region':
        region.update(lb=[.3]*6, ub=[.8]*6, confidence=confidence)
    return {'request_id': lgbo_request_id(payload), 'region': region}
