# Round 8 Review Result

Mainline Progress Verdict: ADVANCED

## Goal Alignment Summary

ACs: 9/13 addressed (5 met, 4 partial) | Forgotten items: 0 | Unjustified deferrals: 0

Round 8 resolves the Round 7 blocking CSV artifact gate and verifies G08. The original implementation plan remains incomplete: G09-G16 are still active mainline work, and AC-11 remains partial until E1, E3, and E4 are delivered.

## Findings

### Mainline Gaps

1. **G09-G16 remain unfinished mainline work.**
   This is not a defect in the Round 8 repair, but it is still required plan scope. The next round must proceed to G09 direction table/query/cache work, followed by G10 E1, G11-G12 M5/E3, G13-G14 M6/E4, G15 reproduction, and G16 final AC/code-review closure.

2. **AC-11 remains partial.**
   G08 supplies the E2 portion with verified three-role M4 evidence, but the original plan requires E1, E3, and E4 as separate experiment closures. Do not treat E2 completion as full AC-11 completion.

3. **AC-12 remains not met.**
   Local M3/M4 archives and regenerated E2 evidence are valid phase evidence, but they are not the G15 fresh supported-environment M0-M6 plus E1-E4 reproduction package.

### Blocking Side Issues

None. The Round 7 CSV `git diff --check` blocker is resolved.

### Queued Side Issues

1. **Business thresholds and DEM mosaic lineage remain unknown.**
   This remains non-blocking for G09 because conditional diagnostics are permitted, but it still blocks business/service/release claims.

2. **Current archives are not the G15 portable reproduction package.**
   Keep this queued until the G15 reproduction workflow is implemented.

## Implementation Review

What I verified:

- `scripts/verify_model_comparison.py` now sets `csv.DictWriter(..., lineterminator='\n')`, fixing the generator rather than only normalizing checked-in files.
- `git diff --check 9654285..HEAD` passes with empty output.
- `reports/m4/groups.csv` and `reports/m4/refinements.csv` byte-match `output/m4-e2-lf-20261010/groups.csv` and `output/m4-e2-lf-20261010/refinements.csv`.
- No CSV in `output/m4-e2-lf-20261010` contains carriage returns.
- `output/m4-e2-lf-20261010/artifacts.json` records 37 artifacts, and all 37 recorded SHA-256 hashes match the archive bytes.
- `reports/m4/e2.json` points to `output/m4-e2-lf-20261010`; its `artifact_manifest_sha256` matches the archive manifest; its `artifacts` map matches the archive manifest.
- The archive has 1189 paired groups and 3567 role rows, exactly 1189 rows for each of `sky_horizon_outline_v1`, `m3_current_single_edge_v1`, and `reference_multi_edge_deygout_v1`; every pair has all three roles.
- The report records equivalence to `output/m4-e2-final-20261010`: 3567 rows equal after ignoring source/resource identity fields, grouped differences/thresholds/failures/refinements equal, and all CSVs LF-only.
- Full tests pass locally: `bash scripts/python_geo.sh -m pytest tests -q` -> 372 passed in 9.33 s.

No additional functional G08 blocker found.

## AC Progress Audit

| AC | Status | Evidence / Remaining Gap |
|---|---|---|
| AC-1 | PARTIAL | G01-G08 now have round evidence, reports, hashes, review records, and tracker state; final cross-phase ledger remains G16. |
| AC-2 | PARTIAL | Prior identity/range work remains valid; G09 cache identity and G15 full-flow identity remain. |
| AC-3 | MET | M1 scalar regression remains protected; full tests pass. |
| AC-4 | MET | M3 declared terrain/loss numerics remain covered by G05/G06. |
| AC-5 | MET | Bounded read/radius/finite-range contract remains covered by G01-G04/G06. |
| AC-6 | MET | Declared M3 software-baseline acceptance remains covered by G06. |
| AC-7 | MET | G07 froze the M4/E2 contract and G08 now provides verified three-role adapters, paired evidence, reports, figures, failures, resources, and LF-clean artifacts. |
| AC-8 | NOT MET | No M2 direction query/cache implementation yet. |
| AC-9 | NOT MET | No M5 conditional quality event implementation yet. |
| AC-10 | NOT MET | No M6 candidate/evaluation implementation yet. |
| AC-11 | PARTIAL | E2 is implemented and verified; E1/E3/E4 remain. |
| AC-12 | NOT MET | No fresh-environment M0-M6/E1-E4 package yet. |
| AC-13 | PARTIAL | Round process continues and the prior false clean-gate claim has been corrected; final code review and closure remain G16. |

## Required Implementation Plan For Remaining Work

1. **G09: implement M2 direction query/cache.**
   Build the regular direction table, nearest/simple interpolation paths, batch query path, disk cache, cache identity invalidation over environment/frequency/height/model/system inputs, and direct fallback behavior. Add tests for sample-value reproduction, 0/360 wrap, zenith and boundary behavior, stale cache rejection, invalid extrapolation, batch behavior, and fallback records.

2. **G10: deliver E1 evidence.**
   Run single-factor and limited joint variations for power, antenna pattern, frequency, direction, and height. Report direct versus cached recomposition, cold-build/hot-query/storage cost, held-out direction error, and unsupported/unknown states separately.

3. **G11-G12: implement M5 and E3.**
   Preserve every candidate and every geometry-invisible/unknown/failed/truncated state, generate geometry and quality windows, integrate irregular samples by time, refine direct-time references for short/contact/crossing cases, and report event error plus break-even query cost without merging unknown time into connected coverage.

4. **G13-G14: implement M6 and E4.**
   Add equal-cost fixed-height candidate enumeration, deterministic tie rules, leakage-proof dev/holdout evaluation, regret/cost/ranking/no-benefit metrics, and fixed-decision information-layer comparison.

5. **G15-G16: reproduce and close.**
   Package a small artificial/public-terrain M0-M6 plus E1-E4 workflow, rerun it in a fresh supported environment, record dependency/data recovery and deterministic tolerances, then perform final AC ledger alignment and code-review cleanup.

## Goal Tracker Update

I updated only the mutable section of `.humanize/rlcr/2026-10-09_08-03-30/goal-tracker.md`.

- Plan Version is now 9 / Round 8.
- G08 moved from Active Tasks to Completed and Verified.
- The resolved G08 CSV blocker was removed from Blocking Side Issues.
- A Round 8 Plan Evolution Log entry records the LF CSV repair and G09 as the next active mainline.
- Immutable goal and acceptance criteria were not modified.

Further work required.
