G07 analysis only. I did not edit files or RLCR state.

**Decision**
Use a three-role M4/E2 contract with these roles fixed:

1. `sky_horizon_outline_v1`
   Visibility-only role. Outputs horizon angle, limiting distance, blocked/clear/unknown status, finite-radius contract, and no attenuation dB. If blocked, it may support threshold disagreement on visibility only. It must not be converted into arbitrary calibrated loss.

2. `m3_current_single_edge_v1`
   Existing M3 scalar local-loss role: `local-dominant-knife-edge-v1`, finite-radius conditional, DSM/DTM/synthetic surface semantics preserved, same effective Earth radius assumption, same cap handling, same `known/not_computed/failed` propagation. This is the current software baseline, not physical truth. Current implementation is explicitly single-edge in [terrain_link.py](/home/Users_Work_Space/zsfang/satellite-coverage-sim/src/satellite_coverage/engine/terrain_link.py:1), with capped `used_loss_db` and `loss_status` in [terrain_link.py](/home/Users_Work_Space/zsfang/satellite-coverage-sim/src/satellite_coverage/engine/terrain_link.py:79).

3. `reference_multi_edge_deygout_v1`
   Recommended third role: a separately implemented recursive multi-edge diffraction solver over the same frozen paired profile geometry, using the documented ITU-R P.526 knife-edge attenuation formula and Deygout-style dominant-edge recursion. This is CPU-feasible, genuinely different from “pick one dominant edge,” and can be V1 only after convergence/failure policy is satisfied. It is still a numerical reference, not truth.

I would not use “same M3 with smaller step” as the third role. That belongs in a separate `same_model_discretization` section, because [interval_extrema.py](/home/Users_Work_Space/zsfang/satellite-coverage-sim/src/satellite_coverage/engine/interval_extrema.py:1) is already clear that stationary candidates are numerical refinement of the declared single-edge raster model, not an independent physical model.

**Third-Role Options**
- Same-model densification: useful diagnostic, V0/convergence only; cannot satisfy AC-7 as “different physical model.”
- Recursive multi-edge Deygout: best minimal choice. It compares different model assumptions while staying CPU-only and terrain-profile based.
- Independent exact diffraction reference: stronger in principle, but not minimal for G08. A Fresnel integral/parabolic-equation/UTD implementation is more work, more boundary-condition sensitive, and likely should be reserved for tiny synthetic V0 cases or later disputes.
- RT or measurements: out of scope for M4/E2. Do not require them, and do not imply they define truth.

Primary references to verify before coding: official ITU-R P.526-16, current “in force” recommendation for diffraction as of 2026-10-10, plus Deygout’s 1966 multiple knife-edge paper DOI `10.1109/TAP.1966.1138719`. The ITU page currently lists P.526-16, approved 2025-11-02, status “In force.” [ITU-R P.526-16](https://www.itu.int/rec/R-REC-P.526-16-202511-I)

**Frozen Pair Schema**
Each paired row should exist for all three roles, even when a role has no power:

`pair_id, role_id, role_version, evidence_level, solver_source, model_family, geometry_id, sample_id, candidate_id, timestamp_utc, pass_id, satellite_id, az_deg, el_deg, slant_range_m, geometrically_above_local_horizontal, scene_id, terrain_source_id, terrain_grid_sha256, surface_type, vertical_datum, grid_geometry, native_resolution_m, radius_m, step_m, sampling_method, effective_radius_m, receiver_lon_deg, receiver_lat_deg, receiver_ellipsoid_height_m, rx_height_agl_m, frequency_hz, tx_power_mode, eirp_dbm, tx_power_dbm, tx_gain_dbi, rx_gain_dbi, antenna_model_id, pointing, mean_power_definition, included_effects, excluded_effects, output_quantity, value, unit, raw_loss_db, used_loss_db, loss_cap_db, cap_triggered, received_power_dbm, margin_db, status, failure_kind, incomplete_reasons, terrain_contract, full_path_status, service_eligibility, runtime_s, peak_memory_mib, warning_flags, input_checksum, config_hash, code_commit`.

Effect rules:
- `sky_horizon_outline_v1`: `included_effects = ["terrain_horizon_geometry"]`, no `local_diffraction`, no `received_power_dbm`.
- `m3_current_single_edge_v1`: includes `local_diffraction_single_knife_edge`, but only within finite radius.
- `reference_multi_edge_deygout_v1`: includes `local_diffraction_multi_edge`, same frequency/geometry/power/antenna inputs, separate implementation identity.

**Eligibility**
- V0: analytic/synthetic cases: flat, single edge, two edges, stair/terrace, nodata, below horizon, zenith unsupported, near-receiver unsupported.
- V1: multi-edge reference only if implementation is separate, formula/version is documented, convergence sweeps are frozen before seeing results, and failures stay in paired rows.
- V2: only measured data with receiver/device/time/service metadata. None required for M4/E2.

**E2 Design**
Freeze before results:

Synthetic cases:
- flat clear path
- one knife edge where M3 and reference should agree closely
- two separated edges where M3 may differ
- ridge-edge grazing cases
- deep blocked/capped cases
- nodata/outside-radius/zenith/near-horizontal unsupported cases

Small conditional real cases:
- open terrain, ridge boundary, deep obstruction
- same finite radius and DSM restrictions as M3 acceptance
- no claim of real terrain truth

Metrics:
- horizon visibility agreement
- local-loss MAE/bias/P95 only where both roles have `known dB`
- threshold disagreement for margin sweeps
- cap rate, failure rate, unsupported rate
- runtime and peak memory

Threshold sweeps:
- power margin bands: `[-10, -6, -3, 0, +3, +6, +10] dB`
- assumption sweeps: frequency, rx height, effective radius, loss cap, radius, step
- preserve existing `0.1 deg` and `1 dB` as diagnostics only, not business standards.

**Pairwise Claims**
- Sky vs M3: visibility/blockage disagreement only; no dB error.
- Sky vs reference: visibility/blockage disagreement only.
- M3 vs reference: loss/power/margin differences only for paired rows where both are `known`, same units/effects, and not capped unless explicitly reported as capped comparison.
- Any row with unknown, unsupported, failed, not applicable, or cap-triggered must remain counted and reported outside numeric error aggregates.

**Failure Policy**
Do not drop rows. Use explicit statuses: `known`, `unknown`, `not_applicable`, `not_computed`, `failed`.

Sky-outline blocked state is final as geometry information, not a reason to synthesize `60 dB` or any calibrated attenuation. Existing code already follows this spirit: `TerrainContext` returns `not_computed` for unsupported profile states and can suppress sampled loss when horizon audit fails in [terrain_context.py](/home/Users_Work_Space/zsfang/satellite-coverage-sim/src/satellite_coverage/engine/terrain_context.py:68) and [terrain_context.py](/home/Users_Work_Space/zsfang/satellite-coverage-sim/src/satellite_coverage/engine/terrain_context.py:93).

**Negative Tests**
- Reject two-role reports claiming AC-7 complete.
- Reject unit/effect mismatches, including duplicate local loss in the link budget.
- Reject converting sky blockage to arbitrary dB.
- Reject same-model densification as V1 physical reference.
- Reject dropping failed/unsupported rows from denominators.
- Reject `known` power when terrain is finite-radius incomplete.
- Reject DSM-as-bare-earth reinterpretation.
- Reject capped-loss rows used as ordinary dB error samples without a cap flag.
- Reject post-hoc tolerance changes after seeing E2 results.

**Main Pitfalls**
The hardest conceptual trap is mixing model error with discretization error. Keep the same-model step/radius sweeps as a convergence appendix, and keep the M3-vs-Deygout comparison as the actual physics-model comparison. The second trap is power availability: all roles stay present in the paired table, but only M3/reference known-power rows support numeric received-power claims.
