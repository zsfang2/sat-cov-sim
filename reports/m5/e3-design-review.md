**Verdict**

Guarded cache mismatch plus direct fallback **can satisfy declared E3**, even if it shows no gain, but only as a negative result: “current M2 cache identity is incompatible with moving TLE slant range, so precision-matched whole-pass E3 falls back to direct M1 and has no finite break-even.” That is valid evidence for AC-11/E3. It must not be reported as cache acceleration or as proof that range can be ignored.

One design trap: current `DirectionTable.query()` will raise `CacheMismatch` when `expected_descriptor` or `fallback_solver.descriptor()` differs from the table descriptor. So an anchor-range table cannot be queried with an actual-range fallback solver and expected to “fallback” inside the table API. The guarded path must catch the mismatch, record it, then call the actual M1 direct evaluator separately. See [direction_table.py](/home/Users_Work_Space/zsfang/satellite-coverage-sim/src/satellite_coverage/engine/direction_table.py) and [docs/M2.md](/home/Users_Work_Space/zsfang/satellite-coverage-sim/docs/M2.md).

**Minimal Frozen Protocol**

Freeze before any quality experiment:

- Scene: Qinling G05 60 m terrain, lon `108.9`, lat `33.9`, ground ellipsoid `1933.3074593633019 m`, antenna `+2 m AGL`, radius `3000 m`, step `15 m`, curvature `6371000`, cap `60 dB`.
- TLE: NORAD `44714`, Jan 1 source, `past_only`, `max_age_days=7`; record catalog hash and selected TLE line hash.
- Pass split: search `2025-01-01T05:00:00Z` to `2025-01-03T05:00:00Z`, min elevation `0 deg`; choose the first four chronological windows with `start_clipped=false` and `end_clipped=false`; first two development, last two holdout; observation interval is pass start/end padded by `30 s`.
- Thresholds: exactly `[-160, -150, -140] dBm`, hypothetical diagnostics only.
- Reference levels: initial `step_s=20`; refinement `(max_probe_s,event_tolerance_s)` = `(2,.1)`, `(1,.05)`, `(.5,.025)`, with predeclared escalation to `(.25,.0125)` and `(.125,.00625)` if convergence fails.
- Convergence: adjacent levels must have same event counts, matched boundary changes `<=0.1 s`, cumulative and longest state-duration changes `<=0.5 s`, no failed/unknown reference upgrade. If exhausted, mark unresolved, not passed.
- Coarse baselines: fixed `20/10/5 s` grids must be summarized without pretending interpolated roots are direct truth.
- Comparison: report per pass, threshold, candidate/channel: event counts, matched boundary deltas, false/missed windows, sufficient/insufficient/invisible/unknown seconds, opportunity optimistic/pessimistic disagreement time, failures, and denominators.

**Tolerances And Size**

The proposed tolerances are acceptable as numerical diagnostics, not business certification. I would tighten the wording: convergence is a gate to use the finest level as a reference, not an accuracy guarantee for windows narrower than the probe spacing.

Resource size is okay if kept to four passes and three thresholds. Do not expand to all 16 passes. Without memoization, threshold × refinement scans may be wasteful; that is analysis cost, not evidence quality.

Memoization across threshold scans is allowed **only** for analysis reuse of identical direct propagation evaluations, with cold timing measured separately without memoization. The ledger must still produce threshold-specific margins/events and must clearly distinguish reused analysis evaluations from cold runtime evidence.

**Safe Instrumentation**

Use a sidecar evaluator around `DirectLinkEvaluator` from [quality_events.py](/home/Users_Work_Space/zsfang/satellite-coverage-sim/src/satellite_coverage/engine/quality_events.py):

1. Call the normal M1 direct evaluator for the timestamp. This preserves propagation physics in [links.py](/home/Users_Work_Space/zsfang/satellite-coverage-sim/src/satellite_coverage/engine/links.py).
2. Extract actual azimuth/elevation/slant range from the returned record.
3. Build the actual `TerrainLocalSolver` descriptor for that range.
4. Attempt anchor table load/query with the actual descriptor.
5. On `CacheMismatch`, record `identity_mismatch_range` and use the already-computed M1 direct record as fallback.
6. Never silently approximate across range, and never alter the terrain or SGP4 path.

**Blocking Defect**

No blocking defect found in verified G10/G11 code. The blocking pre-run issue is design/execution: if the planned guarded cache path assumes the existing table API can internally fallback across slant-range mismatch, it will fail or tempt an unsafe workaround. Freeze the mismatch-catch plus external direct-M1 fallback protocol before running E3.
