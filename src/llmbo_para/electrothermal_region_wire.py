"""Optional compact Region exchange bound to the complete frozen request.

Only transport representation changes. The optimizer still receives the strict
v2 envelope, with all identities copied from its immutable local request after
checking the returned binding. Old wire replies and cache validation are intact.
"""
from copy import deepcopy
from .runstore import digest_value,canonical_json
from .electrothermal_lgbo import is_lgbo_method

FORMATS=('full_v1','compact_v1','compact_action_v2')
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
    is_region=payload.get('task')==TASK
    if is_region and mode=='compact_action_v2' and payload.get('region_proposal')!='catalog_v1':
        raise ValueError('action Region wire requires catalog_v1')
    return is_region and mode in ('compact_v1','compact_action_v2')

def _binding(payload):
    # Include weights, scales, history, physical semantics, signatures and pool
    # advice, not just the dimension or a model-provided context identifier.
    version='region_compact_action_v2' if payload.get('region_wire_format')=='compact_action_v2' else 'region_compact_v1'
    return digest_value({'wire_version':version,
        'request':{k:v for k,v in payload.items() if k!='artifact_task'}})

def region_wire_payload(payload):
    if payload.get('task')==TASK and is_lgbo_method(payload.get('region_method')):
        from .electrothermal_lgbo_wire import lgbo_wire_payload
        return lgbo_wire_payload(payload)
    if not _compact(payload):return deepcopy(payload)
    if any(k not in payload for k in ENVELOPE):raise ValueError('complete frozen Region envelope required')
    wire=deepcopy(payload);wire.pop('signatures')
    wire['request_id']=_binding(payload)
    region_contract=deepcopy(payload['response_contract']['properties']['region'])
    action=payload.get('region_wire_format')=='compact_action_v2'
    if action:
        for branch in region_contract['oneOf']:
            branch['required']=[name for name in branch['required'] if name!='reason']
            # Unrequested legacy commentary is inert metadata, never an action
            # field. Accepting it does not permit any other extra field.
            branch['properties']['reason']={}
    wire['response_contract']={'type':'object','additionalProperties':False,'required':['request_id','region'],
        'properties':{'request_id':{'const':wire['request_id']},'region':region_contract}}
    wire['instructions']+= ('\nReturn only request_id and the required region action fields. Copy request_id exactly. Do not provide explanations or generate a reason field.' if action else
        '\nFor this compact exchange, return only request_id and region as specified by response_contract. Copy request_id exactly; identities are checked locally.')
    return wire

def decode_region_wire(response,payload):
    if payload.get('task')==TASK and is_lgbo_method(payload.get('region_method')):
        from .electrothermal_lgbo_wire import decode_lgbo_action
        return decode_lgbo_action(response,payload)
    if not _compact(payload):return response
    action=payload.get('region_wire_format')=='compact_action_v2'
    if action:
        # Check the entire reply before discarding metadata: invalid JSON must
        # not become a valid action merely because the bad value was in reason.
        from .electrothermal_region_catalog import catalog_reply_is_json_native
        if not catalog_reply_is_json_native(response):raise ValueError('action reply must use native JSON types')
        try:canonical_json(response)
        except (ValueError,TypeError,OverflowError):raise ValueError('action reply must contain finite JSON') from None
    if not isinstance(response,dict) or set(response)!={'request_id','region'} or response['request_id']!=_binding(payload):
        raise ValueError('stale or invalid compact Region binding')
    if action:
        if type(response['region']) is not dict:raise ValueError('action region must be a JSON object')
        region={k:deepcopy(v) for k,v in response['region'].items() if k!='reason'}
        region['reason']='structured_catalog_response'
    else:region=deepcopy(response['region'])
    return {**{k:deepcopy(payload[k]) for k in ENVELOPE},'region':region}
