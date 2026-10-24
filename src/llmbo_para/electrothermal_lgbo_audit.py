"""Independent reconstruction of LGBO actions and finite-Gaussian tilt algebra."""
from copy import deepcopy
from pathlib import Path
import json
import math

import numpy as np

from .acquisition import gaussian_ei
from .runstore import canonical_json
from .sobol import Sobol6
from .electrothermal_lgbo import is_lgbo_method,lgbo_prompt_filename


def _require(value, message):
    if not value:
        raise ValueError(message)


def _equal(actual, expected, message):
    _require(canonical_json(actual) == canonical_json(expected), message)


def _audit_weighted_evidence(payload, context, history):
    """Recompute from curve-verified records; do not call the request producer."""
    _require(payload.get('region_method')=='lgbo_v2','LGBO weighted context version differs')
    records={r.evaluation_id:r for r in history}
    scalar=context.scalarization
    raw=dict(zip(scalar.observation_ids,scalar.raw_labels))
    names=('F_U_V','F_T_K')
    for row in payload['history']:
        record=records[row['evaluation_id']]
        _require(record.complete_pair_valid,'LGBO weighted history lacks a complete pair')
        components=[float(w*(value/scale-z)) for value,w,scale,z in
                    zip(record.objectives,scalar.weights,scalar.objective_scales,scalar.ideal)]
        maximum=max(components)
        augmented=maximum+scalar.rho_aug*sum(components)
        expected=dict(version='weighted_tchebycheff_v1',weighted_components=components,
            max_component=maximum,active_objectives=[names[j] for j in range(2) if components[j]==maximum],
            augmented_scalar=augmented)
        _require(all(math.isfinite(v) for v in [*components,augmented]),'LGBO weighted evidence is nonfinite')
        _equal(row.get('weighted_objective_evidence'),expected,'LGBO weighted objective evidence differs')
        _require(math.isclose(augmented,raw[record.evaluation_id],rel_tol=1e-14,abs_tol=1e-15),
                 'LGBO weighted evidence differs from frozen scalar label')


def _independent_tilt(gp, context, response, outcome, space, *, region_method='lgbo_v1'):
    """Re-derive the published covariance rule without calling the product tilt."""
    _require(is_lgbo_method(region_method),'unknown LGBO method')
    pool = np.asarray(context.pool)
    mean, std = gp.predict(pool)
    ei = gaussian_ei(mean, std, context.scalarization.best)
    plain = int(np.argmax(ei))
    result = dict(region_method=region_method, context_id=context.context_id,
        mean=mean.tolist(), std=std.tolist(), plain_ei=ei.tolist(),
        signed_delta=np.zeros(len(pool)).tolist(), adjusted_mean=mean.tolist(),
        effective_ei=ei.tolist(), plain_index=plain, selected_index=plain,
        action_valid=False, tilt_applied=False, selection_changed=False, accepted=False,
        fallback_reason=None, response=deepcopy(response), request_outcome=deepcopy(outcome))
    if response is None:
        result['fallback_reason'] = 'no_response'
        return result
    # Actions below have already been independently decoded from the wire.
    region = response['region']
    result['action_valid'] = True
    if region['kind'] == 'none':
        result['fallback_reason'] = 'abstained'
        return result
    confidence = region['confidence']
    if confidence == 0:
        result['fallback_reason'] = 'zero_confidence'
        return result
    lo, hi = np.asarray(region['lb']), np.asarray(region['ub'])
    samples = lo+(hi-lo)*Sobol6(1+32*(context.ordinal-1)).draw(32)
    keep = []
    for point in samples:
        try:
            space.denormalize(point)
            keep.append(True)
        except ValueError:
            keep.append(False)
    anchors = samples[np.asarray(keep)]
    result.update(sampled_anchors=samples.tolist(), anchor_feasible_mask=keep,
                  anchors=anchors.tolist())
    if not len(anchors):
        result['fallback_reason'] = 'no_feasible_anchors'
        return result
    covariance = gp.posterior_covariance(anchors)
    cross = gp.posterior_covariance(pool, anchors)
    weights = np.full(len(anchors), 1/len(anchors))
    variance = float(weights @ covariance @ weights)
    if not np.all(np.isfinite(covariance)) or not np.all(np.isfinite(cross)):
        result['fallback_reason'] = 'invalid_posterior'
        return result
    if variance <= 1e-12:
        result['fallback_reason'] = 'negative_region_variance' if variance < -1e-12 else 'degenerate_region_variance'
        return result
    lam = confidence/math.sqrt(variance)
    delta = lam*(cross @ weights)
    adjusted = mean-delta
    lifted = gaussian_ei(adjusted, std, context.scalarization.best)
    selected = int(np.argmax(lifted))
    result.update(region_variance=variance, **{'lambda': lam},
        anchor_weights=weights.tolist(), signed_delta=delta.tolist(), adjusted_mean=adjusted.tolist(),
        effective_ei=lifted.tolist(), selected_index=selected,
        tilt_applied=bool(np.any(delta != 0)), selection_changed=selected != plain,
        accepted=selected != plain)
    return result


def audit_lgbo_round(root, *, event, context, gp, history, prepared, cost_events):
    """Bind raw responses to past-only requests, then independently audit selection."""
    from .electrothermal_llm import build_electrothermal_payload
    from .electrothermal_lgbo_wire import decode_lgbo_action
    from .electrothermal_region_wire import region_wire_payload
    from .electrothermal_json import decode_archived_http_response, archival_json
    from .electrothermal_requests import request_controls
    root = Path(root)
    def read(relative):
        return json.loads((root/relative).read_text(encoding='utf-8'))
    cfg = prepared.config
    _require(cfg['optimization']['mode'] == 'full_llmbo_mo', 'LGBO round outside Full mode')
    _require('trust' not in event['feedback'], 'LGBO must not update legacy trust')
    saved = event['region']; outcome = saved.get('request_outcome')
    _require(isinstance(outcome, dict) and outcome.get('context_id') == context.context_id,
             'LGBO request outcome has wrong frozen context')
    references = []
    canonical = None
    if 'ordinal' not in outcome:
        _require(outcome.get('status') == 'skipped' and outcome.get('reason') in
            ('disabled', 'global_budget', 'task_budget', 'missing_credential', 'missing_mock_transport'),
            'invalid LGBO skip; no inactivity or eligible gate exists')
    else:
        n = outcome['ordinal']
        _require(type(n) is int and n >= 0 and outcome.get('status') in ('received', 'failed'),
                 'invalid LGBO request ordinal/status')
        references.append(n)
        _equal(read(f'llm/{n:06d}.outcome.json'), outcome, 'LGBO outcome archive differs')
        expected = build_electrothermal_payload('region_preference_electrothermal',
            prepared=prepared, history=history, context=context)
        expected['instructions'] = (root/'source/src/llmbo_para/prompts'/lgbo_prompt_filename(cfg['optimization']['region_method'])).read_text(encoding='utf-8')
        expected['artifact_task'] = expected['task']+'_request_'+'a'*(n+1)
        expected = json.loads(canonical_json(expected))
        payload = read(f'llm/{n:06d}.payload.json')
        if cfg['optimization']['region_method']=='lgbo_v2':
            _audit_weighted_evidence(payload,context,history)
        _equal(payload, expected, 'LGBO past-only request or dynamic evidence differs')
        _require(cost_events.get(f'llm:{n}', {}).get('phase') == expected['task'],
                 'LGBO request lacks cost reference')
        artifact = expected['artifact_task']
        http_request = root/'http'/f'{artifact}.request.json'
        http_response = root/'http'/f'{artifact}.response.json'
        supervision_path = root/'http'/f'{artifact}.supervision.json'
        supervision = read(f'http/{artifact}.supervision.json') if supervision_path.exists() else {}
        # Completion/parse evidence is emitted only after the transport saved
        # the provider's JSON reply. A failed status must not erase that proof.
        # A request or failure_stage alone is insufficient: malformed HTTP JSON,
        # connection errors and worker startup can fail before this archive exists.
        decoded_http = any(key in evidence for evidence in (outcome, supervision)
                           for key in ('completion', 'protocol_issue')) or (
                               root/'http'/f'{artifact}.parse-error.json').exists()
        _require(not decoded_http or http_response.is_file(),
                 'LGBO decoded HTTP response archive is missing')
        receipt = root/f'llm/{n:06d}.lgbo-response.json'
        mutation = root/f'llm/{n:06d}.lgbo-mutation.json'
        if http_request.exists():
            _equal(outcome.get('wire_format'), 'lgbo_action_v1', 'LGBO supervised wire marker differs')
            body = read(f'http/{artifact}.request.json')['body']
            wire = region_wire_payload(expected)
            controls = request_controls(cfg, expected['task'])
            if cfg['llm'].get('transport') == 'openai_responses':
                from .electrothermal_responses import responses_request_body
                _equal(body, responses_request_body(wire, model=cfg['llm']['model'],
                    max_tokens=controls['max_tokens'], json_mode=cfg['llm']['json_mode'],
                    reasoning_effort=controls.get('reasoning_effort')),
                    'LGBO Responses request differs')
            else:
                target = {'model': cfg['llm']['model'], 'max_tokens': controls['max_tokens'], 'stream': False}
                for key, value in target.items():
                    _equal(body.get(key), value, 'LGBO Chat control differs: '+key)
                messages = body['messages']
                _require(len(messages) == 2 and messages[0]['role'] == 'system' and messages[1]['role'] == 'user',
                         'LGBO Chat message structure differs')
                from .electrothermal_responses import JSON_INSTRUCTIONS
                instructions = wire['instructions']+(JSON_INSTRUCTIONS if cfg['llm']['json_mode'] else '')
                _equal(messages[0]['content'], instructions, 'LGBO Chat prompt differs')
                _equal(json.loads(messages[1]['content']), {k: v for k, v in wire.items() if k != 'instructions'},
                       'LGBO Chat scientific content differs')
        if http_response.exists():
            decoded, issue = decode_archived_http_response(read(f'http/{artifact}.response.json'),
                payload=expected, transport=cfg['llm'].get('transport', 'openai_chat_completions'))
            if issue is None:
                _require(receipt.exists(), 'LGBO valid HTTP response lacks controller receipt')
                raw = read(f'llm/{n:06d}.lgbo-response.json')
                _equal(raw, {'version': 'lgbo_response_v1', 'representation': 'canonical',
                             'response_json': archival_json(decoded)}, 'LGBO native receipt differs')
                canonical = decoded
            else:
                _require(outcome['status'] == 'failed' and outcome.get('reason') == 'protocol_error'
                         and not receipt.exists(), 'LGBO unfinished/invalid HTTP action was accepted')
        elif receipt.exists():
            _require(not http_request.exists(), 'LGBO native receipt has no raw HTTP response')
            raw = read(f'llm/{n:06d}.lgbo-response.json')
            _require(raw.get('version') == 'lgbo_response_v1' and raw.get('representation') == 'wire',
                     'invalid LGBO injected-wire receipt')
            try:
                canonical = decode_lgbo_action(json.loads(raw['response_json']), expected)
            except (ValueError, TypeError, KeyError, OverflowError):
                _require(outcome['status'] == 'failed' and outcome.get('reason') == 'invalid_lgbo_response',
                         'LGBO invalid injected action was accepted')
        else:
            _require(outcome['status'] == 'failed', 'LGBO received outcome lacks raw reply evidence')
        if mutation.exists():
            changed = json.loads(read(f'llm/{n:06d}.lgbo-mutation.json')['sent_payload_json'])
            _require(canonical_json(changed) != canonical_json(expected), 'false LGBO mutation evidence')
            _require(outcome['status'] == 'failed' and outcome.get('reason') == 'invalid_lgbo_response',
                     'mutated LGBO request was accepted')
            canonical = None
        if canonical is not None:
            _require(outcome['status'] == 'received', 'valid LGBO action has unexplained failure')
    _equal(saved.get('response'), canonical, 'LGBO action differs from original wire')
    expected_region = _independent_tilt(gp, context, canonical, outcome, prepared.space,
                                       region_method=cfg['optimization']['region_method'])
    _require(set(saved) == set(expected_region), 'LGBO decision fields differ')
    numeric = {'mean', 'std', 'plain_ei', 'signed_delta', 'adjusted_mean', 'effective_ei',
               'sampled_anchors', 'anchors', 'anchor_weights', 'region_variance', 'lambda'}
    for key, value in expected_region.items():
        if key in numeric:
            actual_array, expected_array = np.asarray(saved[key], dtype=float), np.asarray(value, dtype=float)
            _require(actual_array.shape == expected_array.shape and np.all(np.isfinite(actual_array))
                     and np.allclose(actual_array, expected_array, rtol=1e-11, atol=1e-12),
                     'independent LGBO formula differs: '+key)
        else:
            _equal(saved[key], value, 'LGBO decision differs: '+key)
    return {'expected_region': expected_region, 'selected_index': expected_region['selected_index'],
            'request_ordinals': references}
