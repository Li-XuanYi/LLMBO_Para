"""Recalculate archived screening labels and replay random draws without DFN/API."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
for name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS"):
    os.environ[name]="1"
workspace=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(workspace/'src'))
import numpy as np
from llmbo_para.audit import read_json
from llmbo_para.config import parameter_space_from_config
from llmbo_para.evaluation import CallableSimulator, DischargeSeries, FourRateEvaluator
from llmbo_para.feasibility import InventoryGate
from llmbo_para.initialization import validated_cached_results
from llmbo_para.runstore import RunStore, digest_value, sha256_file


def audit(directory):
    directory=Path(directory).resolve()
    manifest=read_json(directory/'manifest.json')
    config=manifest['config'].get('experiment',manifest['config'])
    space=parameter_space_from_config(config)
    inputs=read_json(directory/'input-series.json')
    series={rate:DischargeSeries(**row) for rate,row in inputs.items()}
    issues=[]
    if digest_value(inputs)!=read_json(directory/'input-series-sha256.json')['sha256']:
        issues.append('input series SHA differs')
    if config['data']['kind']=='xlsx' and sha256_file(directory/'inputs/raw.xlsx')!=config['data']['sha256']:
        issues.append('workbook SHA differs')
    plan=read_json(directory/'initial-plan.json')
    validated_cached_results(config,series,plan,directory/'initial-plan.json')
    records=[read_json(file) for file in sorted((directory/'attempts').glob('*.json'))]
    for index,record in enumerate(records):
        rates={row['rate']:row for row in record['rates']}
        simulator=CallableSimulator(lambda params,row: (rates[row.rate]['simulation_time_s'],rates[row.rate]['simulation_voltage_v']))
        actual=FourRateEvaluator(space,simulator).evaluate(record['parameters'],series)
        if actual.valid!=record['valid'] or (actual.valid and not np.isclose(actual.objective_v,record['objective_v'],rtol=1e-10,atol=1e-12)):
            issues.append(f'candidate {index}: full-curve validity or objective differs')
        for row in actual.rates:
            saved=rates[row.rate]
            if row.valid!=saved['valid'] or (row.valid and not np.isclose(row.rmse_v,saved['rmse_v'],rtol=1e-10,atol=1e-12)):
                issues.append(f'candidate {index}/{row.rate}: rate label differs')
            if not saved['valid'] and (saved['rmse_v'] is not None or not saved['reason']):
                issues.append(f'candidate {index}/{row.rate}: failure has invented label or missing reason')
    cost=plan['screening_cost']; prior=plan.get('prior_candidate_evaluations',0)
    if len(records)+prior!=cost['candidate_evaluations']:
        issues.append('candidate screening cost differs from archives')
    rng_replayed=None
    if plan['source']=='random':
        policy=read_json(directory/'screening-policy.json')
        gate=InventoryGate(**policy['gate']) if policy['gate'] else None
        generated=np.random.default_rng(config['optimization']['seed']).random((cost['generated_draws'],space.dimension))
        expected=[]; seen=set()
        for normalized in generated:
            try:
                point=space.denormalize(normalized)
            except ValueError:
                continue
            if point in seen:
                continue
            seen.add(point)
            if gate is None or gate.check(point)['feasible']:
                expected.append(list(point))
        rng_replayed=len(expected)
        if expected[prior:]!=[row['parameters'] for row in records]:
            issues.append('evaluations differ from the exact seeded uniform draw sequence after necessary screening')
    return {'passed':not issues,'issues':issues,'screening_directory':str(directory),'candidate_records_recalculated':len(records),
        'valid_by_rate':{rate:sum(next(row for row in record['rates'] if row['rate']==rate)['valid'] for record in records) for rate in series},
        'failed_rate_attempts':sum(not attempt['valid'] for record in records for row in record['rates'] for attempt in row['attempts']),
        'cached_labels_recalculated':len(plan['parameters']),'random_dfns_replayed_without_solving':rng_replayed,
        'screening_cost':cost,'new_battery_solves':0,'api_requests':0}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    args=parser.parse_args()
    store=RunStore(workspace/'runs/screening-audits',{'screening_directory':str(args.directory.resolve())},command=' '.join(sys.argv))
    try:
        result=audit(args.directory)
        store.write_json('audit.json',result)
        store.finish('completed' if result['passed'] else 'failed',result)
        print(json.dumps({'audit_directory':str(store.path),**result},indent=2))
        raise SystemExit(0 if result['passed'] else 1)
    except Exception as exc:
        store.finish('failed',{'error_type':type(exc).__name__,'message':str(exc)})
        raise
