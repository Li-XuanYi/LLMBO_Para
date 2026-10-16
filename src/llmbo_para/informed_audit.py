"""Offline replay of region suggestions; never requests an LLM or a simulator."""
from dataclasses import asdict
import json
import math
import numpy as np

from .evaluation import EvaluationResult, RateResult
from .informed import InformedSettings, observation_summary, region_decision, trust_feedback, validate_region_response
from .metrics import LogRMSETransform
from .runstore import digest_value
from .surrogate import Matern52GP


def equivalent(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(equivalent(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(equivalent(x,y) for x,y in zip(a,b))
    if type(a) in (int,float) and type(b) in (int,float):
        return math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-12)
    return a == b


def replay_informed_step(root, *, options, candidate_id, initial_count, state, row, attempts,
                         space, ready, probabilities, gate, trust, stats, issues):
    def read(path):
        return json.loads(path.read_text(encoding="utf-8"))

    def check(condition, message):
        if not condition:
            issues.append(f"candidate-{candidate_id:06d}: LLM-Informed {message}")

    settings = InformedSettings.parse(options.get("llm_informed"))
    relative = f"informed/candidate-{candidate_id:06d}.json"
    check(row.get("informed_artifact") == relative, "artifact path differs")
    envelope = read(root/relative)
    ordinal = candidate_id-initial_count
    check(envelope["candidate_id"] == candidate_id and envelope["iteration"] == ordinal, "iteration differs")
    check(envelope["settings"] == asdict(settings), "settings differ from configuration")
    check(equivalent(envelope["trust_before"], trust), "trust does not follow actual previous outcomes")
    requested = ready and ordinal < settings.active_until
    request = envelope["request"]
    preference = None
    if requested:
        check(envelope["status"] in {"evaluated","llm_error","lift_error"} and isinstance(request,dict), "missing active request")
        stats["requested_iterations"] += 1
        count = request["attempts"]
        check(type(count) is int and 1 <= count <= 2, "request attempt count outside [1,2]")
        if type(count) is not int or not 1 <= count <= 2:
            raise ValueError("invalid informed request attempt count")
        stats["request_attempts"] += count
        check(request["iteration"] == ordinal, "request iteration differs")
        records = [EvaluationResult(tuple(r["parameters"]),tuple(RateResult(**q) for q in r["rates"]),r["valid"],r["objective_v"]) for r in attempts[:candidate_id]]
        expected_observations = observation_summary(space, records)
        prompt = (root/"source/src/llmbo_para/prompts/region_preference.txt").read_text(encoding="utf-8")
        import hashlib
        previous_response = None
        final_response_valid = False
        for attempt in range(1,count+1):
            prefix = f"informed-requests/iteration-{ordinal:06d}/attempt-{attempt:03d}/"
            sent = read(root/prefix/"llm/region_preference.request.json")
            check(sent["observations"] == expected_observations, "request observations differ or contain extra data")
            check(sent["parameter_order"] == [s.name for s in space.specs] and sent["bounds"] == [[s.lower,s.upper] for s in space.specs]
                and sent["units"] == [s.unit for s in space.specs] and sent["transforms"] == [s.transform for s in space.specs], "request parameter definitions differ")
            check(sent["iteration"] == ordinal and sent["task"] == "region_preference", "request identity differs")
            check(sent["instructions"] == prompt and sent["prompt_sha256"] == hashlib.sha256(prompt.encode()).hexdigest(), "prompt differs from source snapshot")
            if attempt > 1:
                check(sent.get("contract_repair",{}).get("previous_response") == previous_response, "schema repair lost prior response")
            response_path = root/prefix/"llm/region_preference.response.json"
            if response_path.exists() and (root/prefix/"validation.json").exists():
                response = read(response_path)
                content = response.get("content",response)
                if isinstance(content,str):
                    content=json.loads(content)
                previous_response = content
                try:
                    preference = validate_region_response(content)
                    final_response_valid = True
                except ValueError:
                    preference = None
                    final_response_valid = False
                validation = read(root/prefix/"validation.json")
                check(validation["valid_response"] == final_response_valid, "response validation differs")
                if attempt < count:
                    check(not final_response_valid, "retried an already valid response")
            else:
                check((root/prefix/"llm/region_preference.error.json").exists(), "request has neither response nor archived error")
                check(attempt == count, "transport failure was silently retried")
                final_response_valid = False
        check(request["archive_prefix"] == prefix, "final request prefix differs")
        check(request["valid_response"] == final_response_valid, "reported response status differs")
        if final_response_valid:
            stats["valid_responses"] += 1
            check(envelope["preference"] == preference, "preference differs from actual LLM response")
        else:
            check(envelope["status"] == "llm_error" and envelope["preference"] is None, "invalid response became an active preference")
    else:
        check(request is None and envelope["preference"] is None and envelope["decision"] is None, "inactive step requested a preference")
        check(envelope["status"] == ("inactive" if ready else "gp_unavailable"), "inactive status differs")
    decision = None
    if preference is not None:
        gp = Matern52GP.from_state(state["models"]["objective"])
        transform = LogRMSETransform(**state["transforms"]["objective"])
        try:
            decision = region_decision(gp,transform,row["best_observed_objective_v"],row["normalized_pool"],row["proposal"]["eligible"],preference,
                space=space,settings=settings,trust=trust,iteration=ordinal,seed=options["seed"],candidate_id=candidate_id,
                probabilities=probabilities,feasibility_weighting=options.get("bo_repair",{}).get("feasibility_weighting",False),
                candidate_filter=gate.check if gate else None)
        except (ValueError, FloatingPointError, np.linalg.LinAlgError) as exc:
            check(envelope["status"] == "lift_error" and envelope["error_type"] == type(exc).__name__, "lift failure is not reproducible")
        else:
            check(envelope["status"] == "evaluated", "claimed lift failure but replay succeeded")
        check(equivalent(envelope["decision"],decision), "posterior, anchors, shift, guard or decision does not reproduce")
        if decision:
            check(equivalent(row["composite_ei"],decision["plain_ei_v"]), "plain EI differs from GP")
    accepted = bool(decision and decision["accepted"])
    check(row.get("informed_applied") == accepted, "adoption flag differs")
    if accepted:
        stats["adopted"] += 1
    else:
        reason = decision["fallback_reason"] if decision else envelope["status"]
        stats["fallback_counts"][reason] = stats["fallback_counts"].get(reason,0)+1
    if envelope["status"] in {"llm_error","lift_error"}:
        stats["error_iterations"] += 1
    current = attempts[candidate_id]
    feedback = trust_feedback(trust,accepted,current["valid"],current["objective_v"],row["best_observed_objective_v"],settings)
    check(equivalent(read(root/f"informed-feedback/candidate-{candidate_id:06d}.json"),feedback), "observed feedback or trust update differs")
    return decision, feedback["trust_after"]
