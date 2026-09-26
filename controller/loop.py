"""The bounded experiment policy, independent of command execution."""


def experiment(records, components, max_attempts=5):
    baseline = components.initialize()
    previous = None
    feedback = []
    for number in range(1, max_attempts + 1):
        attempt = f"attempt-{number:03d}"
        records.event("attempt_started", attempt_id=attempt, summary=f"Optimizer attempt {number}/{max_attempts}")
        optimized = components.optimize(attempt, baseline, previous, feedback)
        if optimized["status"] == "no-change":
            feedback.append(optimized["result_ref"])
            records.event("decision", attempt_id=attempt, decision="continue",
                          summary="Optimizer submitted no change; this attempt consumed its budget.",
                          evidence=optimized["result_ref"])
            continue
        if optimized["status"] != "candidate-created":
            raise RuntimeError("Optimizer did not complete; inspect its recorded result")
        candidate = optimized["candidate"]
        components.check_candidate(candidate)
        before = components.version()
        evaluation = components.evaluate(attempt, baseline, candidate)
        # Audit every candidate, including failed/incomplete evaluations. The auditor
        # may report incomplete if compilation failed before probe binaries existed.
        audit = components.audit(attempt, candidate, evaluation)
        components.check_candidate(candidate)
        after = components.version()
        feedback.extend([evaluation["result_ref"], audit["result_ref"]])
        previous = candidate
        if after != before:
            components.validate_check_change(before, after, audit)
            records.event("checks_changed", attempt_id=attempt,
                          summary="Audit added checks. Earlier evaluation results are stale for selection.",
                          evaluator_before=before, evaluator_after=after,
                          invalidated_results=[evaluation["result_ref"]],
                          invalidates_all_prior_versions=True, evidence=audit["result_ref"])
            baseline = components.refresh_baseline(attempt)
            evaluation = components.evaluate(attempt + "-recheck", baseline, candidate)
            feedback.append(evaluation["result_ref"])
            # This is the same frozen candidate. Its violation remains a violation;
            # a fresh optimizer revision will receive a new audit.
        if evaluation["status"] == "incomplete" or audit["status"] == "incomplete":
            raise RuntimeError("Evaluation or audit could not complete; no candidate was accepted")
        qualifies = evaluation["status"] == "improved" and audit["status"] == "no-issue-found"
        if qualifies:
            components.verify_qualification(baseline, candidate, evaluation, audit)
            records.verify()
            records.event("decision", attempt_id=attempt, decision="qualify",
                          summary="Correctness passed, the library time-reduction target was met with 95% confidence, and audit found no issue. Application performance is reported separately.",
                          evidence=evaluation["result_ref"], audit=audit["result_ref"],
                          candidate=candidate["manifest_ref"])
            return {"status": "qualified", "attempts": number,
                    "candidate": candidate["manifest_ref"], "evaluation": evaluation["result_ref"],
                    "audit": audit["result_ref"]}
        records.event("decision", attempt_id=attempt, decision="revise_or_restart",
                      summary=f"Not qualified: evaluation={evaluation['status']}; audit={audit['status']}. "
                              "The optimizer will choose revision or restart if budget remains.",
                      evidence=evaluation["result_ref"], feedback=audit["result_ref"])
    return {"status": "no-qualifying-improvement", "attempts": max_attempts}
