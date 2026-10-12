Used the `humanize` skill and did not edit files.

**Assessment**
G16 is not complete yet. Round 15 accepted G15 for the declared same-host fresh-venv reproduction scope, but AC-1 and AC-13 remain partial until G16 supplies the final AC ledger, score-row cleanup, clean tested commit, native review gate, code-review, and finalize transition. That is explicit in [round-16-contract.md](/home/Users_Work_Space/zsfang/satellite-coverage-sim/.humanize/rlcr/2026-10-09_08-03-30/round-16-contract.md:3) and [round-15-review-result.md](/home/Users_Work_Space/zsfang/satellite-coverage-sim/.humanize/rlcr/2026-10-09_08-03-30/round-15-review-result.md:15).

**Final AC Ledger Recommendation**
Use Round 15’s audit as the seed:

| AC | G16 status framing |
|---|---|
| AC-1 | Partial until final G01-G16 evidence/limitation ledger is written. |
| AC-2 | Met for identity/reproduction scope; keep DEM/TLE upstream lineage unknown. |
| AC-3 | Met for M1 scalar behavior via accepted E1/regression evidence. |
| AC-4 | Met for M3 numerical/software scope; not physical truth. |
| AC-5 | Met for bounded-read/finite-radius contract; keep full-path proof unresolved. |
| AC-6 | Met as conditional M3 software baseline. |
| AC-7 | Met for M4/E2 three-role comparison, with reference limits. |
| AC-8 | Met for M2/E1 direction/cache scope. |
| AC-9 | Met for M5/E3 conditional event scope. |
| AC-10 | Met for M6/E4 selection/evaluation software scope. |
| AC-11 | Met for conditional E1-E4 closure. |
| AC-12 | Met for G15 finite same-host supported-env replay. |
| AC-13 | Partial until native implementation gate, code-review, fixes, and finalize evidence complete. |

Preserve the big limitations in the ledger: finite radius only; real E4 strict reference eligibility was 0/72 and the benefit remains inconclusive, not “no benefit”; business thresholds/source lineage are unknown; same-host G15 fresh-venv scope is not cross-platform; legacy scheduler/beam/weather/clutter/RNG/writer/resume/benchmark remains backlog. The E4 report is especially clear on 0/72 and inconclusive benefit in [reports/m6/e4.md](/home/Users_Work_Space/zsfang/satellite-coverage-sim/reports/m6/e4.md:22).

**Minimal Score-Row Correction**
The real code defect is in [candidate_selection.py](/home/Users_Work_Space/zsfang/satellite-coverage-sim/src/satellite_coverage/engine/candidate_selection.py:50): candidates are bounded at 256, total passes at 1000, but score rows are capped at 100000 in `_Scores` even though a valid selected split can be `256 * 999 = 255744` rows. The fix should not add another arbitrary cap.

Minimal implementation shape:

```python
required = len(expected)
if not isinstance(data["rows"], list) or len(data["rows"]) != required:
    raise ValueError("score table requires one row for each candidate/pass pair")
```

Then keep the existing per-row rejection for duplicate, foreign, wrong-split, malformed, and denominator errors. Add a true positive regression over 100000 rows, for example 256 candidates × 391 development passes plus one holdout pass. Add same-size negative regressions for missing+duplicate, foreign candidate/pass, and wrong split. Add an oversized malformed count test that is rejected by row-count mismatch before row parsing.

**Current vs Historical Docs**
Do not rewrite `goal.md` or historical archives as though they were produced at final HEAD. Add a clearly dated current status/index instead. Also update current-facing docs that are now stale: [reports/reproduction/progress.md](/home/Users_Work_Space/zsfang/satellite-coverage-sim/reports/reproduction/progress.md:3) still says Round 15 was waiting review, while Round 15 is now accepted. For G15, identify the reviewed portable snapshot as `70e93f0`; any later score-bound cleanup should be documented as G16 boundary/API cleanup after the frozen scientific snapshot, not retroactively folded into G15.

**Blockers**
Genuine implementation-completion blockers: score-row bound fix/regressions, final AC/evidence/limitation ledger, current-vs-historical doc cleanup, clean tests/commit, native review gate, code-review/fix cycle, finalize.

Queued research limitations, not blockers to G16 implementation closure: physical whole-pass M4 qualification, actual business thresholds/benefit, original DEM/TLE provenance, finite-radius/full-path proof, and legacy reference pipeline restoration.
