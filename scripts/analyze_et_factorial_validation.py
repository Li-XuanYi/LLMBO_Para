"""Independent full-pool metrics and seed-paired factorial effects."""
from pathlib import Path
import json
import math
import statistics


def read(path):return json.loads(Path(path).read_text(encoding='utf8'))


def _front(rows):
    return [r for r in rows if not any(other is not r and all(a<=b for a,b in zip(other['objectives'],r['objectives']))
                 and any(a<b for a,b in zip(other['objectives'],r['objectives'])) for other in rows)]


def metric_trajectory(pool,new_records,*,normalize):
    from analyze_et_three_arm_validation import exact_hv
    history={};attempted={};rows=[]
    for index,batch in enumerate([pool,*[[record] for record in new_records]]):
        for record in batch:
            attempted[record['evaluation_id']]=record
            if record.get('objectives') is None:continue
            ident=record['evaluation_id']
            if ident in history and [history[ident]['parameters'],history[ident]['objectives']]!=[record['parameters'],record['objectives']]:
                raise ValueError('conflicting repeated evaluation')
            history[ident]=record
        costs={'candidate_attempts':len(attempted),'solver_calls':sum(r.get('costs',{}).get('solver_calls',0) for r in attempted.values())}
        if not history:rows.append({'round':index,'HV':None,'F_U_V':None,'F_T_K':None,**costs});continue
        front=_front(list(history.values()))
        def key(r):
            values=[.5*r['objectives'][0]/.1,.5*r['objectives'][1]]
            return (max(values)+.05*math.fsum(values),tuple(normalize(r['parameters'])),r['evaluation_id'])
        chosen=min(front,key=key)
        hv=exact_hv([(r['objectives'][0]/.1,r['objectives'][1]) for r in front])
        rows.append({'round':index,'HV':hv,'F_U_V':chosen['objectives'][0],'F_T_K':chosen['objectives'][1],**costs,
                     'representative_id':chosen['evaluation_id'],'representative_parameters':chosen['parameters']})
    return rows


def factorial_effects(values):
    a,b,c,d=[values[k] for k in ('A00','A10','A01','A11')]
    return {'WarmStart':((b-a)+(d-c))/2,'Region':((c-a)+(d-b))/2,'interaction':d-b-c+a}


def verify_pool(pool):
    from dataclasses import asdict
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    from llmbo_para.electrothermal_provenance import load_initial_plan
    from llmbo_para.electrothermal_warmstart_wire import (freeze_warmstart_request,BoundWarmStartReply,decode_candidate_only_reply)
    from llmbo_para.sobol import Sobol6
    from llmbo_para.runstore import sha256_file
    import analyze_et_three_arm_validation as core
    root=Path(pool['run_directory'])
    proof=audit_electrothermal_run(root,deep=True)
    if not proof['passed']:raise ValueError('initial pool deep audit failed: '+str(proof.get('errors')))
    cfg=read(root/'manifest.json')['config'];report,prepared=prepare_electrothermal_experiment(cfg,base_dir=root/'source')
    if prepared is None:raise ValueError('archived pool preparation failed')
    plan=load_initial_plan(pool['plan_path'],space=prepared.space,dataset=prepared.dataset,signatures=prepared.signatures,
                           expected_selection_rule='pareto_quality_gated_spacefill_v3')
    if sha256_file(pool['plan_path'])!=pool['plan_file_sha256']:raise ValueError('signed pool plan changed')
    records=[read(p) for p in sorted((root/'electrothermal-evaluations').glob('*.json'))]
    info=read(root/'factorial-initialization.json');by={r['evaluation_id']:r for r in records}
    if not 16<=len(records)<=64 or len(by)!=len(records) or len(info['origins'])!=len(records) or sum(r['complete_pair_valid'] for r in records)!=16:
        raise ValueError('sixteen complete unique real pool observations required')
    if len({tuple(r['parameters']) for r in records})!=len(records):raise ValueError('duplicate physical pool point')
    if [x['evaluation_id'] for x in info['origins']]!=[r['evaluation_id'] for r in records]:raise ValueError('origin order differs')
    seed=cfg['optimization']['seed'];payloads=sorted((root/'llm').glob('*.payload.json'))
    if len(payloads)!=info['request_count'] or len(payloads)>(3 if info['kind']=='llm_v3' else 0):raise ValueError('initial request count differs')
    from llmbo_para.electrothermal_llm import build_electrothermal_payload
    from llmbo_para.electrothermal_evaluation import result_from_dict
    from llmbo_para.runstore import digest_value
    for n,path in enumerate(payloads):
        payload=read(path)
        past=[result_from_dict(by[o['evaluation_id']]) for o in info['origins'] if o['kind']=='llm' and o['request']<n]
        expected=build_electrothermal_payload('warm_start_electrothermal',prepared=prepared,history=past)
        expected.update(sampling_request={'remaining_unique_candidates':16-sum(r.complete_pair_valid for r in past),'require_novel_parameters':True},artifact_task=payload['artifact_task'])
        if digest_value(expected)!=digest_value(payload):raise ValueError('initial request history or sampling instruction differs')
    decoded={}
    for row in info['origins']:
        record=by[row['evaluation_id']];core.verify_objectives(record)
        if row['kind']=='llm':
            n=row['request']
            if n not in decoded:
                payload=read(root/f'llm/{n:06d}.payload.json');receipt=read(root/f'llm/{n:06d}.warmstart-binding.json')
                raw=json.loads(read(root/f'llm/{n:06d}.warmstart-response.json')['response_json'])
                if receipt['transport_status']=='completed':
                    envelope=root/'http'/(payload['artifact_task']+'.response.json')
                    if sha256_file(envelope)!=receipt['http_envelope_sha256']:raise ValueError('LLM envelope changed')
                    native=read(envelope)['choices'][0]['message']['content']
                    if json.loads(native)!=raw:raise ValueError('LLM response bytes differ')
                request=freeze_warmstart_request(payload,run_id=root.name,ordinal=n)
                decoded[n]=decode_candidate_only_reply(BoundWarmStartReply(raw,receipt,request),prepared=prepared,expected_request=request)
            item=decoded[n][row['index']]['parameters'];expected=[item[s.name] for s in prepared.space.specs]
        elif row['kind'] in ('sobol','sobol_fill'):
            lower=seed*1024+(256 if row['kind']=='sobol_fill' else 0)
            if not lower<=row['index']<lower+128:raise ValueError('Sobol origin outside declared stream')
            expected=prepared.space.denormalize(Sobol6(row['index']).draw(1)[0])
        else:raise ValueError('unknown initialization source')
        if list(expected)!=record['parameters']:raise ValueError('pool point differs from true proposal or Sobol source')
    if [r.evaluation_id for r in plan.records]!=pool['selected_ids'] or pool['costs']!=read(root/'electrothermal-summary.json')['costs']:
        raise ValueError('pool selection or cost attribution differs')
    return records


def analyze_arm(case,pool):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    from llmbo_para.config import parameter_space_from_config
    from llmbo_para.runstore import sha256_file,digest_value
    import analyze_et_three_arm_validation as core
    initial=verify_pool(pool)
    root=Path(case['run_directory']);proof=audit_electrothermal_run(root,deep=True)
    if not proof['passed']:raise ValueError('arm deep audit failed: '+str(proof.get('errors')))
    if case['initial_file_sha']!=pool['plan_file_sha256'] or case['selected_ids']!=pool['selected_ids']:
        raise ValueError('shared initialization differs')
    cfg=read(root/'manifest.json')['config'];space=parameter_space_from_config(cfg)
    events=[read(p) for p in sorted((root/'mo-rounds').glob('*.json'))]
    records=[read(p) for p in sorted((root/'electrothermal-evaluations').glob('*.json'))]
    if len(events)!=case['BO_rounds'] or len(records)!=8+len(events):raise ValueError('round archive count differs')
    by={}
    for row in records:core.verify_objectives(row);by[row['evaluation_id']]=row
    selected=[by[i] for i in case['selected_ids']]
    for row in selected:
        original=next(r for r in initial if r['evaluation_id']==row['evaluation_id'])
        if row['parameters']!=original['parameters'] or row['objectives']!=original['objectives']:raise ValueError('selected input changed')
    # Events identify the actual newly attempted observations; partial failures stay diagnostic.
    additions=[by[event['evaluation_id']] for event in events]
    trajectory=metric_trajectory(initial,additions,normalize=space.normalize)
    all_complete={r['evaluation_id']:r for r in [*initial,*additions] if r.get('objectives') is not None}
    final_pareto=[{k:r[k] for k in ('evaluation_id','parameters','objectives')} for r in _front(list(all_complete.values()))]
    k=min(10,len(events));auc=math.fsum((a['HV']+b['HV'])/2 for a,b in zip(trajectory[:k],trajectory[1:k+1]))/k if k else None
    first=events[0]['context'] if events else None
    return {'status':'audited','trajectory':trajectory,'AUC_HV_0_10':auc if k==10 else None,
            'first_numeric_context':digest_value({k:first[k] for k in ('scalarization','gp_state','pool')}) if first else None,
            'weights':[e['context']['scalarization']['weights'] for e in events],
            'initial_plan_sha256':case['initial_file_sha'],'costs':case['costs'],
            'region_diagnostics':case['summary']['region_diagnostics'],'final_pareto':final_pareto,
            'failed_objective_pairs':sum(not r['complete_pair_valid'] for r in additions)}


def analyze_trial(result):
    output={'status':'completed' if result['status']=='completed' else 'partial','seeds':[],
            'metric_scope':'all sixteen real initialization points plus formal observations',
            'counts':result.get('counts'),'full_regression':'not_claimed'}
    for seed in result['seeds']:
        arms={}
        for arm,case in seed.get('arms',{}).items():
            if case.get('status')=='completed':arms[arm]=analyze_arm(case,seed['pools']['numeric' if arm in ('A00','A01') else 'llm_v3'])
        for left,right in (('A00','A01'),('A10','A11')):
            if left in arms and right in arms:
                if arms[left]['first_numeric_context']!=arms[right]['first_numeric_context']:raise ValueError('paired first GP/pool differs')
        item={'seed':seed['seed'],'arms':arms,'complete_four_arm_seed':len(arms)==4}
        if len(arms)==4:
            if len({json.dumps(v['weights']) for v in arms.values()})!=1:raise ValueError('factorial weights differ')
        if len(arms)==4 and all(v['AUC_HV_0_10'] is not None and len(v['trajectory'])>10 for v in arms.values()):
            item['effects_AUC_HV_0_10']=factorial_effects({a:v['AUC_HV_0_10'] for a,v in arms.items()})
            item['effects_HV_10']=factorial_effects({a:v['trajectory'][10]['HV'] for a,v in arms.items()})
        output['seeds'].append(item)
    output['completed_four_arm_seeds']=sum(s['complete_four_arm_seed'] for s in output['seeds'])
    complete=[s for s in output['seeds'] if 'effects_AUC_HV_0_10' in s]
    if complete:
        output['mean_effects_AUC_HV_0_10']={name:statistics.fmean(s['effects_AUC_HV_0_10'][name] for s in complete) for name in ('WarmStart','Region','interaction')}
    return output
