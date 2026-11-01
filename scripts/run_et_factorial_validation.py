"""Four-arm factorial supervisor. Importing this file cannot send requests or solve."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf8'))


def execute(args):
    # These imports must stay inside the parent entrypoint for Windows spawn isolation.
    from dataclasses import asdict
    import prepare_et_ablation_benchmarks as design
    import et_factorial_worker as worker
    import run_lgbo_real_gain as helper
    import run_et_warmstart_quality_gate_trial as legacy
    import analyze_et_factorial_validation as analyzer
    from et_factorial_budget import FactorialBudget,atomic_json
    from llmbo_para.electrothermal_provenance import source_fingerprint

    if not args.software and (args.rounds!=50 or args.seed_count!=5):raise ValueError('authorized live factorial requires five seeds and fifty rounds')
    output=args.output.resolve()
    template=json.loads(args.template.read_text(encoding='utf-8-sig'))
    bundle=design.build_design(template,template_path=str(args.template.resolve()),rounds=50)
    seeds=bundle['protocol']['screening_seeds'][:args.seed_count]
    names=legacy.source_names()|{'scripts/et_factorial_budget.py','scripts/et_factorial_worker.py',
        'scripts/analyze_et_factorial_validation.py','scripts/run_et_factorial_validation.py','scripts/prepare_et_ablation_benchmarks.py'}
    pins={name:sha(ROOT/name) for name in sorted(names)}
    def integrity():
        if any(sha(ROOT/name)!=expected for name,expected in pins.items()):raise ValueError('running source changed')
        if output.exists() and (output/'protocol.json').exists() and sha(output/'protocol.json')!=protocol_sha:raise ValueError('trial protocol changed')
    if not args.software:
        legacy.verify_runtime()
        if subprocess.check_output(['git','status','--short'],cwd=ROOT,text=True).strip():raise ValueError('live source must be committed')
        if args.software_proof is None:raise ValueError('five-seed software rehearsal proof required')
        proof=read(args.software_proof/'result.json');proof_analysis=read(args.software_proof/'analysis.json')
        if proof.get('status')!='completed' or proof.get('rounds')!=10 or proof.get('seed_order')!=seeds or proof.get('counts')!={'DFN':0,'API':0}:
            raise ValueError('software rehearsal result differs')
        if proof_analysis.get('completed_four_arm_seeds')!=5 or read(args.software_proof/'source-pins.json')!=pins:
            raise ValueError('software rehearsal source or analysis differs')
    if not args.resume:
        output.mkdir(parents=True,exist_ok=False)
        protocol={'experiment_id':'factorial-20261101','seed_order':seeds,'rounds':args.rounds,
                  'fit_rates':template['fit_rates'],'initial_pool':16,'gp_initial':8,'initial_unique_attempt_guard':64,
                  'selection':worker.RULE,'region_method':'lgbo_v2','mode':'software' if args.software else 'real_DFN_synthetic',
                  'authorization':'user: directly implement/run five seeds/fifty rounds with no spending quota',
                  'full_regression':'not_claimed','template_sha256':sha(args.template),'no_global_spending_quota':True,
                  'phase_timeout_s':21600,'ablation_order':{str(s):bundle['protocol']['ablation_order'][str(s)] for s in seeds},
                  'physical_data_sha256':hashlib.sha256(json.dumps(template['data'],sort_keys=True).encode()).hexdigest()}
        atomic_json(output/'protocol.json',protocol);atomic_json(output/'template.json',template);atomic_json(output/'source-pins.json',pins)
        for name in names:
            dest=output/'runtime'/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,dest)
        atomic_json(output/'release.json',{'source_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'source_pins':pins,'software_proof':str(args.software_proof) if args.software_proof else None,
            'full_regression_completed':False,'user_authorized':not args.software,'created_unix':time.time()})
    else:
        if read(output/'source-pins.json')!=pins:raise ValueError('cannot resume different source')
        protocol=read(output/'protocol.json')
        if protocol['rounds']!=args.rounds or protocol['seed_order']!=seeds or protocol['template_sha256']!=sha(args.template):raise ValueError('resume protocol differs')
    protocol_sha=sha(output/'protocol.json');integrity()
    phases={}
    for seed in seeds:
        phases[f'{seed}-numeric']={'DFN':0 if args.software else 128,'API':0}
        phases[f'{seed}-llm_v3']={'DFN':0 if args.software else 128,'API':0 if args.software else 3}
        for arm in protocol['ablation_order'][str(seed)]:
            phases[f'{seed}-{arm}']={'DFN':0 if args.software else 2*args.rounds,
                                     'API':0 if args.software or arm in ('A00','A10') else args.rounds}
    ledger=output/'budget.jsonl'
    budget=FactorialBudget(ledger,phases=phases) if args.resume else FactorialBudget.start(ledger,phases=phases,protocol_sha=protocol_sha)
    result=read(output/'result.json') if args.resume else {'status':'running','rounds':args.rounds,'seed_order':seeds,'seeds':[],'counts':budget.counts()}
    if budget.state()['phase'] is not None:budget.finish(False)
    if not args.software:
        # Read only the endpoint-specific variable, never place a key in a command or artifact.
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as key:
            secret,_=winreg.QueryValueEx(key,'LLMBO_OPENCODE_API_KEY')
        if not secret or any(c.isspace() for c in secret):raise ValueError('dedicated credential is unavailable')
        os.environ['LLMBO_OPENCODE_API_KEY']=secret;del secret
    cached_analysis={'status':'running','seeds':[],'completed_four_arm_seeds':0}
    def phase(seed,kind,arm=None,initial=None):
        name=f'{seed}-{arm or kind}';phase_root=output/f's{seed}-{arm or kind}'
        finished={e['phase']:e['success'] for e in budget.state()['finished']}
        if name in finished:
            if finished[name] and (phase_root/'worker-result.json').is_file():return read(phase_root/'worker-result.json')
            return {'status':'failed','reason':'previous failed phase preserved','phase':name}
        budget.begin(name);phase_root.mkdir(exist_ok=False)
        spec={'kind':kind,'arm':arm,'seed':seed,'rounds':args.rounds,'initial':initial,'base_config':template,
              'software_fixture':args.software,'source_root':str(ROOT),'source':source_fingerprint(ROOT),
              'output':str(phase_root),'label':name,'deadline':budget.deadline}
        try:
            integrity();value=helper.supervise(worker.run_worker,spec,budget,deadline=budget.deadline,
                                               metadata=output/(name+'-owned.json'),integrity_check=integrity)
            if value['status']!='completed':raise ValueError('worker did not complete')
            budget.finish(True);return value
        except Exception as exc:
            if budget.state()['phase'] is not None:budget.finish(False)
            error={'status':'failed','phase':name,'error_type':type(exc).__name__,'reason':str(exc)}
            if (phase_root/'worker-failure.json').exists():error['worker_failure']=read(phase_root/'worker-failure.json')
            atomic_json(output/(name+'-failure.json'),error);return error
    try:
        atomic_json(output/'result.json',result)
        with helper.keep_awake(output/('wake-resume.json' if args.resume else 'wake.json')):
            for seed in seeds:
                old=next((s for s in result['seeds'] if s['seed']==seed),None)
                row=old if old else {'seed':seed,'pools':{},'arms':{}}
                if old is None:result['seeds'].append(row)
                for kind in ('numeric','llm_v3'):
                    row['pools'][kind]=phase(seed,kind)
                    result['counts']=budget.counts();atomic_json(output/'result.json',result)
                for arm in protocol['ablation_order'][str(seed)]:
                    group=worker.ARMS[arm][0];pool=row['pools'][group]
                    if pool['status']!='completed':
                        name=f'{seed}-{arm}'
                        if name not in [e['phase'] for e in budget.state()['finished']]:budget.begin(name);budget.finish(False)
                        row['arms'][arm]={'status':'failed','reason':'initialization failed'};continue
                    initial={'path':pool['plan_path'],'sha256':pool['plan_file_sha256']}
                    row['arms'][arm]=phase(seed,'arm',arm,initial)
                    result['counts']=budget.counts();atomic_json(output/'result.json',result)
                    print(json.dumps({'seed':seed,'arm':arm,'status':row['arms'][arm]['status'],'counts':result['counts']}),flush=True)
                row['status']='completed' if all(v['status']=='completed' for v in row['arms'].values()) and len(row['arms'])==4 else 'failed'
                # Each finished seed yields independently audited early results before later seeds run.
                partial={'status':'partial','seeds':[row],'counts':budget.counts()}
                analysis=analyzer.analyze_trial(partial)
                atomic_json(output/f'seed-{seed}-analysis.json',analysis)
                result['counts']=budget.counts();atomic_json(output/'result.json',result)
            result.update(status='completed' if all(s['status']=='completed' for s in result['seeds']) else 'completed_with_failures',counts=budget.counts())
            atomic_json(output/'result.json',result)
            analysis=analyzer.analyze_trial(result);atomic_json(output/'analysis.json',analysis)
            integrity()
        print(json.dumps({'status':result['status'],'counts':result['counts'],'completed_seeds':analysis['completed_four_arm_seeds'],'output':str(output)}),flush=True)
        return 0 if result['status']=='completed' else 1
    finally:os.environ.pop('LLMBO_OPENCODE_API_KEY',None)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True);mode.add_argument('--software',action='store_true');mode.add_argument('--execute',action='store_true')
    parser.add_argument('--template',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--rounds',type=int,default=50);parser.add_argument('--seed-count',type=int,default=5,choices=range(1,6))
    parser.add_argument('--software-proof',type=Path);parser.add_argument('--resume',action='store_true')
    args=parser.parse_args()
    for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[name]='1'
    os.environ['PYBAMM_DISABLE_TELEMETRY']='true';sys.dont_write_bytecode=True
    return execute(args)


if __name__=='__main__':
    raise SystemExit(main())
