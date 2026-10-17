"""Separate zero-default-budget electrothermal fixed-candidate/DFN smoke entry."""
import argparse
import json
import os
from pathlib import Path
import sys
for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):os.environ[name]='1'
os.environ['PYBAMM_DISABLE_TELEMETRY']='true'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from llmbo_para.electrothermal_workflow import run_electrothermal_smoke


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config',type=Path);parser.add_argument('--parameters',type=Path,required=True)
    parser.add_argument('--budget-file',type=Path);parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--output',type=Path,default=Path('runs/electrothermal-smoke'))
    args=parser.parse_args(argv)
    try:
        config=json.loads(args.config.read_text(encoding='utf-8'));points=json.loads(args.parameters.read_text(encoding='utf-8'))
        if isinstance(points,dict):points=points['parameters']
        budget=json.loads(args.budget_file.read_text(encoding='utf-8')) if args.budget_file else None
        result=run_electrothermal_smoke(config,points,args.output,base_dir=args.config.resolve().parent,budget=budget,dry_run=args.dry_run)
        print(json.dumps(result,indent=2));return 0
    except (ValueError,KeyError,OSError) as exc:print(json.dumps({'ready':False,'error':str(exc)}));return 2

if __name__=='__main__':raise SystemExit(main())
