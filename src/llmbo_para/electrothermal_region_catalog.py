"""Host-owned geometry proposals and strict IDs bound to a complete request."""
from copy import deepcopy
import json
import math
import re
import numpy as np

from .runstore import digest_value


VERSION = 'region_catalog_v1'
ENVELOPE = ('schema_version','parameter_profile','fit_rates','signatures','context_id')


def catalog_archival_json(value) -> str:
    """Sanitized formal JSON text, including rejected nonfinite diagnostics.

    Mask token-shaped strings without changing their length so replay retains
    the reason-length validation. This never reads a credential environment.
    """
    def redact(item):
        if isinstance(item,str):
            return re.sub(r'sk-[A-Za-z0-9_-]{8,}',lambda m:'*'*len(m[0]),item)
        if isinstance(item,dict):
            result={};reserved=set(item)
            for name,child in sorted(item.items(),key=lambda pair:str(pair[0])):
                public=redact(name) if isinstance(name,str) else name
                if public!=name:
                    suffix=0
                    while public in reserved or public in result:
                        suffix+=1;ending='~'+str(suffix)
                        public='*'*max(0,len(name)-len(ending))+ending
                result[public]=('[REDACTED]' if str(name).lower() in
                    {'authorization','api_key','access_token','secret'} else redact(child))
            return result
        if isinstance(item,(list,tuple)):
            return [redact(child) for child in item]
        return item
    return json.dumps(redact(value),ensure_ascii=False,sort_keys=True,allow_nan=True)


def _entry_id(context_id, entry):
    return digest_value({'version':VERSION,'context_id':context_id,'candidate_id':entry['candidate_id'],
                         'lb':entry['lb'],'ub':entry['ub']})


def build_region_catalog(context, *, advice: dict, settings) -> dict:
    """Offer three fixed widths per existing eligible shortlist point, no ranks."""
    width, maximum = float(settings.min_width),float(settings.max_width)
    if not math.isfinite(width) or not math.isfinite(maximum) or not 0<width<=maximum<=1:
        raise ValueError('valid configured Region widths required')
    if advice.get('context_id')!=context.context_id or advice.get('pool_digest')!=digest_value(context.pool):
        raise ValueError('catalog advice must match the frozen context and pool')
    candidates=advice.get('candidates')
    if not isinstance(candidates,list) or not 1<=len(candidates)<=12:
        raise ValueError('bounded existing candidate shortlist required')
    entries=[];seen_ids=set()
    for row in candidates:
        if not row.get('eligible_alternative') or row.get('is_plain'):
            continue
        ident=row['candidate_id'];index=row['pool_index'];point=np.asarray(row['normalized_parameters'],dtype=float)
        if (not isinstance(ident,str) or ident in seen_ids or type(index) is not int or not 0<=index<len(context.pool)
                or point.shape!=(6,) or np.any(~np.isfinite(point)) or np.any((point<0)|(point>1))
                or not np.array_equal(point,np.asarray(context.pool[index],dtype=float))):
            raise ValueError('catalog candidate differs from the frozen shortlist')
        seen_ids.add(ident);seen_widths=set()
        for factor in (1,2,4):
            requested=min(maximum,factor*width)
            if requested in seen_widths:continue
            seen_widths.add(requested)
            lower=np.clip(point-requested/2,0.,1.-requested)
            entry={'candidate_id':ident,'pool_index':index,'width':requested,
                   'lb':lower.tolist(),'ub':(lower+requested).tolist()}
            entry={'region_id':_entry_id(context.context_id,entry),**entry}
            entries.append(entry)
    catalog={'version':VERSION,'context_id':context.context_id,'pool_digest':digest_value(context.pool),'entries':entries}
    return {**catalog,'catalog_digest':digest_value(catalog)}


def catalog_proposal_binding(payload: dict) -> str:
    return digest_value({k:v for k,v in payload.items() if k not in ('artifact_task','response_contract','proposal_binding')})


def catalog_region_contract(payload: dict) -> dict:
    """Region fragment only; existing full/compact envelopes remain responsible."""
    base={'coordinate_space':{'const':'normalized'},'confidence':{'type':'number','minimum':0,'maximum':1},
          'reason':{'type':'string','maxLength':400},'proposal_binding':{'const':payload['proposal_binding']}}
    none={'kind':{'const':'none'},**base}
    branches=[{'type':'object','additionalProperties':False,'required':list(none),'properties':none}]
    ids=[entry['region_id'] for entry in payload['region_catalog']['entries']]
    if ids:
        region={'kind':{'const':'region'},**base,'region_id':{'type':'string','enum':ids},
                'evidence_ids':{'type':'array','minItems':1,'maxItems':3,'uniqueItems':True,
                                'items':{'type':'string','enum':[r['evaluation_id'] for r in payload['history']]}}}
        branches.append({'type':'object','additionalProperties':False,'required':list(region),'properties':region})
    return {'oneOf':branches}


def resolve_catalog_region(response: dict, *, payload: dict) -> tuple[dict,dict]:
    """Validate the model's ID; host copies geometry, never repairs coordinates."""
    try:
        if payload.get('region_proposal')!='catalog_v1' or payload['proposal_binding']!=catalog_proposal_binding(payload):
            raise ValueError('invalid frozen catalog request binding')
        catalog=payload['region_catalog']
        if (catalog['version']!=VERSION or catalog['context_id']!=payload['context_id']
                or catalog['catalog_digest']!=digest_value({k:v for k,v in catalog.items() if k!='catalog_digest'})):
            raise ValueError('invalid frozen Region catalog')
        entries=catalog['entries']
        if not isinstance(entries,list) or len(entries)>33 or len({e['region_id'] for e in entries})!=len(entries):
            raise ValueError('invalid catalog entries')
        for entry in entries:
            if entry['region_id']!=_entry_id(payload['context_id'],entry):
                raise ValueError('catalog geometry identity differs')
        if not isinstance(response,dict) or set(response)!={*ENVELOPE,'region'}:
            raise ValueError('complete electrothermal catalog envelope required')
        if type(response['schema_version']) is not int or any(digest_value(response[k])!=digest_value(payload[k]) for k in ENVELOPE):
            raise ValueError('stale or incompatible catalog envelope')
        region=response['region']
        if not isinstance(region,dict):raise ValueError('catalog region must be an object')
        base={'kind','coordinate_space','confidence','reason','proposal_binding'}
        kind=region.get('kind')
        if kind not in ('none','region') or set(region)!=(base if kind=='none' else base|{'region_id','evidence_ids'}):
            raise ValueError('catalog reply must use only the documented ID fields')
        confidence=region['confidence']
        if (region['coordinate_space']!='normalized' or region['proposal_binding']!=payload['proposal_binding']
                or type(confidence) not in (int,float) or not math.isfinite(confidence) or not 0<=confidence<=1
                or not isinstance(region['reason'],str) or len(region['reason'])>400):
            raise ValueError('invalid catalog reply binding or scalar fields')
        entry=None;evidence=[]
        if kind=='region':
            ident=region['region_id'];evidence=region['evidence_ids']
            past={r['evaluation_id'] for r in payload['history']}
            if (not isinstance(ident,str) or type(evidence) is not list or not 1<=len(evidence)<=3
                    or any(type(i) is not str or i not in past for i in evidence) or len(set(evidence))!=len(evidence)):
                raise ValueError('catalog reply requires unique sent past evidence IDs')
            entry=next((e for e in entries if e['region_id']==ident),None)
            if entry is None:raise ValueError('unknown Region ID')
        canonical={k:deepcopy(payload[k]) for k in ENVELOPE}
        canonical['region']={'kind':kind,'coordinate_space':'normalized','confidence':float(confidence),
                             'reason':'structured_catalog_response'}
        if entry is not None:
            canonical['region'].update(lb=deepcopy(entry['lb']),ub=deepcopy(entry['ub']))
        from .electrothermal_llm import validate_electrothermal_region
        canonical=validate_electrothermal_region(canonical,expected_context_id=payload['context_id'],expected_signatures=payload['signatures'])
        resolution={'version':'catalog_resolution_v1','context_id':payload['context_id'],
            'proposal_binding':payload['proposal_binding'],'catalog_digest':catalog['catalog_digest'],
            'kind':kind,'region_id':entry['region_id'] if entry is not None else None,
            'evidence_ids':deepcopy(evidence),'confidence':float(confidence),'canonical_response':deepcopy(canonical)}
        return canonical,resolution
    except (KeyError,TypeError,OverflowError) as exc:
        raise ValueError('malformed electrothermal catalog response or request') from exc
