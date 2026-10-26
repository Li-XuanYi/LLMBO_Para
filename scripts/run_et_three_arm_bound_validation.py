"""Isolated candidate-bound rerun of the frozen five-seed comparison."""
import run_et_three_arm_validation as runner


BASE = runner.BASE
runner.PROPOSAL = BASE / "three-arm-50round-bound-proposal-20261026"
runner.EVIDENCE = BASE / "three-arm-50round-bound-20261026"
runner.SOURCE = runner.EVIDENCE / "source"
runner.OUTPUT = runner.MAIN / "runs/g26y"
runner.CORE_FINGERPRINT = runner.helper.fingerprint(runner.WT)
runner.PLAN_COMMIT = "3c27fe4db152d1be7859d037ee9420a9a770119d"
runner.CANDIDATE_GATE = True

_load = runner.load_protocol
_dry_run = runner.dry_run


def load_bound_protocol(path=None):
    protocol = _load(path or runner.PROPOSAL / "protocol-proposal.json")
    if protocol.get("warmstart_wire_format") != "candidate_only_v1":
        raise ValueError("bound study requires explicit candidate-only WarmStart")
    for seed in runner.SEEDS:
        if runner._seed_config(seed)["llm"].get("warmstart_wire_format") != "candidate_only_v1":
            raise ValueError("every seed must use the same WarmStart reply contract")
    return protocol


runner.load_protocol = load_bound_protocol


def dry_run_bound(path=None, *, output=None):
    return _dry_run(path or runner.PROPOSAL / "protocol-proposal.json",
                    output=output or runner.OUTPUT)


runner.dry_run = dry_run_bound


if __name__ == "__main__":
    raise SystemExit(runner.main())
