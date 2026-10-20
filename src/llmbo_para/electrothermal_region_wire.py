"""Optional compact Region exchange bound to the complete frozen request.

Only transport representation changes. The optimizer still receives the strict
v2 envelope, with all identities copied from its immutable local request after
checking the returned binding. Old wire replies and cache validation are intact.
"""
from copy import deepcopy
from .runstore import digest_value

FORMATS=('full_v1','compact_v1')
TASK='region_preference_electrothermal'
ENVELOPE=('schema_version','parameter_profile','fit_rates','signatures','context_id')

def region_wire_format(config):
    if not isinstance(config,dict) or not isinstance(config.get('llm'),dict):raise ValueError('llm must be an object')
    value=config['llm'].get('region_wire_format','full_v1')
    if value not in FORMATS:raise ValueError('invalid Region wire format')
    return value

def _compact(payload):
    mode=payload.get('region_wire_format','full_v1')
    if mode not in FORMATS:raise ValueError('invalid Region wire format')
    return payload.get('task')==TASK and mode=='compact_v1'

def _binding(payload):
    # Include weights, scales, history, physical semantics, signatures and pool
    # advice, not just the dimension or a model-provided context identifier.
    return digest_value({'wire_version':'region_compact_v1',
        'request':{k:v for k,v in payload.items() if k!='artifact_task'}})

def region_wire_payload(payload):
    if not _compact(payload):return deepcopy(payload)
    if any(k not in payload for k in ENVELOPE):raise ValueError('complete frozen Region envelope required')
    wire=deepcopy(payload);wire.pop('signatures')
    wire['request_id']=_binding(payload)
    wire['response_contract']={'type':'object','additionalProperties':False,'required':['request_id','region'],
        'properties':{'request_id':{'const':wire['request_id']},'region':deepcopy(payload['response_contract']['properties']['region'])}}
    wire['instructions']+='\nFor this compact exchange, return only request_id and region as specified by response_contract. Copy request_id exactly; identities are checked locally.'
    return wire

def decode_region_wire(response,payload):
    if not _compact(payload):return response
    if not isinstance(response,dict) or set(response)!={'request_id','region'} or response['request_id']!=_binding(payload):
        raise ValueError('stale or invalid compact Region binding')
    return {**{k:deepcopy(payload[k]) for k in ENVELOPE},'region':deepcopy(response['region'])}
