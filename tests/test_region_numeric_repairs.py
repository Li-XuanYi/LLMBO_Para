"""Region geometry/horizon regressions using software observations and real GPs."""
from dataclasses import replace
from types import SimpleNamespace


def test_nominal_minimum_width_reaches_posterior_covariance(tmp_path, monkeypatch):
    from llmbo_para.electrothermal_llm import apply_electrothermal_region
    from llmbo_para.informed import InformedSettings
    from test_electrothermal_region import context_fixture, response

    optimizer, prepared, context = context_fixture(tmp_path)
    reply = response(context)
    reply['region'].update(lb=[.27] * 6, ub=[.30] * 6)
    # These decimal bounds express the inclusive minimum width. Their binary
    # difference is 0.02999999999999997, which must not invalidate the box.
    calls = []
    original = optimizer.gp.posterior_covariance

    def tracked(left, right=None):
        calls.append((len(left), None if right is None else len(right)))
        return original(left, right)

    monkeypatch.setattr(optimizer.gp, 'posterior_covariance', tracked)
    result = apply_electrothermal_region(
        optimizer.gp, context, context.pool, reply,
        settings=InformedSettings(), trust=.5, space=prepared.space,
    )
    assert result['fallback_reason'] != 'invalid_width'
    assert result['anchors']
    assert len(calls) == 2


def test_inactive_region_makes_no_request_and_records_inactive(tmp_path):
    from test_mo_optimizer import make_optimizer

    optimizer = make_optimizer(tmp_path)
    optimizer.options['mode'] = 'full_llmbo_mo'
    optimizer.region_settings = replace(optimizer.region_settings, active_until=1)

    def forbidden_request(*args, **kwargs):
        raise AssertionError('inactive Region must not issue a transport request')

    optimizer.llm_controller = SimpleNamespace(
        prepared=object(), request_region=forbidden_request,
    )
    event = optimizer.step()
    assert event['context']['ordinal'] == optimizer.region_settings.active_until
    assert event['region']['fallback_reason'] == 'inactive'
    assert not event['region']['accepted']
    assert event['selected_index'] == event['region']['plain_index']
