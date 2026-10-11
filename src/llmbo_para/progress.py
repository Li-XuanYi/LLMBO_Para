"""Human-readable counts and measured throughput for run status reports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
import math

from .metrics import RATE_ORDER


@dataclass(frozen=True)
class Progress:
    total_candidates: int
    completed_candidates: int
    failed_candidates: int
    running_candidates: int
    candidate_rate_per_min: float | None
    eta_minutes: float | None
    completed_by_rate: dict[str, int]
    failed_by_rate: dict[str, int]
    pending_candidates: int


def summarize_progress(total: int, records: Iterable[dict], elapsed_s: float, running: int = 0) -> Progress:
    if total < 0 or elapsed_s < 0 or running < 0:
        raise ValueError("progress counts and elapsed time must be non-negative")
    items = list(records)
    completed = len(items)
    failed = sum(not bool(r.get("valid")) for r in items)
    done_by_rate = {rate: 0 for rate in RATE_ORDER}
    failed_by_rate = {rate: 0 for rate in RATE_ORDER}
    for record in items:
        for result in record.get("rates", []):
            rate = result.get("rate")
            if rate in done_by_rate:
                done_by_rate[rate] += 1
                if not result.get("valid"):
                    failed_by_rate[rate] += 1
    if completed + running > total:
        raise ValueError("completed plus running candidates exceeds the budget")
    remaining = total - completed
    newly_evaluated = sum(not row.get("cache_provenance") for row in items)
    throughput = newly_evaluated * 60.0 / elapsed_s if newly_evaluated and elapsed_s > 0 else None
    eta = remaining / throughput if throughput and math.isfinite(throughput) else None
    return Progress(total, completed, failed, running, throughput, eta, done_by_rate, failed_by_rate, remaining - running)
