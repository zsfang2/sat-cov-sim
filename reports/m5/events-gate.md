# Round 11 Review Result

Mainline Progress Verdict: ADVANCED

## Goal Alignment Summary

ACs: 11/13 addressed (6 met, 5 partial) | Forgotten items: 0 | Unjustified deferrals: 0

Round 11 verifies G11 / AC-9 for conditional quality-event software and artificial/direct-time tests. The original implementation plan remains incomplete: G12-G16 are still required mainline work, AC-9 remains partial until E3 full-pass event evidence, AC-10 and AC-12 remain not met, and AC-11 remains partial until E3 and E4 are delivered.

## Implementation Review

No blocking G11 defect found.

What I verified:

- The round contract is singular and aligned with G11: conditional geometry/quality event extraction, direct-time refinement, duration integration, unknown/failure/censor semantics, and M1 arbitrary-time support.
- `src/satellite_coverage/engine/quality_events.py` preserves all candidate records, separates geometry from quality state, keeps invisible distinct from insufficient, records unknown transition brackets instead of interpolated roots, and reports event IDs/types/durations/censor metadata.
- Multi-candidate opportunity semantics are conservative: any known sufficient candidate makes the interval available; otherwise unknown dominates unavailable; empty candidate sets keep the whole observation denominator as unavailable and service eligibility remains unknown.
- `direct_events()` performs actual callback evaluations at every recorded time, probes all intervals to the configured spacing, refines differing geometry/quality states to the configured bracket width, retains evaluator failures as failed records, and raises on sample-budget exhaustion rather than returning a partial event result.
- `calculate_links(..., evaluation_times=...)` supports explicit direct times only for TLE/fixed-ECEF sources, keeps TLE selection and max-age checks tied to the original interval, rejects sampled direction/ENU sequence interpolation, and preserves the regular M1 path.
- Tests cover analytic crossings within the declared 0.1 s tolerance, short windows, threshold contact and plateau behavior, missing/solver-failure windows, irregular duration weighting and gaps, multi-candidate handoff/no-candidate semantics, geometry-vs-quality roots, budget failure, invalid inputs, fixed-grid equivalence, TLE fixed selection/age policy, and finite terrain contract binding.
- `scripts/verify_quality_events.py` replays the claimed artificial cases and M1 adapter check; `output/m5-events-final-20261010` contains the claimed 16 artifacts, and every recorded SHA-256 hash matches the archive bytes. `reports/m5/events.json` matches the archive artifact map, and its manifest hash is the byte hash of `output/m5-events-final-20261010/artifacts.json`.
- `docs/M5.md`, `reports/m5/events.md`, and `docs/NUMERICAL_CHANGELOG.md` avoid overclaiming: finite probe spacing limitations, unknown business tolerance, no service certification, and G12/E3 remaining scope are explicit.
- `reports/m2/e1-gate.md` is an exact tracked copy of the Round 10 review result and does not alter G10 evidence.

Verification performed:

- `bash scripts/python_geo.sh -m pytest tests/test_quality_events.py -q` -> 12 passed in 0.20 s.
- Fresh verifier replay: `bash scripts/python_geo.sh scripts/verify_quality_events.py --output /tmp/m5-review-r11` -> passed; max analytic boundary error 0.018437 s, M1 direct times 65.
- `bash scripts/python_geo.sh -m pytest tests -q` -> 417 passed in 10.18 s.
- `git diff --check 3f5e9c7..HEAD` -> passed with empty output.
- Artifact hash audit against `output/m5-events-final-20261010/artifacts.json` -> 16/16 hashes matched.

## Findings

### Mainline Gaps

1. **G12-G16 remain unfinished mainline work.**
   G11 is verified, but the original plan still requires E3 held-out complete-pass event/convergence/cost evidence, M6 candidate/evaluation implementation, E4 fixed-decision comparison, fresh supported-environment reproduction, and final AC/code-review closure.

2. **AC-9 remains partial.**
   G11 delivers the M5 software layer and artificial direct-time tests. AC-9 also requires G12: held-out complete-pass E3 evidence with direct reference convergence, event error denominators, and cost/break-even reporting. Do not treat artificial 10 s fixtures as actual full-pass event accuracy.

3. **AC-11 remains partial.**
   E1 and E2 are verified, and G11 supplies the event substrate needed for E3. AC-11 still requires E3 and E4 outputs before it can close.

4. **AC-10 and AC-12 remain not met.**
   No M6 candidate/evaluation framework or fresh supported-environment M0-M6 plus E1-E4 reproduction package exists yet.

### Blocking Side Issues

None.

### Queued Side Issues

1. **Business thresholds and DEM mosaic lineage remain unknown.**
   This remains non-blocking for G12 because conditional diagnostics and assumption scans are allowed, but it still blocks business/service/release claims.

2. **Phase archives are not the G15 portable reproduction package.**
   `output/m5-events-final-20261010` is valid G11 phase evidence only. G15 must still package and rerun a small M0-M6 plus E1-E4 workflow in a fresh supported environment.

## AC Progress Audit

| AC | Status | Evidence / Remaining Gap |
|---|---|---|
| AC-1 | PARTIAL | G01-G11 now have reviewable reports, archives, hashes, and tracker entries; final cross-phase ledger remains G16. |
| AC-2 | PARTIAL | Prior identity/range/cache work remains valid; G11 preserves M1 explicit-time identity and finite terrain binding, but full-flow identity remains G15. |
| AC-3 | MET | M1 scalar path remains protected; explicit-time fixed/TLE checks and full tests pass. |
| AC-4 | MET | Prior M3 terrain/loss numerics remain covered by G05/G06. |
| AC-5 | MET | Prior bounded read/radius/finite-range contract remains covered by G01-G04/G06 and G11 terrain-contract checks. |
| AC-6 | MET | Prior declared M3 software-baseline acceptance remains covered by G06. |
| AC-7 | MET | M4/E2 remains verified from G07/G08. |
| AC-8 | MET | M2/E1 remains verified from G09/G10. |
| AC-9 | PARTIAL | G11 implements conditional quality-event software, direct-time refinement, artificial tests, reports, and archive evidence; G12 whole-pass E3 remains. |
| AC-10 | NOT MET | No M6 candidate/evaluation implementation yet. |
| AC-11 | PARTIAL | E1 and E2 verified; G11 adds event substrate; E3 and E4 remain. |
| AC-12 | NOT MET | No fresh supported-environment M0-M6 plus E1-E4 reproduction package yet. |
| AC-13 | PARTIAL | Round 11 followed the contract, supplied tests/reports/archive evidence, and passed review; final code review and closure remain G16. |

## Required Implementation Plan For Remaining Work

1. **G12: deliver E3 next.**
   Freeze a held-out complete-pass event experiment using the verified G11 direct-time engine as the reference. Run whole-pass scenarios, report direct-reference convergence, candidate/event error, unknown/failure denominators, strict/direct/cache-derived costs, and break-even query counts. Preserve unfavorable passes and never convert interpolated sample times into direct truth.

2. **G13: implement M6 candidate/evaluation framework.**
   Build equal-cost fixed-height candidate enumeration, deterministic tie rules, an isolated development-selection path, holdout-only evaluation, artificial known-optimum/regret tests, and leakage guards.

3. **G14: deliver E4.**
   Run fixed-decision information-layer comparisons on the common holdout set. Report cumulative and longest insufficiency, rankings, regret, cost, no-benefit cases, and threshold/config sensitivity without converting unknown business thresholds into certification.

4. **G15-G16: reproduce and close.**
   Package a small artificial/public-terrain M0-M6 plus E1-E4 workflow, rerun it in a fresh supported environment, record dependency/data recovery and deterministic tolerances, reconcile every AC in the tracker, then perform final code-review cleanup.

## Goal Tracker Update

I updated only the mutable section of `.humanize/rlcr/2026-10-09_08-03-30/goal-tracker.md`.

- Plan Version is now 12 / Round 11.
- G11 moved from Active Tasks to Completed and Verified.
- G12 is now the next active mainline task.
- A Round 11 Plan Evolution Log entry records G11 verification and AC-9 partial status.
- Immutable goal and acceptance criteria were not modified.

Further work required.
