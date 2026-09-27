"""Candidate eligibility, optimizer ambition, and final ranking."""

MIN_ATTEMPTS = 3
MAX_ATTEMPTS = 5
STRETCH_MULTIPLIER = 1.5
STRETCH_CEILING_PERCENT = 95


def eligible_candidates(reviewed, version):
    """Use complete independent measurements and clean audits of frozen code."""
    return [entry for entry in reviewed
            if entry["evaluation"]["evaluator_version"] == version
            and entry["evaluation"]["status"] in {"improved", "inconclusive", "slower"}
            and entry["evaluation"]["feedback"]["correctness"]["status"] == "passed"
            and entry["audit"]["status"] == "no-issue-found"]


def indexing(entry):
    return entry["evaluation"]["feedback"]["performance"]["aggregate"]["indexing"]


def stretch_target(acceptance, reviewed, version):
    eligible = eligible_candidates(reviewed, version)
    best = max(eligible, key=lambda entry: indexing(entry)["time_reduction_percent"], default=None)
    measured = indexing(best)["time_reduction_percent"] if best else None
    target = acceptance if best is None else max(
        acceptance, min(STRETCH_CEILING_PERCENT, STRETCH_MULTIPLIER * measured))
    return {
        "schema_version": "optimizer-stretch-target/v1",
        "time_reduction_percent": target,
        "acceptance_threshold_percent": acceptance,
        "multiplier": STRETCH_MULTIPLIER,
        "ceiling_percent": STRETCH_CEILING_PERCENT,
        "best_previous": None if best is None else {
            "candidate_id": best["candidate"]["candidate_id"],
            "time_reduction_percent": measured,
            "evaluation": best["evaluation"]["result_ref"],
            "audit": best["audit"]["result_ref"],
        },
    }


def qualifying_candidates(reviewed, version):
    return [entry for entry in eligible_candidates(reviewed, version)
            if entry["evaluation"]["status"] == "improved"
            and entry["evaluation"]["feedback"]["performance"]["qualification"]["met"]]


def best_qualifier(reviewed, version):
    # max retains the earliest candidate on an exact tie. Entries are chronological.
    return max(qualifying_candidates(reviewed, version),
               key=lambda entry: indexing(entry)["time_reduction_interval_95"][0], default=None)
