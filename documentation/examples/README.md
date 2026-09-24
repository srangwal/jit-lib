# Example reports

These JSON files are **illustrative summary excerpts**, not original raw evidence
or valid evaluator/auditor inputs. They retain source-report checksums, selected
outcomes, and counts. Long descriptions are shortened; local paths and raw logs
are omitted. Missing historical configuration is not reconstructed.

- `evaluator.json`: original-versus-original evaluator validation. Its timing
  intervals do not establish an optimization.
- `auditor-confirmed.json`: a deliberately planted document-skipping change,
  reproduced by an auditor-generated book and rejected by the strengthened
  evaluator.
- `auditor-benign.json`: a behavior-preserving preallocation control. No violation
  was found, but incomplete supplied evaluation evidence left the audit unresolved.

Run `python3 scripts/reproduce.py` first. Use the printed reproduction directory
and the self-check run ID from its `summary.json`:

```sh
DEMO=".evaluator/reproduction/<reproduction-id>/repository"
python3 scripts/sample_reports.py \
  --evaluation "$DEMO/.evaluator/runs/<self-check-id>" \
  --confirmed "$DEMO/.auditor/validation/planted/audit" \
  --benign "$DEMO/.auditor/validation/benign/audit" \
  --output documentation/examples
```

The script replaces only the three JSON excerpts. Original run directories are
separate, ignored artifacts and are not included in a checkout. If independent
inspection of historical evidence is needed, provide a separately checksummed
release archive containing those original artifacts. No archive is published or
implied by these examples. Fresh reproduction uses the repository's evaluator
and auditor commands rather than these excerpts.

The checked-in excerpts come from the [2026-09-24 cold-setup rehearsal](../REPRODUCTION.md).
