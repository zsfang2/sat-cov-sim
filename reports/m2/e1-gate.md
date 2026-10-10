# Round 10 Review Result

Mainline Progress Verdict: ADVANCED

## Goal Alignment Summary

ACs: 10/13 addressed (6 met, 4 partial) | Forgotten items: 0 | Unjustified deferrals: 0

Round 10 verifies G10 / AC-8 and the E1 portion of AC-11. The original implementation plan remains incomplete: G11-G16 are still required mainline work, AC-9/10/12 remain not met, and AC-11 remains partial until E3 and E4 are delivered.

## Implementation Review

No blocking G10 defect found.

What I verified:

- The round contract is singular and aligned with G10: E1 physical-factor direct/cache recomposition, held-out direction error, and cold/hot cost evidence while preserving AC-3.
- `configs/m2_e1.yaml` freezes the expected scenes, factors, held-out directions, exact tolerance, methods, and non-business threshold basis before execution.
- `src/satellite_coverage/experiments/direction_cache.py` recomposes local-cache responses through the scalar budget, and `full_pipeline()` calls the actual `calculate_links()` path for factor cases rather than only redoing component addition.
- `scripts/verify_direction_cache.py` verifies the config hash against the pre-results freeze, checks real Qinling input hashes, builds 16 tables, confirms held-out directions are disjoint from table samples, performs stale-identity negative checks, records strict fallback/direct recomposition, and reports nearest/bilinear errors without post-hoc thresholds.
- The factor matrix covers power, antenna, frequency, direction, height, direction+antenna, and frequency+height, and records which components changed and whether local cache identity was reusable.
- The E1 report does not overclaim: it preserves unfavorable mountain interpolation errors, reports strict fallback as slower, states no accuracy-matched speedup was proven, and leaves TLE event cost to G12.
- `reports/m2/e1.json` matches `output/m2-e1-audit-20261010/artifacts.json`: 55 artifact hashes match bytes on disk and the manifest SHA-256 matches.
- Tracked E1 CSVs are LF-only, and `git diff --check 16d576d..HEAD` passes with empty output.

Verification performed:

- `bash scripts/python_geo.sh -m pytest tests/test_direction_cache_experiment.py tests/test_direction_table.py -q` -> 33 passed in 0.22 s.
- Fresh verifier replay: `bash scripts/python_geo.sh scripts/verify_direction_cache.py --output /tmp/m2-e1-review-r10` -> passed; 96 factor rows, 6912 held-out rows, 16 tables, strict max power error 0 dB, 36 negative identity checks.
- `bash scripts/python_geo.sh -m pytest tests -q` -> 405 passed in 9.24 s.
- `git diff --check 16d576d..HEAD` -> passed with empty output.

## Findings

### Mainline Gaps

1. **G11-G16 remain unfinished mainline work.**
   G10 is verified, but the original plan still requires M5 conditional quality events, E3 full-pass event/cost evidence, M6 candidate/evaluation implementation, E4 fixed-decision comparison, fresh supported-environment reproduction, and final AC/code-review closure.

2. **AC-11 remains partial.**
   E1 and E2 are now verified, but E3 and E4 are still required by the original plan. Do not treat this round as AC-11 closure.

3. **AC-12 remains not met.**
   `output/m2-e1-audit-20261010` is valid phase evidence, but it is not the G15 portable M0-M6 plus E1-E4 reproduction package.

### Blocking Side Issues

None.

### Queued Side Issues

1. **Business thresholds and DEM mosaic lineage remain unknown.**
   This remains non-blocking for G11 because conditional diagnostics are permitted, but it still blocks service/business/release claims.

2. **Phase archives are not the G15 portable reproduction package.**
   M2/M3/M4 archives are legitimate phase evidence only. G15 must still package and rerun a small M0-M6 plus E1-E4 workflow in a fresh supported environment.

## AC Progress Audit

| AC | Status | Evidence / Remaining Gap |
|---|---|---|
| AC-1 | PARTIAL | G01-G10 now have reviewable reports, archives, hashes, and tracker entries; final cross-phase ledger remains G16. |
| AC-2 | PARTIAL | Prior identity/range work plus G09/G10 cache identity checks are valid; full-flow identity remains G15. |
| AC-3 | MET | M1 scalar path remains protected; G10 directly cross-checks factor cases against `calculate_links()` and full tests pass. |
| AC-4 | MET | Prior M3 terrain/loss numerics remain covered by G05/G06. |
| AC-5 | MET | Prior bounded read/radius/finite-range contract remains covered by G01-G04/G06. |
| AC-6 | MET | Prior declared M3 software-baseline acceptance remains covered by G06. |
| AC-7 | MET | M4/E2 remains verified from G07/G08. |
| AC-8 | MET | G09 provides query/cache software; G10 supplies held-out direction error, cold/hot cost, storage, fallback, and identity-invalidation evidence for the declared scope. |
| AC-9 | NOT MET | No M5 conditional quality-event implementation yet. |
| AC-10 | NOT MET | No M6 candidate/evaluation implementation yet. |
| AC-11 | PARTIAL | E1 and E2 verified; E3 and E4 remain. |
| AC-12 | NOT MET | No fresh supported-environment M0-M6 plus E1-E4 reproduction package yet. |
| AC-13 | PARTIAL | Round 10 followed the contract and review gates; final code review and closure remain G16. |

## Required Implementation Plan For Remaining Work

1. **G11: implement M5 conditional quality events.**
   Add the event model that preserves every candidate and every invisible/unknown/failed/truncated state. Generate separate geometry and quality windows, integrate irregular samples by time, keep unknown time separate from connected coverage, and add artificial tests for short windows, threshold contact, crossings, missing samples, and truncation.

2. **G12: deliver E3.**
   Run held-out complete-pass event experiments using direct-time refinement as the reference. Report event error, unknown/failure denominators, strict versus cache-derived costs, and break-even query counts. Do not use interpolated event times as direct truth and do not hide unfavorable passes.

3. **G13: implement M6 candidate/evaluation framework.**
   Build equal-cost fixed-height candidate enumeration, deterministic tie rules, an isolated development selection path, holdout-only evaluation, artificial optimal/regret tests, and leakage guards.

4. **G14: deliver E4.**
   Run fixed-decision information-layer comparisons on the common holdout set. Report cumulative/longest insufficiency, rankings, regret, cost, no-benefit cases, and threshold/config sensitivity without converting unknown business thresholds into certification.

5. **G15-G16: reproduce and close.**
   Package a small artificial/public-terrain M0-M6 plus E1-E4 workflow, rerun it in a fresh supported environment, record dependency/data recovery and deterministic tolerances, reconcile every AC in the tracker, then perform final code-review cleanup.

## Goal Tracker Update

I updated only the mutable section of `.humanize/rlcr/2026-10-09_08-03-30/goal-tracker.md`.

- Plan Version is now 11 / Round 10.
- G10 moved from Active Tasks to Completed and Verified.
- G11 is now the next active mainline task.
- A Round 10 Plan Evolution Log entry records G10 verification and AC-8 closure for the declared M2 query/cache/error/cost scope.
- Immutable goal and acceptance criteria were not modified.

Further work required.
