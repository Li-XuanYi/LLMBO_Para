"""Cold-spawn paired fresh-seed LLMBO / NSGA-II / SMPSO experiment."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]


def read(path): return json.loads(Path(path).read_text(encoding='utf8'))
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--software',action='store_true');group.add_argument('--execute',action='store_true')
    p.add_argument('--design',type=Path,required=True);p.add_argument('--template',type=Path,required=True)
    p.add_argument('--policy-python',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--rounds',type=int,default=50);p.add_argument('--seed-count',type=int,default=5,choices=range(1,6))
    p.add_argument('--software-proof',type=Path)
    args=p.parse_args()
    if args.rounds<1: raise ValueError('positive rounds required')
    if args.execute and (args.rounds!=50 or args.seed_count!=5 or args.software_proof is None):
        raise ValueError('five seeds, fifty rounds and matching software proof required')
    for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
    os.environ['PYBAMM_DISABLE_TELEMETRY']='true';sys.dont_write_bytecode=True
    sys.path.insert(0,str(ROOT/'src'))
    import et_factorial_worker as factorial
    import et_classical_worker as classical
    import analyze_et_classical_validation as analyzer
    import run_lgbo_real_gain as helper
    from et_factorial_budget import FactorialBudget,atomic_json
    from llmbo_para.electrothermal_provenance import source_fingerprint
    design=read(args.design);template=read(args.template);seeds=design['seeds'][:args.seed_count]
    if sha(args.template)!=design['template_sha256'] or len(seeds)!=len(set(seeds)):
        raise ValueError('frozen design or data template changed')
    names=['scripts/run_fresh_comparison.py','scripts/et_factorial_worker.py','scripts/et_classical_worker.py',
           'scripts/et_classical_policy.py','scripts/analyze_et_classical_validation.py','scripts/analyze_et_factorial_validation.py',
           'scripts/run_lgbo_real_gain.py','scripts/lgbo_real_gain_worker.py','scripts/et_factorial_budget.py']
    package=args.policy_python.resolve().parent.parent/'Lib/site-packages/jmetal'
    def pins_now():
        return {'design':sha(args.design),'template':sha(args.template),'scientific_source':source_fingerprint(ROOT),
            'scripts':{n:sha(ROOT/n) for n in names},'policy_python':sha(args.policy_python),
            'jmetal_sources':{str(x.relative_to(package)):sha(x) for x in sorted(package.rglob('*.py'))}}
    pins=pins_now()
    if not pins['jmetal_sources']:raise ValueError('policy environment missing')
    if args.execute:
        proof=read(args.software_proof/'result.json')
        if read(args.software_proof/'source-pins.json')!=pins or proof['status']!='completed' or proof['rounds']!=10 or proof['counts']!={'DFN':0,'API':0}:
            raise ValueError('software proof or pinned sources differ')
        if [x['seed'] for x in proof['seeds']]!=seeds:raise ValueError('software proof seed mismatch')
        for row in proof['seeds']:
            if set(row['arms'])!={'LLMBO','nsga2','smpso'} or any(x['status']!='completed' for x in row['arms'].values()):
                raise ValueError('software proof incomplete')
            for m in ('nsga2','smpso'):
                if not analyzer.audit_external(row['arms'][m]['run_directory'],expected_rounds=10)['passed']:
                    raise ValueError('software external audit failed')
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as key:
            credential,_=winreg.QueryValueEx(key,'LLMBO_OPENCODE_API_KEY')
        if not credential or any(c.isspace() for c in credential):raise ValueError('LLM credential unavailable')
        os.environ['LLMBO_OPENCODE_API_KEY']=credential;del credential
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    atomic_json(output/'source-pins.json',pins)
    protocol={'design':design,'mode':'software' if args.software else 'real_DFN_synthetic','rounds':args.rounds,'seed_order':seeds}
    atomic_json(output/'protocol.json',protocol)
    phases={}
    for s in seeds:
        for k in ('numeric','llm_v3'):
            phases[f'{s}-{k}']={'DFN':0 if args.software else 128,'API':0 if args.software or k=='numeric' else 3}
        for m in design['arm_order_by_seed'][str(s)]:
            phases[f'{s}-{m}']={'DFN':0 if args.software else 2*args.rounds,'API':0 if args.software or m!='LLMBO' else args.rounds}
    budget=FactorialBudget.start(output/'budget.jsonl',phases=phases,protocol_sha=sha(output/'protocol.json'))
    result={'status':'running','rounds':args.rounds,'seed_order':seeds,'seeds':[],'counts':budget.counts()}
    atomic_json(output/'result.json',result)
    def integrity():
        if pins_now()!=pins:raise ValueError('pinned source or dependencies changed')
    def run_phase(s,kind,pool=None):
        label=f'{s}-{kind}';dest=output/label;dest.mkdir();budget.begin(label)
        common={'seed':s,'rounds':args.rounds,'base_config':template,'software_fixture':args.software,
            'source_root':str(ROOT),'source':pins['scientific_source'],'output':str(dest),'label':label,'deadline':budget.deadline}
        if kind in ('numeric','llm_v3'):
            target=factorial.run_worker;spec={**common,'kind':kind,'arm':None,'initial':None}
        elif kind=='LLMBO':
            target=factorial.run_worker;spec={**common,'kind':'arm','arm':'A11',
                'initial':{'path':pool['plan_path'],'sha256':pool['plan_file_sha256']}}
        else:
            target=classical.run_worker;spec={**common,'method':kind,'pool':pool,
                'policy_python':str(args.policy_python.resolve()),'policy_environment':{'mode':'software' if args.software else 'real'}}
        try:
            value=helper.supervise(target,spec,budget,deadline=budget.deadline,metadata=output/(label+'-owned.json'),integrity_check=integrity)
            if value.get('status')!='completed' or not value.get('audit_passed'):raise ValueError('worker audit or completion failed')
            if kind in ('nsga2','smpso'):
                check=analyzer.audit_external(value['run_directory'],expected_rounds=args.rounds)
                if not check['passed']:raise ValueError('external audit: '+check['reason'])
                value['external_audit']=check
            budget.finish(True);return value
        except Exception as exc:
            if budget.state()['phase'] is not None:budget.finish(False)
            detail=read(dest/'worker-failure.json') if (dest/'worker-failure.json').exists() else None
            return {'status':'failed','reason':str(exc),'worker_failure':detail}
    try:
        with helper.keep_awake(output/'wake.json'):
            for s in seeds:
                row={'seed':s,'pools':{},'arms':{}};result['seeds'].append(row)
                for k in ('numeric','llm_v3'):
                    row['pools'][k]=run_phase(s,k);result['counts']=budget.counts();atomic_json(output/'result.json',result)
                    print(json.dumps({'seed':s,'phase':k,'status':row['pools'][k]['status'],'counts':result['counts']}),flush=True)
                for m in design['arm_order_by_seed'][str(s)]:
                    pool=row['pools']['llm_v3' if m=='LLMBO' else 'numeric']
                    if pool['status']=='completed':row['arms'][m]=run_phase(s,m,pool)
                    else:
                        budget.begin(f'{s}-{m}');budget.finish(False)
                        row['arms'][m]={'status':'failed','reason':'required initialization failed'}
                    result['counts']=budget.counts();atomic_json(output/'result.json',result)
                    print(json.dumps({'seed':s,'phase':m,'status':row['arms'][m]['status'],'counts':result['counts']}),flush=True)
            result['status']='completed' if all(all(v['status']=='completed' for v in row['pools'].values()) and all(v['status']=='completed' for v in row['arms'].values()) for row in result['seeds']) else 'completed_with_failures'
            result['counts']=budget.counts();atomic_json(output/'result.json',result)
    finally:
        if args.execute:os.environ.pop('LLMBO_OPENCODE_API_KEY',None)
    return 0 if result['status']=='completed' else 1


if __name__=='__main__':raise SystemExit(main())
