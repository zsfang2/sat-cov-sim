**Blockers**
G14 is not ready to execute until a frozen E4 design/receipt file exists. The current contract correctly requires consultation/freeze before quality runs. No tracked edits, experiments, loop-state changes, or completion claims should happen yet.

Main blockers to freeze:

1. Three Qinling sites need exact identities before any quality evidence:
   `Q0=(0,0)`, `Q_E300=(300,0)`, `Q_N300=(0,300)` in local ENU from `(108.9E, 33.9N)`, converted to lon/lat/ellipsoid height with 2 m AGL, each with its own centered 60 m, 3 km bounded DEM/geoid grid. Do not reuse one shifted grid as if centered.

2. Pass eligibility must be geometry-only and frozen first:
   find chronological complete passes 5-8 for NORAD 44714 over `2025-01-01T05:00Z` to `2025-01-03T05:00Z`, `past_only`. Best minimal rule: ordinal by origin-site no-terrain geometry, observation window is the three-site union geometry window plus 30 s padding. Passes 5-6 development, 7-8 holdout.

3. Sky layer semantics need to be strict:
   `sky_horizon_outline_v1` can mark geometric blocked/clear/unknown, but it must not emit loss, received power, or threshold sufficiency. Clear sky should become quality `unknown`, blocked sky can become known geometric unavailable. No fake dB.

4. Common holdout must be one reference table:
   each layer selects from its own development scores, but all selections are evaluated against the same holdout M4 reference scores. Otherwise `compare_evaluations()` cannot honestly compare gain/regret.

**Smallest Valid Protocol**
Use four development information layers for each of six scenarios: `(EIRP 55,45 dBm) x thresholds (-160,-150,-140 dBm)`.

Layers:

- `no_terrain`: M1 direct FSPL + declared atmosphere, no local terrain.
- `sky_proxy`: M4 sky horizon only; no attenuation.
- `m3_single_edge`: existing `TerrainContext` / M3 local loss.
- `m4_multi_edge_reference`: existing `compare_models()` multi-edge role, with eligibility checks.

Pipeline:

1. Build `CandidateSet` with three equal-cost 2 m AGL sites.
2. Build `PassRegistry` with passes 5-8, development before holdout.
3. For each scenario and layer, construct development score rows only for passes 5-6 using `direct_events()` and `score_row_from_events()`.
4. Create and persist all `SelectionReceipt`s before constructing any holdout score rows.
5. Construct holdout passes 7-8 once as the common M4 reference table. Noneligible reference intervals become `unknown_s`, not dropped.
6. Evaluate every receipt with `evaluate_selection(receipt, common_holdout)`.
7. Use `compare_evaluations()` per scenario with `no_terrain` as baseline, preserving zero and negative gains.
8. Report rankings, selected site, oracle site, cumulative `insufficient/invisible/unknown`, longest unavailable, regret, gain, missing-reference counts, and costs.

**Reference Checks**
Spatial reference: use 15 / 7.5 / 3.75 m profile steps for M4 reference eligibility only. Require both adjacent raw-loss deltas `<=0.1 dB`, stable LOS, stable cap state, and all three levels completed. This is a discretization diagnostic, not physical truth.

Temporal reference: use direct probes `1 / 0.5 / 0.25 s` with brackets `0.05 / 0.025 / 0.0125 s`. Require two adjacent passing comparisons. Do not add 0.125 s after seeing outcomes; mark noneligible reference as unknown.

**Cost Assessment**
The full 15/7.5/3.75 m plus 1/.5/.25 s design is tractable only if propagation ledgers are shared by analysis identity, not recomputed per threshold. EIRP/threshold changes should derive margins from archived propagation; report that as shared analysis reuse, not an acceleration claim.

Expected cost is materially above E3: three sites, four whole passes, four layers, and six scenarios. The row-cap issue does not block this small run: score tables are only `3 candidates x 2 passes = 6 rows` per split/scenario/layer.

Costs to report separately: grid preparation per site, no-terrain geometry, shared M4 preparation, sky/M3/multi-edge role wall time, event refinement, threshold derivation, selection/evaluation, I/O/figures, and RSS with attribution limits. Installation cost remains equal and separate from compute cost.

**Research Judgment**
Because business thresholds and minimum useful gain are undetermined, the final judgment should be conditional: “continue”, “adjust”, or “inconclusive due reference unknowns”, based on observed holdout gain/regret and unknown counts. No service or deployment claim is valid.
