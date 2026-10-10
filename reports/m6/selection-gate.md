# Round 13 Review Result

Mainline Progress Verdict: ADVANCED

## Goal Alignment Summary

ACs: 12/13 addressed (7 met, 5 partial, 1 not met) | Forgotten items: 0 | Unjustified deferrals: 0

Round 13 verifies G13 / AC-10 for the M6 candidate-selection software layer: equal-cost fixed-AGL candidate identities, complete development/holdout score-table validation, development-only selection receipts, common-holdout evaluation, oracle/regret/gain reporting, and artificial leakage/optimality tests. The original implementation plan remains incomplete: G14-G16 are still required, AC-10 remains partial until E4 uses this evaluator on actual information-layer evidence, AC-11 remains partial until E4, and AC-12 remains not met until G15.

## Implementation Review

No blocking G13 defect found.

What I verified:

- The Round 13 contract is singular and aligned with G13 / AC-10: implement the fixed candidate/evaluation framework, not the later E4 information-layer experiment.
- `src/satellite_coverage/engine/candidate_selection.py` validates candidate identity, equal positive cost, identical nonnegative AGL, explicit feasibility, complete development/holdout pass registries, non-overlapping chronological splits, and full candidate x pass score rows.
- `DevelopmentScores` and `HoldoutScores` are separate runtime types. `select_candidate()` rejects holdout scores, `evaluate_selection()` rejects development scores, and `SelectionReceipt` recomputes the development-only decision on load so selected-candidate tampering is rejected.
- The frozen objective is `insufficient + invisible + unknown` seconds over the complete observation denominator. Unknown and invisible time are retained in component outputs, and the reports avoid claiming actual service outage or business certification.
- The holdout oracle is computed only in `evaluate_selection()`, and regret is the selected holdout objective minus the retrospective feasible holdout optimum with negative regret beyond 1e-6 s rejected.
- `compare_evaluations()` requires the same holdout checksum, candidate-set checksum, pass-registry checksum, and decision rule before reporting gain, so no-benefit and negative-gain cases are preserved.
- `score_row_from_events()` binds M5 event summaries back to a registered pass interval and keeps all no-satellite observation time as invisible rather than dropping the denominator.
- `scripts/verify_candidate_selection.py` creates and persists all development selection receipts before constructing holdout tables, then archives reversal and no-benefit common-holdout scenarios plus tamper/leakage checks.
- `reports/m5/e3-gate.md` is an exact tracked copy of the Round 12 review result, and `reports/m5/e3.md` now correctly points to G12 as accepted.
- `reports/m6/selection.md`, `docs/M6.md`, and `docs/NUMERICAL_CHANGELOG.md` correctly state that G13 is software isolation evidence, not actual E4 information-value evidence.

Verification performed:

- `bash scripts/python_geo.sh -m pytest tests/test_candidate_selection.py -q` -> 18 passed in 0.18 s.
- Fresh verifier replay: `bash scripts/python_geo.sh scripts/verify_candidate_selection.py --output /tmp/m6-selection-review-r13` -> passed; reversal selected B for the richer artificial method with regret 7 s and gain -7 s; no-benefit gain was 0; tampered receipt and holdout-to-selector checks were rejected.
- `bash scripts/python_geo.sh -m pytest tests -q` -> 439 passed in 9.96 s.
- `git diff --check cc8c233..HEAD` -> passed with empty output.
- Artifact audit against `reports/m6/selection.json` and `output/m6-selection-20261010/artifacts.json` -> 17/17 hashes matched; manifest hash matched.
- I also checked the declared upper-bound consistency and found a non-blocking row-cap issue listed below.

## Findings

### Mainline Gaps

1. **G14-G16 remain unfinished mainline work.**
   G13 is verified, but the original plan still requires E4 fixed-decision information-layer comparison, fresh supported-environment reproduction, and final AC/code-review closure.

2. **AC-10 remains partial, not closed.**
   The M6 selection/evaluation software now exists and is tested with artificial known-optimum, reversal, tie, no-benefit, no-feasible and leakage cases. AC-10 still requires G14 to run the common-holdout evaluation for actual information layers, report threshold/config sensitivity, and make the no-benefit/research judgment evidence concrete.

3. **AC-11 remains partial.**
   E1, E2, and E3 are verified, and G13 supplies the fixed-decision evaluator needed by E4. AC-11 still requires E4 benefit/regret evidence.

4. **AC-12 remains not met.**
   `output/m6-selection-20261010` is a valid G13 phase archive, but it is not the G15 portable M0-M6 plus E1-E4 reproduction package in a fresh supported environment.

### Blocking Side Issues

None.

### Queued Side Issues

1. **The score-table row cap is inconsistent with the declared candidate/pass upper bounds.**
   `CandidateSet` allows 256 candidates, `PassRegistry` allows up to 1000 complete observations, and `_Scores` requires every candidate x split-pass row, but `_Scores` rejects any row list over 100000 rows. A valid 256-candidate / 500-development-pass table therefore needs 128000 rows and is rejected before exact-row validation. This does not block the current artificial G13 evidence or the likely small G14 experiment, but the API should either raise the row cap to match its declared bounds or lower the advertised bounds before relying on those maxima.

2. **Business thresholds and DEM mosaic lineage remain unknown.**
   This remains non-blocking for G14 because conditional diagnostics and sensitivity scans are allowed, but it still blocks service/business/release claims.

3. **Phase archives are not the G15 portable reproduction package.**
   M2/M3/M4/M5/M6 archives are legitimate phase evidence only. G15 must still package and rerun a small M0-M6 plus E1-E4 workflow in a fresh supported environment.

## AC Progress Audit

| AC | Status | Evidence / Remaining Gap |
|---|---|---|
| AC-1 | PARTIAL | G01-G13 now have reviewable reports, archives, hashes, and tracker entries; final cross-phase ledger remains G16. |
| AC-2 | PARTIAL | Prior identity/range/cache work remains valid; G13 preserves candidate/pass identity checks, but full-flow portable identity remains G15. |
| AC-3 | MET | M1 scalar path remains protected; full tests pass. |
| AC-4 | MET | Prior M3 terrain/loss numerics remain covered by G05/G06. |
| AC-5 | MET | Prior bounded read/radius/finite-range contract remains covered by G01-G04/G06. |
| AC-6 | MET | Prior declared M3 software-baseline acceptance remains covered by G06. |
| AC-7 | MET | M4/E2 remains verified from G07/G08. |
| AC-8 | MET | M2/E1 remains verified from G09/G10. |
| AC-9 | MET | G11/G12 satisfy the declared M5/E3 conditional numerical scope. |
| AC-10 | PARTIAL | G13 implements the candidate selection/evaluation software and leakage guards; G14 actual common-holdout E4 evidence remains. |
| AC-11 | PARTIAL | E1, E2, and E3 are verified; E4 remains G14. |
| AC-12 | NOT MET | No fresh supported-environment M0-M6 plus E1-E4 reproduction package yet. |
| AC-13 | PARTIAL | Round 13 followed a singular contract, supplied tests/reports/archive evidence, and passed review checks; final code review and closure remain G16. |

## Required Implementation Plan For Remaining Work

1. **G14: deliver E4 next.**
   Use the verified G13 receipt/evaluation API to compare fixed decisions across information layers on a common holdout set. Freeze the E4 config and split before running, save receipts before constructing holdout tables, and report cumulative/longest insufficiency, rankings, regret, gain, no-benefit cases, threshold/config sensitivity, and costs without converting unknown business thresholds into certification.

2. **G15: package and rerun a small full workflow.**
   Build a small artificial/public-terrain M0-M6 plus E1-E4 reproduction package with dependency/data recovery instructions, then rerun it in a fresh supported environment and record deterministic tolerances and failures.

3. **G16: close the plan.**
   Reconcile every AC, queued issue, phase report, and evidence index; fix the queued score-table row-cap inconsistency if it has not already been handled; run final code-review cleanup; keep unresolved business/source limitations explicit.

## Goal Tracker Update

I updated only the mutable section of `.humanize/rlcr/2026-10-09_08-03-30/goal-tracker.md`.

- Plan Version is now 14 / Round 13.
- G13 moved from Active Tasks to Completed and Verified.
- G14 is now the next active mainline task.
- A Round 13 Plan Evolution Log entry records G13 verification and AC-10 remaining partial until G14.
- The score-table row-cap inconsistency was added to Queued Side Issues.
- Immutable goal and acceptance criteria were not modified.

Further work required.
