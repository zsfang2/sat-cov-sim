# Round 5 Review Result

Mainline Progress Verdict: ADVANCED

## Goal Alignment Summary

ACs: 6/13 addressed (4 met, 2 partial) | Forgotten items: 0 | Unjustified deferrals: 0

Round 5 completed the intended G06 analysis lane: conditional M3 software-baseline acceptance for the declared finite-radius, declared-raster, local single-knife-edge model. I verified the work against `docs/humanize261009plan.md`, the Round 5 contract, recent review history, and the tracker.

The review does not close the original implementation plan. G07-G16 remain active mainline work: M4/E2 roles and pairing, M2/E1 query/cache, M5/E3 events, M6/E4 candidate evaluation, G15 fresh-environment reproduction, and G16 final AC/code-review closure. Do not output COMPLETE.

## AC Progress Audit

| AC | Status | Evidence if MET/PARTIAL | Blocker if NOT MET |
|---|---|---|---|
| AC-1 | PARTIAL | Round evidence now includes G01-G06 reports, hashes, independent consultation, tracker updates, and M3 acceptance ledger. | Final cross-phase ledger remains G16. |
| AC-2 | PARTIAL | G01/G02/G04 identity, bounded reader, finite-range contract, and query binding remain verified. | G09 cache identity and G15 portable full-flow identity remain. |
| AC-3 | MET | M1 scalar regression remains protected; Round 5 full suite passed. | Continue regression during G10/E1. |
| AC-4 | MET | G05 plus G06 acceptance ledger cover declared terrain/loss numerics, T06/T07, raw/used/caps, curvature and counterexamples. | None for declared M3 software scope. |
| AC-5 | MET | G01-G04 plus G06 acceptance ledger cover bounded read, 48 km radius matrix, finite-range API/CLI/archive contract, and full-path non-verification. | None for declared finite-radius contract scope. |
| AC-6 | MET | G06 explicitly separates implementation, numerics, source assumptions, physical truth, unsupported zenith/near geometry, and downstream restrictions. | None for declared M3 software-baseline acceptance; physical truth remains out of scope. |
| AC-7 | NOT MET | No M4 three-role adapter/reference work yet. | G07/G08. |
| AC-8 | NOT MET | No M2 direction query/cache implementation yet. | G09/G10. |
| AC-9 | NOT MET | No M5 conditional quality event implementation yet. | G11/G12. |
| AC-10 | NOT MET | No M6 candidate/evaluation implementation yet. | G13/G14. |
| AC-11 | NOT MET | E1-E4 remain downstream; only M3 prerequisite evidence exists. | G08/G10/G12/G14. |
| AC-12 | NOT MET | No small M0-M6/E1-E4 fresh-environment package. | G15. |
| AC-13 | PARTIAL | Round contract, independent analysis, summary, tracker reconciliation, and this review preserve process evidence. | Final code review and closure remain G16. |

Forgotten items: none. The original G01-G16 sequence is still represented in Active/Completed sections after my tracker update.

Explicitly deferred items: none. The queued threshold/source-lineage and portability issues remain valid queued side issues, not deferrals.

## Implementation Review

No blocking implementation defect found in Round 5.

What I verified:

- `reports/m3/acceptance.md` maps M3 requirements and AC-1/4/5/6/13 to concrete evidence while preserving limitations: finite radius only, `full_path_status=not_verified`, DSM source assumptions, unsupported zenith/near geometry, and no physical/business certification.
- `reports/m3/acceptance-review.md` exactly matches the official ask-codex output; its SHA-256 is `2cbe28a626edbfc7ae0e2258383eb14a9fa16d4f7515f1cb8de6fae4f365965e`, matching `reports/m3/acceptance.json`.
- `reports/m3/acceptance.json` correctly records the consultation path, input/output hashes, evidence hashes, implementation baseline `8fb0991`, Round 5 validation command, and remaining tasks G07-G16.
- The added angular-boundary regression in `tests/test_cell_profile.py` checks the isolated cell support against analytic corner angles over 4/2/1/0.5/0.25 degree spacings and verifies bracket errors decrease without changing production code.
- `reports/m3/progress.md` and `docs/M3.md` point to the layered acceptance result and preserve the distinction between declared software acceptance and physical truth.

Verification performed:

- `bash scripts/python_geo.sh -m pytest tests/test_cell_profile.py -q` -> 16 passed in 0.14 s.
- `bash scripts/python_geo.sh -m pytest tests/test_terrain_contract.py tests/test_terrain_integration.py tests/test_terrain_domain.py tests/test_native_terrain.py tests/test_m1_links.py -q` -> 73 passed in 1.59 s.
- `bash scripts/python_geo.sh -m pytest tests -q` -> 331 passed in 9.22 s.
- `git diff --check 8fb0991..8bc752c` -> passed.
- SHA-256 checks for acceptance review, evidence summaries, and `tests/test_cell_profile.py` matched the recorded `acceptance.json` entries.

## Mainline Gaps

1. **G07-G16 remain unfinished mainline work.**
   This is expected sequence progress, not a G06 defect. The next round must start G07, not revisit completed M3 evidence unless a concrete G06 regression is introduced.

2. **G07 must freeze the M4/E2 three-role comparison contract before any adapter coding.**
   Claude should define the three roles required by AC-7: sky-horizon outline, current simplified generator/model, and finer reference role. The G07 output must freeze paired sample IDs, geometry, frequency, antenna assumptions, average-power convention, effect-inclusion vocabulary, V0/V1/V2 reference tiers, failure/status rows, resource fields, and E2 parameters. It must explicitly carry forward the M3 restrictions from `reports/m3/acceptance.md`.

3. **The full plan remains incomplete until G16.**
   After G07, execute G08 through G16 in dependency order. Do not substitute the M3 acceptance ledger for M4/M2/M5/M6 implementation or E1-E4 experimental closure.

## Blocking Side Issues

None.

## Queued Side Issues

1. **Business thresholds and DEM mosaic lineage remain unknown.**
   This does not block G07 because conditional diagnostics are allowed, but it still blocks business/service/release claims and final research conclusions.

2. **Local diagnostics are not the G15 portable reproduction package.**
   Existing real-data evidence is valid phase evidence. G15 must still package and rerun a small M0-M6/E1-E4 workflow in a supported fresh environment.

3. **`docs/M3.md` has one stale status phrase.**
   The top paragraph correctly says G06 independent analysis supports declared-scope acceptance pending this gate, but the next paragraph still says "G06 独立验收待完成." This is not blocking because the acceptance ledger and progress report are clear, but it should be cleaned up during the next M3 documentation touch or G16 final documentation pass.

## Required Implementation Plan For Remaining Work

1. **G07: freeze the M4/E2 comparison design.**
   Write a tracked M4 design report that defines the sky-outline, current-model, and finer-reference roles; the exact paired record schema; required geometry/frequency/antenna/power/effect fields; V0/V1/V2 reference classifications; failure and truncation semantics; resource metrics; and E2 parameter set. Include a negative checklist proving that two-role comparison, same-model densification as independent truth, dropped failures, and unit/effect mismatches cannot close AC-7.

2. **G08: implement the M4 adapters and paired report.**
   Add the adapters/pairing code and tests from the G07 schema. Generate E2 tables/figures with all paired successes/failures, grouped statistics, threshold disagreements, truncation and resources. Include the same-model densification report separately and label its independence limits.

3. **G09-G10: implement M2 direction query/cache and E1 validation.**
   Build the regular direction table, nearest/simple interpolation query path, batch and disk cache, identity invalidation, boundary/domain behavior, and cold/hot resource measurements. Then run E1 single-factor and limited joint variations, direct/cache recomposition checks, held-out direction error, and cost evidence.

4. **G11-G14: implement events and candidate evaluation.**
   G11/G12 must preserve candidate, invisible, unknown, failed, truncated and irregular-sampling states while producing geometry and quality windows with direct-time refinement. G13/G14 must add equal-cost fixed-height candidate enumeration, leakage-proof dev/holdout evaluation, tie rules, regret/cost metrics, no-benefit reporting, and E4 information-layer comparison.

5. **G15-G16: reproduce and close.**
   Package a small artificial/public-terrain M0-M6 plus E1-E4 workflow, run it in a fresh supported environment, record dependencies/data recovery and deterministic tolerances, then perform the final AC ledger alignment and code-review cleanup. Only after this can the overall Humanize plan be considered complete.

## Goal Tracker Update

I updated only the mutable section of `.humanize/rlcr/2026-10-09_08-03-30/goal-tracker.md`.

- Plan Version is now 6 / Round 5.
- Plan Evolution Log records G06 verification and G07 as next mainline.
- G06 moved out of Active Tasks.
- G06 added to Completed and Verified with Round 5 evidence.
- The stale `docs/M3.md` phrase was added as a queued side issue.
- Immutable goal and acceptance criteria were not modified.

Further work required.
