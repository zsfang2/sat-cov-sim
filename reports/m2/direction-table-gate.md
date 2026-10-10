# Round 9 Review Result

Mainline Progress Verdict: ADVANCED

## Goal Alignment Summary

ACs: 10/13 addressed (5 met, 5 partial) | Forgotten items: 0 | Unjustified deferrals: 0

Round 9 verifies G09 / AC-2 and AC-8 software implementation. The direction-table/cache layer is identity-bound, preserves local-only finite-radius semantics, refuses stale descriptors, and records sample/cache evidence. The original implementation plan is still incomplete: G10-G16 remain required, AC-8 is only partial until G10 supplies held-out direction error and cost evidence, and AC-11/12 remain downstream.

## Acceptance Criteria Audit

| AC | Status | Evidence if MET/PARTIAL | Blocker if NOT MET |
|---|---|---|---|
| AC-1 | PARTIAL | G01-G09 now have reports, round summaries/reviews, artifact hashes or explicit evidence, and tracker entries. | Final cross-phase ledger remains G16. |
| AC-2 | PARTIAL | Prior M0 identity/range work remains verified, and G09 adds cache identity over terrain descriptor, receiver, frequency, finite slant range, model/source fingerprint, system assumptions, axes, guard, schema, content hash, and stale-load rejection. | G15 still must prove full-flow identity in the portable M0-M6/E1-E4 package. |
| AC-3 | MET | M1 scalar regression remains protected; full suite passes after G09. | Continue regression during G10/E1. |
| AC-4 | MET | G05/G06 still cover declared M3 terrain/loss numerics, raw/used/cap, curvature, and counterexamples. | None for declared M3 software scope. |
| AC-5 | MET | G01-G04/G06 still cover bounded read, expanded-radius audit, finite-range API/CLI/archive contract, and full-path non-verification. | None for declared finite-radius contract scope. |
| AC-6 | MET | G06 preserves implementation/numerics/source/physical-truth separation and unsupported geometry limits. | None for declared M3 software-baseline acceptance. |
| AC-7 | MET | G07/G08 verified three-role M4/E2 contract, adapters, paired outputs, artifacts, and CSV gate repair. | None for M4/E2. |
| AC-8 | PARTIAL | G09 implements regular direction tables, original-sample reproduction, nearest/bilinear query, batch streaming, disk JSON cache, boundary markers, fallback records, domain/zenith behavior, stale cache rejection, and software archive evidence. | G10 must still report cold-build/hot-query/storage cost and held-out direction error; non-sample interpolation accuracy is not yet certified. |
| AC-9 | NOT MET | No M5 conditional quality-event implementation yet. | G11/G12. |
| AC-10 | NOT MET | No M6 candidate/evaluation implementation yet. | G13/G14. |
| AC-11 | PARTIAL | E2 is implemented and verified; G09 provides the cache substrate needed for E1. | E1, E3, and E4 remain G10/G12/G14. |
| AC-12 | NOT MET | Local M2/M3/M4 archives are valid phase evidence. | No fresh supported-environment M0-M6 plus E1-E4 reproduction package yet; G15 remains. |
| AC-13 | PARTIAL | Round 9 kept a singular mainline objective, supplied tests, reports, archive evidence, and tracker reconciliation; review gates were actually run. | Final code review and closure remain G16. |

Forgotten items: none. The original G01-G16 sequence is still represented in Completed and Verified or Active Tasks after the tracker update.

Explicitly deferred items: none. The Explicitly Deferred table is empty. The queued business/source-lineage and G15 portability items remain valid non-blocking side issues and do not contradict the ultimate goal because the plan permits conditional diagnostics before final business/release claims.

Goal completion summary:

```text
Acceptance Criteria: 5/13 met (0 deferred)
Active Tasks: 7 remaining
Estimated remaining rounds: 7-8
Critical blockers: none
```

## Mainline Drift Audit

The current round's mainline objective is clear and singular: G09 direction query/cache software. It advances the original M2/E1 sequence rather than clearing a side issue. Recent history also shows forward progress: Round 7 exposed a real artifact gate failure, Round 8 corrected and verified it, and Round 9 moved to the next planned coding task.

Blocking Side Issues: 0

Queued Side Issues: 2

No stagnation detected. The same issue is not recurring across recent rounds, acceptance criteria have advanced in each of Rounds 6-9, and this round adds new tested code and evidence instead of repeating prior feedback.

## Implementation Review

No blocking G09 defect found.

What I verified:

- `DirectionTable` validates finite descriptors and local-response schema, keeps local loss separate from FSPL/gain/power, validates axes, marks boundary/unavailable samples, and computes the cache key from solver identity plus axes/guard/storage schema (`src/satellite_coverage/engine/direction_table.py:45`, `src/satellite_coverage/engine/direction_table.py:57`, `src/satellite_coverage/engine/direction_table.py:141`, `src/satellite_coverage/engine/direction_table.py:185`).
- `TerrainLocalSolver` binds the existing M3 finite-distance local model to receiver, frequency, slant range, terrain descriptor, source fingerprint, Python/NumPy versions, and explicit excluded effects; finite range is correctly a cache dependency, not silently approximated away (`src/satellite_coverage/engine/direction_table.py:85`).
- Query behavior matches the G09 contract: descriptor mismatch and fallback-solver identity mismatch raise `CacheMismatch`; zenith/out-of-elevation-domain queries fall back; interpolation refuses incompatible status/LOS/cap/scope stencils; requested error tolerance forces direct fallback except exact samples (`src/satellite_coverage/engine/direction_table.py:272`).
- Disk cache behavior is conservative: exclusive creation, content hash validation, descriptor validation, schema/storage checks, sample budget, and cache key recomputation are all present (`src/satellite_coverage/engine/direction_table.py:344`).
- Tests cover original-sample reproduction, defensive copies, analytic bilinear and nearest behavior, 0/360 wrapping, incompatible unknown/blocked/capped states, domain/zenith fallback, requested-accuracy fallback, stale identity rejection, fallback-solver identity, checksum tamper detection, exclusive writes, build/read budgets, batch order, retained solver failures, invalid directions, and M3 direct equivalence (`tests/test_direction_table.py:52`, `tests/test_direction_table.py:83`, `tests/test_direction_table.py:113`, `tests/test_direction_table.py:139`, `tests/test_direction_table.py:192`).
- `scripts/verify_direction_table.py` creates the claimed artificial-ridge run, writes environment/source/config/grid/cache/query/summary/validation artifacts, proves sample round-trip equality, exercises nearest/bilinear/fallback queries, and rejects stale frequency cache loads (`scripts/verify_direction_table.py:16`).
- `docs/M2.md` and `reports/m2/direction-table.md` correctly avoid overclaiming: they state that sample reproduction is not a physical error proof, non-sample accuracy is not verified, and G10 remains responsible for held-out error/cost and E1 recomposition.

Verification performed:

- `git diff --check 91d6328..HEAD` -> passed with empty output.
- `bash scripts/python_geo.sh -m pytest tests/test_direction_table.py -q` -> 30 passed in 0.21 s.
- `bash scripts/python_geo.sh -m pytest tests -q` -> 402 passed in 9.79 s.
- Fresh verifier run: `bash scripts/python_geo.sh scripts/verify_direction_table.py --output /tmp/m2-review-r9-$$` -> succeeded, 84 samples, 72 known, 40 boundary samples, max sample error 0 dB, stale frequency cache rejected.
- Archived `output/m2-table-20261010/artifacts.json` has 10 files; all recorded SHA-256 hashes match bytes on disk; `reports/m2/direction-table.json` artifact map and manifest hash match the archive.

## Findings

### Mainline Gaps

1. **G10 is now the next mainline task.**
   G09 completes the software query/cache surface, but AC-8 remains partial until G10 reports cold-build/hot-query/storage costs, held-out direction error, and direct/cache recomposition under E1 parameter changes.

2. **AC-11 remains partial.**
   E2 is verified and G09 supplies M2 software infrastructure, but the plan still requires E1, E3, and E4 outputs before AC-11 can close.

3. **G11-G16 remain unfinished.**
   M5 events/E3, M6 candidate evaluation/E4, fresh-environment reproduction, and final AC/code-review closure are still active plan scope.

### Blocking Side Issues

None.

### Queued Side Issues

1. **Business thresholds and DEM mosaic lineage remain unknown.**
   Still non-blocking for G10 because conditional diagnostics are allowed, but they block business/service/release claims.

2. **Phase archives are not the G15 portable reproduction package.**
   `output/m2-table-20261010`, M3, and M4 archives are valid phase evidence, but G15 still needs a small M0-M6 plus E1-E4 workflow rerun in a supported fresh environment.

## Goal Tracker Update

I updated only the mutable section of `.humanize/rlcr/2026-10-09_08-03-30/goal-tracker.md`.

- Plan Version is now 10 / Round 9.
- G09 moved from Active Tasks to Completed and Verified.
- G10 is now the next active mainline task.
- A Round 9 Plan Evolution Log entry records the G09 verification and AC-8 partial status.
- Immutable goal and acceptance criteria were not modified.

Further work required.
