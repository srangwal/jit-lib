"""The bounded experiment policy, independent of command execution."""

from controller.policy import (MIN_ATTEMPTS, MAX_ATTEMPTS, best_qualifier, indexing,
                               qualifying_candidates, stretch_target)


def experiment(records, components, max_attempts=MAX_ATTEMPTS):
    if not MIN_ATTEMPTS <= max_attempts <= MAX_ATTEMPTS:
        raise ValueError("Experiments require three to five optimizer attempts")
    baseline = components.initialize()
    previous = None
    feedback = []
    reviewed = []
    for number in range(1, max_attempts + 1):
        attempt = f"attempt-{number:03d}"
        target = stretch_target(components.configuration["library_reduction_target_percent"],
                                reviewed, components.version())
        target_ref = records.write(f"tasks/{attempt}-stretch-target.json", target)
        records.event("attempt_started", attempt_id=attempt, evidence=target_ref,
                      summary=f"Optimizer attempt {number}/{max_attempts}; acceptance "
                              f"{target['acceptance_threshold_percent']:g}%, stretch "
                              f"{target['time_reduction_percent']:g}%.")
        optimized = components.optimize(attempt, baseline, previous, feedback, target)
        if optimized["status"] == "no-change":
            feedback.append(optimized["result_ref"])
            records.event("decision", attempt_id=attempt, decision="no_change",
                          summary="Optimizer submitted no change; this attempt consumed its budget.",
                          evidence=optimized["result_ref"])
        else:
            if optimized["status"] != "candidate-created":
                raise RuntimeError("Optimizer did not complete; inspect its recorded result")
            candidate = optimized["candidate"]
            components.check_candidate(candidate)
            before = components.version()
            evaluation = components.evaluate(attempt, baseline, candidate)
            # Audit every submitted candidate, including failed evaluations.
            audit = components.audit(attempt, candidate, evaluation)
            components.check_candidate(candidate)
            after = components.version()
            feedback.extend([evaluation["result_ref"], audit["result_ref"]])
            previous = candidate
            current = {"candidate": candidate, "evaluation": evaluation, "audit": audit}
            reviewed.append(current)
            if after != before:
                components.validate_check_change(before, after, audit)
                records.event("checks_changed", attempt_id=attempt,
                              summary="Audit added checks. Refreshing baseline and retained candidate measurements.",
                              evaluator_before=before, evaluator_after=after,
                              invalidated_results=[entry["evaluation"]["result_ref"] for entry in reviewed],
                              invalidates_all_prior_versions=True, evidence=audit["result_ref"])
                baseline = components.refresh_baseline(attempt)
                # Recheck the triggering candidate, then every earlier candidate with
                # a clean audit. A non-clean audit is never cleared by reevaluation.
                refresh = [current] + [entry for entry in reviewed[:-1]
                                       if entry["audit"]["status"] == "no-issue-found"]
                for entry in refresh:
                    old = entry["evaluation"]
                    saved = entry["candidate"]
                    label = (attempt + "-recheck" if entry is current else
                             saved["candidate_id"] + "-recheck-after-" + attempt)
                    components.check_candidate(saved)
                    entry["evaluation"] = components.evaluate(label, baseline, saved)
                    components.check_candidate(saved)
                    feedback.append(entry["evaluation"]["result_ref"])
                    records.event("candidate_rechecked", attempt_id=attempt,
                                  candidate_id=saved["candidate_id"],
                                  previous_evaluation=old["result_ref"],
                                  evidence=entry["evaluation"]["result_ref"], audit=entry["audit"]["result_ref"],
                                  summary=f"Reevaluated {saved['candidate_id']} under new checks; "
                                          "retained its existing audit of the same frozen source.")
                    if entry["evaluation"]["status"] == "incomplete":
                        raise RuntimeError("Evaluation or audit could not complete; no candidate was accepted")
            if current["evaluation"]["status"] == "incomplete" or audit["status"] == "incomplete":
                raise RuntimeError("Evaluation or audit could not complete; no candidate was accepted")

        winner = best_qualifier(reviewed, components.version())
        if number >= MIN_ATTEMPTS and winner is not None:
            candidate, evaluation, audit = (winner[key] for key in ("candidate", "evaluation", "audit"))
            components.verify_qualification(baseline, candidate, evaluation, audit)
            selection = records.write("selection.json", {
                "schema_version": "controller-selection/v1",
                "criterion": "highest_lower_95_library_reduction_bound",
                "tie_break": "earliest_attempt", "candidate_id": candidate["candidate_id"],
                "evaluator_version": components.version(),
                "qualifying_candidates": [{
                    "candidate_id": entry["candidate"]["candidate_id"],
                    "time_reduction_lower_bound_95_percent": indexing(entry)["time_reduction_interval_95"][0],
                    "evaluation": entry["evaluation"]["result_ref"], "audit": entry["audit"]["result_ref"],
                } for entry in qualifying_candidates(reviewed, components.version())],
            })
            records.verify()
            records.event("decision", attempt_id=attempt, decision="qualify",
                          summary=f"Selected {candidate['candidate_id']} after {number} attempts: "
                                  "highest lower 95% library-reduction bound among qualifying candidates. "
                                  "Application performance is reported separately.",
                          evidence=selection, feedback=evaluation["result_ref"], audit=audit["result_ref"],
                          candidate=candidate["manifest_ref"])
            return {"status": "qualified", "attempts": number,
                    "selected_candidate_id": candidate["candidate_id"], "selection": selection,
                    "candidate": candidate["manifest_ref"], "evaluation": evaluation["result_ref"],
                    "audit": audit["result_ref"]}
        reason = ("Completing the minimum three optimizer attempts." if number < MIN_ATTEMPTS else
                  "No candidate meets the fixed acceptance rule.")
        records.event("decision", attempt_id=attempt, decision="continue" if number < max_attempts else "budget_exhausted",
                      summary=reason + (" Continuing with complete history." if number < max_attempts else " Attempt budget exhausted."))
    return {"status": "no-qualifying-improvement", "attempts": max_attempts}
