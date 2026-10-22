"""Direct LGBO actions, bound to the complete immutable internal request."""
from copy import deepcopy
import json

from .electrothermal_lgbo import is_lgbo_method, validate_lgbo_region
from .runstore import canonical_json, digest_value

WIRE_VERSION = 'lgbo_action_v1'
TASK = 'region_preference_electrothermal'
IDENTITIES = ('schema_version', 'parameter_profile', 'fit_rates', 'signatures',
              'context_id', 'region_method')


def lgbo_region_contract():
    bounds = {'type': 'array', 'minItems': 6, 'maxItems': 6,
              'items': {'type': 'number', 'minimum': 0, 'maximum': 1}}
    action = {'kind': {'const': 'region'}, 'lb': bounds, 'ub': deepcopy(bounds),
              'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1}}
    return {'oneOf': [
        {'type': 'object', 'additionalProperties': False, 'required': ['kind'],
         'properties': {'kind': {'const': 'none'}}},
        {'type': 'object', 'additionalProperties': False, 'required': list(action),
         'properties': action}]}


def lgbo_request_id(payload):
    if (payload.get('task') != TASK or not is_lgbo_method(payload.get('region_method'))
            or 'request_id' in payload or any(k not in payload for k in IDENTITIES)):
        raise ValueError('complete internal LGBO request required')
    return digest_value({'wire_version': WIRE_VERSION,
                         'request': {k: v for k, v in payload.items() if k != 'artifact_task'}})


def lgbo_wire_payload(payload):
    binding = lgbo_request_id(payload)
    wire = deepcopy(payload)
    wire.pop('signatures')
    wire['request_id'] = binding
    wire['response_contract'] = {
        'type': 'object', 'additionalProperties': False,
        'required': ['request_id', 'region'],
        'properties': {'request_id': {'const': binding}, 'region': lgbo_region_contract()}}
    return wire


def decode_lgbo_action(response, payload):
    if (type(response) is not dict or set(response) != {'request_id', 'region'}
            or type(response['request_id']) is not str
            or response['request_id'] != lgbo_request_id(payload)):
        raise ValueError('stale or invalid LGBO request binding')
    # Host dataclasses contain tuples; only trusted identities are normalized.
    # The model's region remains untouched for the strict native JSON check.
    canonical = json.loads(canonical_json({k: payload[k] for k in IDENTITIES}))
    canonical['region'] = deepcopy(response['region'])
    validate_lgbo_region(canonical, expected_context_id=payload['context_id'],
                         expected_signatures=payload['signatures'],expected_region_method=payload['region_method'])
    return canonical
