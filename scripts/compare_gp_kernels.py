"""Compare full versus saved LLM-mixture kernels on the same adaptive trajectory.

Both models receive exactly the archived inputs/targets available before each
selected candidate. No candidate is selected anew and no DFN/API is executed.
"""
import os
for key in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):os.environ[key]='1'
import argparse
from contextlib import redirect_stdout,redirect_stderr
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from llmbo_para.runstore import RunStore,sha256_file,digest_value
from llmbo_para.surrogate import Matern52GP
from resource_snapshot import snapshot


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def restore(state):
    model=Matern52GP(max_sweeps=state['max_sweeps'],jitter=state['jitter'],max_lambda=state['max_lambda'])
    model.x=np.array(state['x']);model.y=np.array(state['y']);model.params=np.array(state['hyperparameters'])
    model.group=tuple(state['group']);model.has_group=bool(model.group);model.lambda_=state['lambda']
    model._factor()
    return model


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_run',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'runs/gp-kernel-controls')
    args=parser.parse_args();source=args.source_run.resolve()
    manifest=read(source/'manifest.json');hashes=read(source/'source-sha256.json')
    normalized={k.replace('\\','/'):v for k,v in hashes.items()}
    for name in ('surrogate.py','metrics.py'):
        if sha256_file(ROOT/'src/llmbo_para'/name)!=normalized['src/llmbo_para/'+name]:
            raise ValueError('control implementation differs from executed source: '+name)
    count=manifest['config']['optimization']['warm_start_llm_points']+manifest['config']['optimization']['sobol_points']
    records=[read(p) for p in sorted((source/'attempts').glob('*.json'))]
    config={'kind':'matched_data_gp_kernel_control','source_run':str(source),'source_manifest_sha256':sha256_file(source/'manifest.json'),
        'gp_sweeps':manifest['config']['optimization']['gp_sweeps'],'selected_bo_points':len(records)-count,
        'api_calls':0,'dfn_solves':0,'groups':'archived LLM suggestion fixed before the evaluated trajectory',
        'limits':'same adaptive test points, available valid-rate labels only; predictive control, not a new BO performance ablation'}
    store=RunStore(args.output,config,command=subprocess.list2cmdline([sys.executable,*sys.argv]))
    print(json.dumps({'control_directory':str(store.path)}),flush=True)
    started=time.perf_counter();rows=[];cache={};fits=0
    with (store.path/'stdout.log').open('x',encoding='utf-8',buffering=1) as out,(store.path/'stderr.log').open('x',encoding='utf-8') as err:
        with redirect_stdout(out),redirect_stderr(err):
            try:
                resources=snapshot();store.write_json('resources-before.json',resources)
                if resources.get('memory_available_bytes',4e9)<1024**3+256*1024**2:raise RuntimeError('insufficient memory for serial offline fitting')
                for index in range(count,len(records)):
                    model_file=source/f'models/after-{index:06d}.json'
                    acquisition_file=source/f'acquisition/candidate-{index:06d}.json'
                    saved=read(model_file);acquisition=read(acquisition_file)
                    x=np.array([acquisition['normalized_pool'][acquisition['selected_index']]])
                    store.write_json(f'inputs/before-{index:06d}.json',{'models':saved,'test_normalized':x.tolist(),
                        'model_source_sha256':sha256_file(model_file),'acquisition_source_sha256':sha256_file(acquisition_file),
                        'actual_errors_v':{q['rate']:q['rmse_v'] for q in records[index]['rates']}})
                    full_states={}
                    for rate,state in saved['models'].items():
                        key=digest_value({'x':state['x'],'y':state['y']})
                        if (rate,key) not in cache:
                            cache[(rate,key)]=Matern52GP(max_sweeps=config['gp_sweeps']).fit(state['x'],state['y'])
                            fits+=1
                        full=cache[(rate,key)];full_states[rate]=full.state_dict()
                        actual=next(q for q in records[index]['rates'] if q['rate']==rate)
                        if not actual['valid']:continue
                        transform=saved['transforms'][rate]
                        z=(np.log(actual['rmse_v']+transform['epsilon_v'])-transform['mean'])/transform['std']
                        for label,model in (('full',full),('llm_mixture',restore(state))):
                            mean,latent_sd=model.predict(x);sd=float(np.sqrt(latent_sd[0]**2+np.exp(2*model.params[7])))
                            median=float(np.exp(transform['mean']+transform['std']*mean[0])-transform['epsilon_v'])
                            error=float((z-mean[0])/sd)
                            rows.append({'bo_iteration':index-count+1,'rate':rate,'model':label,
                                'actual_rmse_v':actual['rmse_v'],'predicted_median_v':median,'absolute_error_mV':abs(median-actual['rmse_v'])*1000,
                                'covered_95':abs(error)<=1.96,'negative_log_predictive_density':float(.5*np.log(2*np.pi*sd**2)+.5*error**2),
                                'training_count':len(state['x']),'lambda':model.lambda_})
                    store.write_json(f'full-models/before-{index:06d}.json',full_states)
                    store.append_event({'type':'matched_gp_step','completed':index-count+1,'pending':len(records)-index-1,'new_full_gp_fits':fits,
                        'elapsed_s':time.perf_counter()-started})
                metrics={}
                for rate in ('0.5C','1C','2C','3C'):
                    metrics[rate]={}
                    for label in ('full','llm_mixture'):
                        values=[r for r in rows if r['rate']==rate and r['model']==label]
                        metrics[rate][label]={'n':len(values),'prediction_mae_mV':float(np.mean([r['absolute_error_mV'] for r in values])),
                            'predictive_95_coverage':float(np.mean([r['covered_95'] for r in values])),
                            'mean_negative_log_predictive_density':float(np.mean([r['negative_log_predictive_density'] for r in values]))}
                result={'metrics':metrics,'new_full_gp_fits':fits,'dfn_solves':0,'api_calls':0,'elapsed_s':time.perf_counter()-started,
                    'predictive_pairs':len(rows)//2,'source_run':str(source),'limits':config['limits']}
                store.write_json('predictions.json',rows);store.write_json('result.json',result)
                store.finish('completed',result)
                print(json.dumps(result,ensure_ascii=False),flush=True)
                return 0
            except BaseException as exc:
                failure={'error_type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()}
                store.write_json('failure.json',failure);store.finish('failed',failure);raise


if __name__=='__main__':raise SystemExit(main())
