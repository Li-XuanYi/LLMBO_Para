"""Offline, train-only LLM prior request and matched chronological GP replay.

Never imports an evaluator or launches DFN. Archived adaptive points are a
development check, not a new BO trajectory or an independent efficacy test.
"""
from __future__ import annotations
import argparse
from contextlib import redirect_stdout, redirect_stderr
import getpass
import json
import math
import os
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[name] = "1"
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import numpy as np
from llmbo_para.acquisition import composite_ei
from llmbo_para.audit import read_json
from llmbo_para.bo_repair import decision_scores, select_candidate
from llmbo_para.config import parameter_space_from_config
from llmbo_para.llm import LLMClient, ChatCompletionsTransport
from llmbo_para.llm_gp_prior import build_payload, make_prior, request_priors, validate_response
from llmbo_para.metrics import RATE_ORDER, LogRMSETransform
from llmbo_para.runstore import RunStore, digest_value, sha256_file
from llmbo_para.surrogate import Matern52GP
from resource_snapshot import snapshot

ARCHIVE = ROOT / "runs/gp-matched-pilots/20261015T113301Z_18c528dbb082_296c6b74/optimization"
DEFAULT_SOURCE = ARCHIVE / "full_kernel/20261015T113331Z_652819910ef7_b45e560d"
DEFAULT_CONTEXT = ARCHIVE / "llm_gp/20261015T113412Z_a76d43167b31_2b7d0b6b/llm/rate_parameter_groups.request.json"
ARMS = ("mle", "generic_map", "llm_map")
STARTS = (0.1, 0.35, 1.0)


def source_files(source, context):
    files = [source / "manifest.json", context]
    files += sorted((source / "attempts").glob("*.json"))
    files += sorted((source / "screening-history").glob("*.json"))
    files += [source / f"models/after-{i:06d}.json" for i in range(8, 13)]
    files += [source / f"acquisition/candidate-{i:06d}.json" for i in range(8, 13)]
    return files


def initial_records(source):
    records = [(f"initial-{i}", read_json(source / f"attempts/candidate-{i:06d}-attempt-001.json")) for i in range(8)]
    records += [(f"screening-{i}", read_json(path)) for i, path in enumerate(sorted((source / "screening-history").glob("record-*.json")))]
    return records


def check_training_alignment(source, space, records):
    """Every transmitted label belongs to initial GP data, including partials."""
    initial = read_json(source / "models/after-000008.json")
    for rate in RATE_ORDER:
        transform = LogRMSETransform(**initial["transforms"][rate])
        expected = []
        for _, record in records:
            q = next(q for q in record["rates"] if q["rate"] == rate)
            if q["valid"]:
                expected.append([*space.normalize(record["parameters"]), transform.transform(q["rmse_v"])])
        observed = np.column_stack((initial["models"][rate]["x"], initial["models"][rate]["y"]))
        assert len(expected) == len(observed)
        # Compare by rows, not archive order (screening and initial are stored separately).
        for row in expected:
            assert np.any(np.all(np.isclose(observed, row, rtol=0, atol=1e-11), axis=1)), rate


def check_replay_alignment(source, space, index, saved, acquisition, actual):
    """Match the full chronological train set and the single held-out point."""
    assert saved["transforms"] == read_json(source / "models/after-000008.json")["transforms"], "output transforms must stay frozen at initialization"
    expected_x = space.normalize(actual["parameters"])
    selected_x = acquisition["normalized_pool"][acquisition["selected_index"]]
    np.testing.assert_allclose(expected_x, selected_x, rtol=0, atol=1e-12)
    past = initial_records(source) + [(f"past-{j}", read_json(source / f"attempts/candidate-{j:06d}-attempt-001.json")) for j in range(8, index)]
    for rate in RATE_ORDER:
        transform = LogRMSETransform(**saved["transforms"][rate])
        expected = []
        for _, record in past:
            q = next(q for q in record["rates"] if q["rate"] == rate)
            if q["valid"]:
                expected.append([*space.normalize(record["parameters"]), transform.transform(q["rmse_v"])])
        observed = np.column_stack((saved["models"][rate]["x"], saved["models"][rate]["y"]))
        np.testing.assert_allclose(sorted(expected), sorted(observed.tolist()), rtol=0, atol=1e-11)


def fit_multistart(store, state, prior, cache):
    key = digest_value({"x": state["x"], "y": state["y"], "prior": prior,
                        "starts": STARTS, "sweeps": 320, "jitter": state["jitter"]})
    if key in cache:
        return cache[key], key
    fits, diagnostics = [], []
    for start in STARTS:
        t = time.perf_counter()
        model = Matern52GP(max_sweeps=320, jitter=state["jitter"], max_lambda=state["max_lambda"],
                          lengthscale_prior=prior, initial_lengthscale=start).fit(state["x"], state["y"])
        fits.append(model)
        diagnostics.append({"initial_lengthscale": start, "elapsed_s": time.perf_counter() - t,
                            "model": model.state_dict()})
    selected = max(range(len(fits)), key=lambda i: fits[i].optimization_objective)
    store.write_json(f"fits/{key}.json", {"starts": diagnostics, "selected_start": selected,
        "selection": "maximum own training MLL or MAP objective; no validation label used"})
    cache[key] = fits[selected]
    return cache[key], key


def prediction_row(model, transform, x, observed_v):
    mean, latent_sd = model.predict(np.asarray([x]))
    sd = math.sqrt(float(latent_sd[0]) ** 2 + math.exp(2 * model.params[7]))
    z = transform.transform(observed_v)
    error = (z - float(mean[0])) / sd
    median = transform.inverse_sample(float(mean[0]))
    lower = transform.inverse_sample(float(mean[0]) - 1.96 * sd)
    upper = transform.inverse_sample(float(mean[0]) + 1.96 * sd)
    return {"actual_rmse_v": observed_v, "predicted_median_v": median,
            "absolute_error_mV": abs(median - observed_v) * 1000,
            "covered_95": bool(abs(error) <= 1.96), "interval_95_v": [lower, upper],
            "interval_width_mV": (upper - lower) * 1000,
            "nlpd_standardized_log": .5 * math.log(2 * math.pi * sd * sd) + .5 * error * error,
            "mean_standardized_log": float(mean[0]), "latent_std_standardized_log": float(latent_sd[0]),
            "observation_std_standardized_log": sd}


def replay(store, source, validated):
    rows, decisions, fit_rows, cache = [], [], [], {}
    started = time.perf_counter()
    source_config = read_json(source / "manifest.json")["config"]
    space = parameter_space_from_config(source_config)
    for index in range(8, 13):
        saved = read_json(source / f"models/after-{index:06d}.json")
        acquisition = read_json(source / f"acquisition/candidate-{index:06d}.json")
        actual = read_json(source / f"attempts/candidate-{index:06d}-attempt-001.json")
        check_replay_alignment(source, space, index, saved, acquisition, actual)
        x = acquisition["normalized_pool"][acquisition["selected_index"]]
        transforms = {r: LogRMSETransform(**saved["transforms"][r]) for r in RATE_ORDER}
        models = {a: {} for a in ARMS}
        for rate in RATE_ORDER:
            state = saved["models"][rate]
            for arm, prior in (("mle", None), ("generic_map", make_prior()),
                               ("llm_map", validated[rate]["lengthscale_prior"])):
                model, key = fit_multistart(store, state, prior, cache)
                models[arm][rate] = model
                ell = np.exp(model.params[:6])
                fit_rows.append({"iteration": index - 7, "rate": rate, "arm": arm,
                    "fit_id": key, "n_train": len(state["x"]), "lengthscales": ell.tolist(),
                    "bound_count": int(sum(np.isclose(ell, .03) | np.isclose(ell, 8))),
                    "noise_std": math.exp(model.params[7]),
                    "converged": model.fit_diagnostics["step_tolerance_reached"]})
                q = next(q for q in actual["rates"] if q["rate"] == rate)
                if q["valid"]:
                    rows.append({"iteration": index - 7, "rate": rate, "arm": arm,
                                 **prediction_row(model, transforms[rate], x, q["rmse_v"])})
        for arm in ARMS:
            ei = composite_ei(acquisition["normalized_pool"], models[arm], transforms,
                 acquisition["best_observed_objective_v"], draws=acquisition["mc_draws"], seed=acquisition["mc_seed"])
            scores, policy, fallback = decision_scores(ei, acquisition["p_complete"], enabled=True)
            chosen = select_candidate(scores, acquisition["proposal"]["eligible"],
                     seed=source_config["optimization"]["seed"], candidate_id=index)
            decisions.append({"iteration": index - 7, "arm": arm, "selected_index": chosen,
                "archived_selected_index": acquisition["selected_index"], "policy": policy, "fallback": fallback,
                "selected_normalized": acquisition["normalized_pool"][chosen],
                "composite_ei": ei.tolist(), "decision_scores": scores.tolist(),
                "outcome_for_alternative_choice": "not evaluated; no counterfactual BO result"})
        store.write_json(f"steps/before-{index:06d}.json", {
            "training_alignment_passed": True,
            "predictions": [v for v in rows if v["iteration"] == index - 7],
            "decisions": [v for v in decisions if v["iteration"] == index - 7],
            "fit_references": [v for v in fit_rows if v["iteration"] == index - 7]})
        done = index - 7; elapsed = time.perf_counter() - started
        progress = {"completed_replay_steps": done, "running": 0, "errors": 0, "pending": 5 - done,
                    "seconds_per_step": elapsed / done, "eta_seconds": elapsed / done * (5 - done),
                    "new_dfn_solves": 0, "unique_fits": len(cache) * len(STARTS)}
        store.append_event({"type": "replay_progress", **progress})
        print(json.dumps(progress), flush=True)
    metrics = {}
    for arm in ARMS:
        metrics[arm] = {}
        for rate in (*RATE_ORDER, "pooled"):
            subset = [row for row in rows if row["arm"] == arm and (rate == "pooled" or row["rate"] == rate)]
            metrics[arm][rate] = {"n_unique_rate_labels": len(subset),
                "prediction_mae_mV": float(np.mean([v["absolute_error_mV"] for v in subset])),
                "coverage_95": float(np.mean([v["covered_95"] for v in subset])),
                "mean_interval_width_mV": float(np.mean([v["interval_width_mV"] for v in subset])),
                "mean_nlpd_standardized_log": float(np.mean([v["nlpd_standardized_log"] for v in subset]))}
    result = {"metrics": metrics, "unique_chronological_points": 5,
        "unique_valid_rate_labels": len(rows) // len(ARMS), "new_dfn_solves": 0,
        "fitting_starts_evaluated": len(cache) * len(STARTS),
        "llm_informative_by_rate": {r: validated[r]["informative"] for r in RATE_ORDER},
        "fit_bound_counts": {a: sum(v["bound_count"] for v in fit_rows if v["arm"] == a) for a in ARMS},
        "selected_fits_converged": all(v["converged"] for v in fit_rows),
        "all_starts_converged": all(start["model"]["fit_diagnostics"]["step_tolerance_reached"]
            for path in (store.path / "fits").glob("*.json") for start in read_json(path)["starts"]),
        "acquisition_changed_llm_vs_generic": sum(
            next(v for v in decisions if v["iteration"] == i and v["arm"] == "llm_map")["selected_index"] !=
            next(v for v in decisions if v["iteration"] == i and v["arm"] == "generic_map")["selected_index"] for i in range(1, 6)),
        "elapsed_s": time.perf_counter() - started,
        "interpretation": "Retrospective chronological development replay on one adaptive trajectory, with fixed train-only LLM priors. No independent replication, causal BO improvement, significance claim, or new voltage RMSE is established."}
    store.write_json("predictions.json", rows)
    store.write_json("acquisition-replay.json", decisions)
    store.write_json("fit-summary.json", fit_rows)
    store.write_json("result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--context", type=Path, default=DEFAULT_CONTEXT)
    parser.add_argument("--prior-response", type=Path, help="Reuse archived structured priors; zero new API calls")
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--output", type=Path, default=ROOT / "runs/gp-prior-offline")
    args = parser.parse_args()
    source = args.source.resolve()
    config = read_json(source / "manifest.json")["config"]
    space = parameter_space_from_config(config)
    records = initial_records(source)
    check_training_alignment(source, space, records)
    payload = build_payload(space, records)
    context = read_json(args.context)["context"]
    # Correct the archive's ambiguous label without changing any physical input.
    for q in context["discharge_summary_by_rate"].values():
        q["current_source"] = "assumed nominal 5 Ah times C-rate; XLSX current column blank"
    inputs = source_files(source, args.context)
    if args.prior_response:
        inputs.append(args.prior_response.resolve())
    hashes = {str(p): sha256_file(p) for p in inputs}
    protocol = {"kind": "offline_full_ard_llm_prior", "source": str(source),
        "arms": list(ARMS), "starts": STARTS, "max_sweeps": 320, "generic_prior": make_prior(),
        "training_record_ids": [v[0] for v in records], "llm_train_payload_sha256": digest_value(payload),
        "api_settings": config["llm"], "proxy": args.proxy, "max_api_requests": 0 if args.prior_response else 2,
        "prior_response_source": str(args.prior_response.resolve()) if args.prior_response else None,
        "new_dfn_budget": 0, "new_bo_budget": 0, "workers": 1,
        "selection_rule": "predeclared fixed priors; identical multistart budget; no held-out tuning"}
    store = RunStore(args.output, protocol, command="python scripts/compare_full_ard_priors.py " + " ".join(sys.argv[1:]), data_hashes=hashes)
    print(f"RUN_DIRECTORY={store.path}", flush=True)
    api_key_env = config["llm"]["api_key_env"]
    try:
        store.write_json("resources-before.json", snapshot())
        store.write_json("preflight.json", {"initial_gp_alignment": True, "n_training_records": len(records),
            "training_summary": payload["training_summary"], "scope": "offline only; no evaluator imported"})
        if not args.prior_response and not os.environ.get(api_key_env):
            os.environ[api_key_env] = getpass.getpass("API credential (memory only): ")
        with (store.path / "stdout.log").open("x", encoding="utf-8", buffering=1) as log, redirect_stdout(log), redirect_stderr(log):
            if args.prior_response:
                response = read_json(args.prior_response)
                validated = validate_response(response, {v[0] for v in records})
                store.write_json("reused-prior-response.json", response)
            else:
                os.environ["HTTPS_PROXY"] = args.proxy; os.environ["HTTP_PROXY"] = args.proxy
                settings = config["llm"]
                transport = ChatCompletionsTransport(settings["endpoint"], api_key_env, model=settings["model"],
                    max_tokens=settings["max_tokens"], json_mode=settings["json_mode"], timeout_s=settings["timeout_s"],
                    thinking=settings.get("thinking"), run_store=store)
                validated = request_priors(LLMClient(transport, context=context, run_store=store), space, records)
            store.write_json("validated-priors.json", validated)
            result = replay(store, source, validated)
            assert hashes == {str(p): sha256_file(p) for p in inputs}, "source archives changed during replay"
            store.write_json("source-integrity.json", {"unchanged": True, "sha256": hashes})
            store.write_json("resources-after.json", snapshot())
            store.finish("completed", result)
    except BaseException as exc:
        store.write_json("failure.json", {"error_type": type(exc).__name__, "traceback": traceback.format_exc()})
        if not (store.path / "terminal.json").exists():
            store.finish("failed", {"error_type": type(exc).__name__, "new_dfn_solves": 0})
        raise
    finally:
        os.environ.pop(api_key_env, None)
    # Logs are closed before checksumming; manifest excludes its own output.
    store.write_json("deliverable-sha256.json", {str(p.relative_to(store.path)): sha256_file(p)
        for p in store.path.rglob("*") if p.is_file()})
    print(json.dumps({"run_directory": str(store.path), "metrics": result["metrics"], "new_dfn_solves": 0}), flush=True)


if __name__ == "__main__":
    main()
