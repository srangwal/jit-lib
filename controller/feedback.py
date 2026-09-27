"""Turn evaluator evidence into explicit, validated feedback for an optimizer."""

from copy import deepcopy
import math

from evaluator.core import (EvaluationError, library_qualification, self_check_calibration,
                            validate_library_reduction_target)


class FeedbackError(ValueError):
    """An evaluator report is malformed or contradicts its measurements."""


METRICS = {"application": "application_build", "index": "indexing"}
PERFORMANCE_OUTCOMES = {"improved", "slower", "inconclusive"}
COMPLETE_OUTCOMES = PERFORMANCE_OUTCOMES | {"validated", "calibration-warning"}
OUTCOMES = COMPLETE_OUTCOMES | {"incomplete", "correctness-failed"}


def _object(value, label):
    if not isinstance(value, dict):
        raise FeedbackError(f"{label} must be an object")
    return value


def _positive(value, label):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise FeedbackError(f"{label} must be positive and finite")
    return value


def _integer(value, minimum, label):
    if type(value) is not int or value < minimum:
        raise FeedbackError(f"{label} must be an integer >= {minimum}")
    return value


def _metric(raw, repetitions, label):
    raw = _object(raw, label)
    speedup = _positive(raw.get("speedup"), f"{label}.speedup")
    interval = raw.get("confidence_interval_95")
    if not isinstance(interval, list) or len(interval) != 2:
        raise FeedbackError(f"{label}.confidence_interval_95 must contain two endpoints")
    lo, hi = [_positive(value, f"{label}.confidence_interval_95") for value in interval]
    if lo > hi:
        raise FeedbackError(f"{label} has reversed confidence interval endpoints")
    verdict = "improved" if lo > 1 else "slower" if hi < 1 else "inconclusive"
    if raw.get("verdict") != verdict:
        raise FeedbackError(f"{label} verdict contradicts its confidence interval")
    pairs = _integer(raw.get("pairs"), 3, f"{label}.pairs")
    if pairs != repetitions:
        raise FeedbackError(f"{label} pairs do not match configured repetitions")
    medians = {key: _positive(raw.get(key), f"{label}.{key}") for key in (
        "original_median_seconds", "candidate_median_seconds")}
    reduction, lower, upper = [100 - 100 / value for value in (speedup, lo, hi)]
    if not all(math.isfinite(value) for value in (reduction, lower, upper)):
        raise FeedbackError(f"{label} percentage conversion is not finite")
    if verdict == "improved":
        reason = "interval_above_no_change"
        explanation = "The entire 95% speedup interval is above 1; improvement exceeds measured uncertainty."
    elif verdict == "slower":
        reason = "interval_below_no_change"
        explanation = "The entire 95% speedup interval is below 1; slowdown exceeds measured uncertainty."
    else:
        reason = "interval_includes_no_change"
        explanation = "The 95% speedup interval includes 1; these measurements do not establish improvement or slowdown."
    return {
        "verdict": verdict,
        **medians,
        "paired_blocks": pairs,
        "samples_per_variant": pairs,
        "speedup_ratio": speedup,
        "speedup_interval_95": [lo, hi],
        "time_reduction_percent": reduction,
        "time_reduction_interval_95": [lower, upper],
        # Signed offsets also work when a small bootstrap sample puts the point
        # estimate outside its percentile interval; do not fabricate symmetric errors.
        "interval_offsets_percentage_points": {
            "lower": lower - reduction, "upper": upper - reduction,
        },
        "reason_code": reason,
        "explanation": (f"Estimated time reduction is {reduction:.2f}%; its 95% interval is "
                        f"[{lower:.2f}%, {upper:.2f}%]. {explanation}"),
    }


def _measurement(config):
    config = _object(config, "configuration")
    if "library_reduction_target_percent" in config:
        try:
            validate_library_reduction_target(config["library_reduction_target_percent"])
        except EvaluationError as exc:
            raise FeedbackError(str(exc)) from exc
    repetitions = _integer(config.get("repetitions"), 3, "configuration.repetitions")
    warmups = _integer(config.get("warmups"), 0, "configuration.warmups")
    resamples = _integer(config.get("bootstrap_resamples"), 1, "configuration.bootstrap_resamples")
    seed = config.get("bootstrap_seed")
    if type(seed) is not int:
        raise FeedbackError("configuration.bootstrap_seed must be an integer")
    return {
        "paired_blocks_per_book": repetitions,
        "warmups_per_variant_per_book": warmups,
        "confidence_level": 0.95,
        "method": "paired_bootstrap_over_complete_blocks",
        "bootstrap_resamples": resamples,
        "bootstrap_seed": seed,
        "aggregation": "equal_weight_geometric_mean_across_books",
        "aggregate_median_semantics": "Median of per-block geometric mean durations across books; not total elapsed time.",
        "speedup_semantics": "Geometric mean of paired original/candidate duration ratios; not a ratio of medians.",
        "time_reduction_formula": "100 * (1 - 1 / speedup_ratio)",
        "timers": {
            "application_build": "External elapsed time of mdBook build; destination cleanup and output comparison are outside the timer.",
            "indexing": "Internal replay timer for library indexing and serialization of captured mdBook calls; compilation and correctness comparison are outside the timer.",
        },
        "scope": "Repeated timing uncertainty for these books on this machine; not a guarantee for other workloads or machine drift.",
        "configuration": deepcopy(config),
    }


def evaluation_feedback(report):
    """Validate a report and return rich feedback, without guessing failure causes.

    Artifact paths/hashes and candidate/evaluator identities are validated by the
    caller. This adapter validates the report's internal measurement consistency.
    No report or referenced artifact is modified.
    """
    report = _object(report, "report")
    outcome = report.get("status")
    if not isinstance(outcome, str) or outcome not in OUTCOMES:
        raise FeedbackError(f"Unknown evaluator status: {outcome!r}")
    mode = report.get("mode")
    if mode not in {"run", "self-check"}:
        raise FeedbackError("Evaluator mode must be run or self-check")
    if outcome in COMPLETE_OUTCOMES:
        if (outcome in PERFORMANCE_OUTCOMES) != (mode == "run"):
            raise FeedbackError("Evaluator status contradicts its mode")
        if report.get("error"):
            raise FeedbackError("A completed evaluator report contains an error")
    measurement = _measurement(report.get("configuration"))
    legacy = "library_reduction_target_percent" not in report["configuration"]
    target = report["configuration"].get("library_reduction_target_percent")
    decision_rule = (
        "Legacy evidence: both aggregate metrics must have a 95% speedup interval entirely above 1. "
        "This historical report has no library reduction target and is not reclassified under the new rule."
        if legacy else
        f"The lower 95% bound of aggregate library-work time reduction must meet the {target:g}% target "
        "and exceed zero. Application performance is reported separately and does not block library success."
    ) + " Individual-book regressions remain visible and do not change the aggregate rule."
    checks = _object(report.get("correctness", {}), "correctness")
    for book, check in checks.items():
        if not isinstance(book, str) or not book:
            raise FeedbackError("Correctness book IDs must be nonempty strings")
        check = _object(check, f"correctness.{book}")
        _integer(check.get("files"), 1, f"correctness.{book}.files")
        for field in ("repeat_identical", "candidate_identical", "capture_identical", "index_replay_identical"):
            if type(check.get(field)) is not bool:
                raise FeedbackError(f"correctness.{book}.{field} must be boolean")
            if field != "index_replay_identical" and not check[field]:
                raise FeedbackError(f"Recorded completed correctness check failed: {book}.{field}")
    if outcome in COMPLETE_OUTCOMES and not checks:
        raise FeedbackError("Completed evaluation has no correctness evidence")
    correctness_status = ("failed" if outcome == "correctness-failed" else
                          "not_completed" if outcome == "incomplete" else
                          "passed" if checks else "not_completed")
    feedback = {
        "schema_version": "evaluator-feedback/v1",
        "execution_status": "failed" if outcome == "incomplete" else "completed",
        "outcome": outcome,
        "mode": mode,
        "correctness": {
            "status": correctness_status,
            "completed_books": deepcopy(checks),
            "completed_book_count": len(checks),
            "failures": ([{"message": report.get("error", "Correctness failed; inspect evaluation evidence.")}]
                         if outcome == "correctness-failed" else []),
            "upstream_suites": deepcopy(report.get("suites", {})),
            "checker_validation": deepcopy(report.get("checker_validation", {})),
            "detail": "Completed book checks are preserved. A later timed-output or integrity check can still fail the run.",
        },
        "performance": {
            "status": "not_measured",
            "aggregate": {}, "per_book": {}, "regressions": [],
            "measurement": measurement,
            "decision_rule": decision_rule,
            "qualification": {
                "criterion": "legacy-both-metrics/v1" if legacy else "library-time-reduction/v1",
                "legacy": legacy,
                "library_reduction_target_percent": target,
                "time_reduction_lower_bound_95_percent": None,
                "meets_target": None,
                "met": False,
                "application_blocks_success": legacy,
                "reason_code": "not_measured",
                "explanation": "No complete timing analysis is available for qualification.",
                "scope": "Evaluator performance and correctness gate only; the controller also requires a resolved, clean audit.",
            },
            "environment": deepcopy(report.get("environment", {})),
        },
        "error": report.get("error"),
    }
    analysis = report.get("analysis")
    if analysis is None:
        if outcome in COMPLETE_OUTCOMES:
            raise FeedbackError("Completed evaluation has no timing analysis")
        feedback["performance"]["explanation"] = "No complete timing analysis is available; missing measurements are not an inconclusive performance result."
        feedback["summary"] = report.get("error") or "Evaluation did not produce complete measurements."
        return feedback
    analysis = _object(analysis, "analysis")
    aggregate = _object(analysis.get("aggregate"), "analysis.aggregate")
    books = _object(analysis.get("books"), "analysis.books")
    if not books:
        raise FeedbackError("Timing analysis contains no books")
    if set(aggregate) != set(METRICS):
        raise FeedbackError("Aggregate analysis must contain exactly application and index metrics")
    performance = feedback["performance"]
    repetitions = measurement["paired_blocks_per_book"]
    performance["aggregate"] = {name: _metric(aggregate[key], repetitions, f"aggregate.{key}")
                                for key, name in METRICS.items()}
    for book, metrics in books.items():
        if not isinstance(book, str) or not book:
            raise FeedbackError("Timing book IDs must be nonempty strings")
        if set(_object(metrics, f"analysis.books.{book}")) != set(METRICS):
            raise FeedbackError(f"Book {book} must contain exactly application and index metrics")
        if book not in checks or not checks[book]["index_replay_identical"]:
            raise FeedbackError(f"Timing book {book} has no passed indexing correctness evidence")
        performance["per_book"][book] = {
            name: _metric(metrics[key], repetitions, f"books.{book}.{key}")
            for key, name in METRICS.items()}
        for metric, result in performance["per_book"][book].items():
            if result["verdict"] == "slower" or result["speedup_ratio"] < 1:
                performance["regressions"].append({
                    "book": book, "metric": metric,
                    "classification": ("confirmed_slowdown" if result["verdict"] == "slower"
                                       else "point_estimate_slowdown_not_established"),
                    **deepcopy(result),
                })
    for key in METRICS:
        combined = math.exp(sum(math.log(values[key]["speedup"]) for values in books.values()) / len(books))
        if not math.isclose(aggregate[key]["speedup"], combined, rel_tol=1e-9):
            raise FeedbackError(f"Aggregate {key} speedup contradicts equal-weight book results")
    qualification = performance["qualification"]
    index = performance["aggregate"]["indexing"]
    qualification["time_reduction_lower_bound_95_percent"] = index["time_reduction_interval_95"][0]
    if legacy:
        expected = ("improved" if all(value["verdict"] == "improved" for value in aggregate.values())
                    else "slower" if any(value["verdict"] == "slower" for value in aggregate.values())
                    else "inconclusive")
        qualification.update(reason_code="legacy_rule", explanation=decision_rule)
    else:
        policy = library_qualification(aggregate["index"], target)
        if analysis.get("performance_policy") != policy:
            raise FeedbackError("Analysis performance policy contradicts the configured target or indexing measurements")
        expected = policy["verdict"]
        lower = policy["time_reduction_confidence_interval_95"][0]
        qualification.update(time_reduction_lower_bound_95_percent=lower,
                             meets_target=policy["meets_target"])
        if policy["meets_target"]:
            reason, explanation = "library_target_met", (
                f"The lower 95% library-work time-reduction bound is {lower:.2f}%, meeting the {target:g}% target "
                "and exceeding zero. Application performance does not block library success.")
        elif index["verdict"] == "improved":
            reason, explanation = "library_improved_below_target", (
                f"Library work improved beyond measurement noise, but its lower 95% time-reduction bound "
                f"of {lower:.2f}% falls below the {target:g}% target. The required reduction is not established.")
        elif index["verdict"] == "slower":
            reason, explanation = "library_slower", "Library work is measurably slower; the library improvement target is not met."
        else:
            reason, explanation = "library_improvement_not_established", (
                "The library-work confidence interval includes no change; an improvement beyond noise is not established.")
        qualification.update(reason_code=reason, explanation=explanation)
    if analysis.get("verdict") != expected:
        raise FeedbackError("Analysis verdict contradicts the aggregate performance rule")
    if outcome in PERFORMANCE_OUTCOMES and outcome != expected:
        raise FeedbackError("Evaluator status contradicts its analysis verdict")
    if outcome in {"validated", "calibration-warning"}:
        if "calibration_policy" in report:
            policy = self_check_calibration(aggregate)
            if report["calibration_policy"] != policy:
                raise FeedbackError("Self-check calibration policy contradicts measurements or the 5% tolerance")
            performance["calibration"] = deepcopy(policy)
            calibrated = policy["passed"]
        else:
            # Preserve historical evidence under the rule that produced it.
            calibrated = all(value["verdict"] == "inconclusive" for value in aggregate.values())
        if (outcome == "validated") != calibrated:
            raise FeedbackError("Self-check status contradicts calibration measurements")
    performance["status"] = "measured" if outcome in COMPLETE_OUTCOMES else "run_invalid"
    performance["aggregate_verdict"] = expected
    qualification["met"] = mode == "run" and outcome == "improved"
    if mode == "self-check":
        rule = (
            "Both aggregate measured time differences must be within +/-5% of original time, inclusive; "
            "confidence intervals do not determine calibration."
            if "calibration_policy" in report else
            "Historical self-check: both aggregate intervals must include no change."
        )
        performance["decision_rule"] = rule
        qualification.update(met=False, reason_code="self_check_calibration",
                             explanation=f"This original-versus-original run checks calibration. {rule} It cannot qualify a candidate.")
    if performance["status"] == "run_invalid":
        qualification.update(met=False, reason_code="run_invalid",
                             explanation="The evaluation failed; retained measurements cannot qualify a candidate.")
    measurement["books_measured"] = len(books)
    feedback["summary"] = " ".join(
        f"{name}: {value['explanation']}" for name, value in performance["aggregate"].items())
    feedback["summary"] += " " + qualification["explanation"]
    if performance["regressions"]:
        feedback["summary"] += f" Individual-book slowdown signals: {len(performance['regressions'])}; inspect regressions."
    if performance["status"] == "run_invalid":
        feedback["summary"] = "Run failed; retained analysis is not eligible for acceptance. " + feedback["summary"]
    return feedback
