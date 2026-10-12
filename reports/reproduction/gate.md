# Round 15 Review Result

Mainline Progress Verdict: ADVANCED

## Goal Alignment Summary

ACs: 13/13 addressed, 11 met and 2 partial | Forgotten items: 0 | Unjustified deferrals: 0

Round 15 verifies G15 / AC-2 / AC-12 for the declared finite-scope, same-host fresh supported environment. The implementation packages recoverable source/config/derived terrain/TLE inputs, locks offline wheels, records a baseline semantic result, and replays the workflow from extracted source in a new CPython 3.12 Linux x86_64 venv outside the git checkout. This closes the portable small M0-M6 / E1-E4 reproduction requirement for the stated scope. It does not close G16, final code-review/final ledger work, physical truth, cross-platform portability, raw national DEM regeneration, or legacy reference-pipeline requirements.

## Findings

### Mainline Gaps

1. **G16 remains unfinished and must be the next mainline task.**
   G15 is accepted, but the original plan still requires G16: full AC/stage ledger reconciliation, queued issue disposition, necessary code-review fixes, documentation/version closure, and final Humanize completion. This keeps AC-1 and AC-13 partial. The tracker now marks G16 as active rather than complete.

2. **Final closure must explicitly handle the queued score-row cap mismatch.**
   The Round 13 row-cap inconsistency remains a queued side issue. It did not block G15 because the reproduction subset is much smaller than the declared upper bounds, but G16 must either fix the cap to match the advertised candidate/pass maxima or formally constrain the documented maxima before final acceptance.

### Blocking Side Issues

None found for G15. The fresh replay path is sufficiently self-contained for the declared supported environment: `scripts/replay_reproduction.py` verifies bundle hashes, extracts source, creates a fresh venv, installs only from hashed local wheels with `--require-hashes`, runs `pip check`, runs the full tests, and then runs the six-stage workflow comparison.

### Queued Side Issues

1. **Same-host fresh venv is accepted only as the declared supported-environment proof.**
   The evidence is not cross-platform or another-host validation. That limitation is documented in `reports/reproduction/summary.json` and `reproduction/README.md`, so it is not a G15 blocker.

2. **Original DEM mosaic lineage and TLE acquisition remain unverified.**
   The bundle includes exact derived grids and exact archived TLE bytes, with source/conversion metadata and hashes. This makes the experiment recoverable but does not authenticate the upstream mosaic or TLE acquisition path.

3. **Real whole-pass M4 reference stability remains unqualified.**
   The portable E4 subset preserves the inconclusive reference outcome rather than upgrading it. It must remain a limitation before any physical/service or true no-benefit claim.

4. **Business thresholds and legacy reference-pipeline backlog remain outside the accepted G15 scope.**
   G15 proves reproducibility of the finite research subset, not deployment utility, service qualification, or restoration of scheduler/beam/weather/clutter/RNG/writer/resume/benchmark behavior.

## Implementation Review

What I verified:

- `reproduction/README.md` defines the locked CPython 3.12 Linux x86_64 target, offline bundle workflow, exact comparison scope, frozen subset coverage for M0-M6/E1-E4, and data provenance limits.
- `scripts/reproduce_small.py` verifies the input manifest, runs the existing synthetic event and selection verifiers plus E1/E2/E3/E4 verifier workflows, audits E4, and compares an explicit semantic projection with exact structure/status/string identity and 1e-6 absolute float tolerance.
- `scripts/package_reproduction.py` requires a passed baseline, rehashes baseline artifacts, copies `expected.json`, archives source/config/reproduction inputs, and includes only wheels whose SHA256 hashes are present in `requirements-reproduce.lock`.
- `scripts/replay_reproduction.py` rejects unsupported Python/platform combinations, verifies bundle file hashes, extracts source outside the repo, creates a venv without system packages, removes geospatial/Python path overrides, installs offline with `--require-hashes`, runs full tests, and runs the workflow against bundled expected science.
- `reports/reproduction/summary.json` records baseline and fresh run identities, 171,636,052-byte bundle, 182 source/input files, 522 verified artifacts, byte-identical semantic JSON, 457 fresh tests, and explicit limitations.
- `reports/reproduction/fresh-tests.txt` records `457 passed in 12.67s`; I independently reran `bash scripts/python_geo.sh -m pytest tests/test_reproduction.py -q` -> 10 passed and `bash scripts/python_geo.sh -m pytest tests -q` -> 457 passed.
- I rechecked the bundle manifest in `output/reproduction-bundle-20261012`: 39 listed files, no missing files, no hash mismatches, 34 wheels present.
- `git diff --check fbc9e33..70e93f0` passed.

## AC Progress Audit

| AC | Status | Evidence / Remaining Gap |
|---|---|---|
| AC-1 | PARTIAL | G01-G15 now have reviewable reports, archives, hashes, and tracker entries; final cross-phase ledger remains G16. |
| AC-2 | MET | Full-flow portable identity evidence now includes bundled input/config hashes, source archive recovery, fresh venv source fingerprint, native library records, and exact semantic comparison. |
| AC-3 | MET | M1 scalar behavior remains protected through E1 and full regression. |
| AC-4 | MET | Prior M3 terrain/loss numerical evidence remains accepted. |
| AC-5 | MET | Prior bounded-read/radius/finite-range contract evidence remains accepted. |
| AC-6 | MET | Prior conditional M3 software-baseline acceptance remains accepted. |
| AC-7 | MET | M4/E2 three-role comparison remains verified and is included in the portable subset. |
| AC-8 | MET | M2/E1 direction cache evidence remains verified and is included in the portable subset. |
| AC-9 | MET | M5/E3 event evidence remains verified and is included in the portable subset. |
| AC-10 | MET | M6/E4 selection/evaluation evidence remains verified for the declared conditional scope and is included in the portable subset. |
| AC-11 | MET | E1-E4 all have accepted configs, outputs, failure/unknown accounting, splits, and now a portable small replay. |
| AC-12 | MET | G15 supplies the fresh supported-environment small M0-M6/E1-E4 package and replay. |
| AC-13 | PARTIAL | Round discipline and review evidence continue; final code-review phase and closure remain G16. |

## Goal Tracker Update

I updated only the mutable section of `.humanize/rlcr/2026-10-09_08-03-30/goal-tracker.md`.

- Plan Version is now 16 / Round 15.
- G15 moved to Completed and Verified with reproduction evidence.
- G16 is now the only active mainline task.
- A Round 15 Plan Evolution Log entry records AC-2/AC-12 closure for the finite supported-environment reproduction scope and keeps AC-1/AC-13 partial until G16.
- Immutable goal and acceptance criteria were not modified.

## Required Implementation Plan For Remaining Work

1. **Execute G16 as the only next mainline task.**
   Produce a final AC ledger that maps every AC-1 through AC-13 to accepted evidence, current limitations, and final status. The ledger must distinguish conditional research acceptance from physical/service/business claims.

2. **Resolve the queued score-row cap mismatch during G16.**
   Update the candidate-selection score table limits so valid tables at the documented candidate/pass maxima are accepted, or lower the documented maxima and tests to the actual supported bound. Add a regression test for whichever bound is final.

3. **Run the final code-review cleanup and record outcomes.**
   Perform the required final review pass, fix any blocking findings, and preserve non-blocking limitations in the final report rather than promoting them to solved work.

4. **Finalize documentation and tracker state.**
   Reconcile README/report language so G15 is accepted only as a small finite-scope replay; preserve same-host, source-lineage, real-reference, business-threshold, finite-radius, and old-reference-pipeline limitations; then mark G16 complete only after all final checks pass.

Further work required.
