"""Isolated opt-in pre-header EOF rerun of the five-seed comparison."""
import run_et_three_arm_validation as runner


BASE = runner.BASE
runner.PROPOSAL = BASE / "three-arm-50round-eof-proposal-20261027"
runner.EVIDENCE = BASE / "three-arm-50round-eof-20261027"
runner.SOURCE = runner.EVIDENCE / "source"
runner.OUTPUT = runner.MAIN / "runs/g27a"
runner.CORE_FINGERPRINT = runner.helper.fingerprint(runner.WT)
runner.PLAN_COMMIT = "3b9cef2955d6e1f3f67a6a6c3c796445066b1dce"
runner.CANDIDATE_GATE = True


_load = runner.load_protocol
_dry_run = runner.dry_run


def load_eof_protocol(path=None):
    protocol = _load(path or runner.PROPOSAL / "protocol-proposal.json")
    if (protocol.get("warmstart_wire_format") != "candidate_only_v1"
            or protocol.get("warmstart_preheader_tls_eof_continue") is not True):
        raise ValueError("EOF study requires explicit candidate-only recovery policy")
    for seed in runner.SEEDS:
        config = runner._seed_config(seed)
        if (config["llm"].get("warmstart_wire_format") != "candidate_only_v1"
                or config["llm"].get("warmstart_preheader_tls_eof_continue") is not True):
            raise ValueError("every seed must share the EOF recovery policy")
    return protocol


runner.load_protocol = load_eof_protocol


def dry_run_eof(path=None, *, output=None):
    return _dry_run(path or runner.PROPOSAL / "protocol-proposal.json",
                    output=output or runner.OUTPUT)


runner.dry_run = dry_run_eof


if __name__ == "__main__":
    raise SystemExit(runner.main())
