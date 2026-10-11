"""Command-line entry points for config preflight and a clearly synthetic smoke run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import os

for _thread_setting in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS"):
    os.environ.setdefault(_thread_setting, "1")

from .config import load_json, validate_experiment_config
from .data import inspect_workbook
from .runstore import RunStore
from .synthetic import synthetic_config
from .workflow import ExperimentFailure, prepare_experiment, run_experiment, run_status, run_fixed_candidates
from .audit import audit_run


def run_synthetic_demo(output: str | Path, budget: int = 5) -> dict:
    """Exercise the orchestration without measured data, PyBaMM, LLM or GPU."""
    return run_experiment(synthetic_config(budget), output, command=f"llmbo-para demo --output {output} --budget {budget}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="llmbo-para")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate-config", help="validate a research configuration")
    validate.add_argument("config", type=Path)
    inspect = subparsers.add_parser("inspect-workbook", help="inventory workbook sheets, headers and numeric completeness")
    inspect.add_argument("workbook", type=Path)
    inspect.add_argument("--output", type=Path, default=Path("runs/data-preflight"))
    demo = subparsers.add_parser("demo", help="run a synthetic software smoke test")
    demo.add_argument("--output", type=Path, default=Path("runs"))
    demo.add_argument("--budget", type=int, default=5)
    preflight = subparsers.add_parser("preflight", help="save a complete preflight report without invoking lab plugins or APIs")
    preflight.add_argument("config", type=Path)
    preflight.add_argument("--output", type=Path, default=Path("runs/preflight"))
    run = subparsers.add_parser("run", help="execute the complete configuration-driven workflow")
    run.add_argument("config", type=Path)
    run.add_argument("--output", type=Path, default=Path("runs/experiments"))
    smoke = subparsers.add_parser("smoke", help="evaluate one explicit six-parameter candidate on all four rates without LLM/GP")
    smoke.add_argument("config", type=Path)
    smoke.add_argument("--parameters", type=Path, required=True)
    smoke.add_argument("--output", type=Path, default=Path("runs/smoke"))
    status = subparsers.add_parser("status", help="read counts, lifecycle, speed and ETA")
    status.add_argument("run_directory", type=Path)
    audit = subparsers.add_parser("audit-run", help="audit saved results into a separate new audit directory")
    audit.add_argument("run_directory", type=Path)
    audit.add_argument("--deep", action="store_true")
    audit.add_argument("--output", type=Path, default=Path("runs/result-audits"))
    retry = subparsers.add_parser("retry-failed", help="re-evaluate failed/unfinished planned candidates in a new run")
    retry.add_argument("run_directory", type=Path)
    retry.add_argument("--config", type=Path)
    retry.add_argument("--output", type=Path, default=Path("runs/recovery"))
    args = parser.parse_args(argv)
    if args.command == "validate-config":
        try:
            config = load_json(args.config)
            validate_experiment_config(config)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        print("configuration is complete and structurally valid")
    elif args.command == "inspect-workbook":
        try:
            report = inspect_workbook(args.workbook)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        store = RunStore(
            args.output,
            {"run_kind": "read_only_workbook_preflight", "source_path": report["path"]},
            data_hashes={report["path"]: report["sha256"]},
            command=f"llmbo-para inspect-workbook {args.workbook} --output {args.output}",
        )
        report_path = store.path / "inspection.json"
        with report_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        store.append_event({"type": "workbook_inspected", "report": report_path.name})
        store.finish("completed", {"inspection_report": report_path.name})
        print(json.dumps({"run_directory": str(store.path.resolve()), **report}, indent=2))
    elif args.command == "demo":
        try:
            print(json.dumps(run_synthetic_demo(args.output, args.budget), indent=2))
        except ExperimentFailure as exc:
            print(json.dumps({"run_directory": exc.run_directory, "status": exc.status, "error": str(exc)}, indent=2))
            return 2
    elif args.command in {"preflight", "run"}:
        config = load_json(args.config)
        if args.command == "preflight":
            report, prepared = prepare_experiment(config, base_dir=args.config.resolve().parent)
            store = RunStore(args.output, config, data_hashes=prepared.input_hashes if prepared else {}, command=f"llmbo-para preflight {args.config}")
            store.write_json("preflight.json", report)
            store.finish("completed" if report["ready"] else "preflight_failed", report)
            print(json.dumps({"run_directory": str(store.path), **report}, indent=2))
            return 0 if report["ready"] else 2
        try:
            result = run_experiment(config, args.output, base_dir=args.config.resolve().parent, command=f"llmbo-para run {args.config} --output {args.output}")
            print(json.dumps(result, indent=2))
        except ExperimentFailure as exc:
            print(json.dumps({"run_directory": exc.run_directory, "status": exc.status, "error": str(exc)}, indent=2))
            return 2
    elif args.command == "status":
        print(json.dumps(run_status(args.run_directory), indent=2))
    elif args.command == "smoke":
        config = load_json(args.config)
        parameters = load_json(args.parameters).get("parameters")
        try:
            print(json.dumps(run_fixed_candidates(config, args.output, [(None, parameters)], mode="smoke", base_dir=args.config.resolve().parent), indent=2))
        except ExperimentFailure as exc:
            print(json.dumps({"run_directory": exc.run_directory, "status": exc.status, "error": str(exc)}, indent=2))
            return 2
    elif args.command == "audit-run":
        report = audit_run(args.run_directory, deep=args.deep)
        store = RunStore(args.output, {"run_kind": "result_consistency_audit", "source_run": str(args.run_directory.resolve()), "deep": args.deep}, command=f"llmbo-para audit-run {args.run_directory} --deep={args.deep}")
        store.write_json("audit.json", report)
        store.finish("completed" if report["passed"] else "failed", report)
        print(json.dumps({"audit_directory": str(store.path), **report}, indent=2))
        return 0 if report["passed"] else 1
    elif args.command == "retry-failed":
        from .recovery import retry_failed
        replacement = load_json(args.config) if args.config else None
        try:
            print(json.dumps(retry_failed(args.run_directory, args.output, replacement_config=replacement), indent=2))
        except ExperimentFailure as exc:
            print(json.dumps({"run_directory": exc.run_directory, "status": exc.status, "error": str(exc)}, indent=2))
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
