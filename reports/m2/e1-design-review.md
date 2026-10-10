**Verdict**

Accept the Round 10 E1 matrix, with a few tightenings before YAML. It matches the E1 requirement to vary power, antenna, frequency, direction, and height, and to compare direct calculation with cache recomposition before claiming reuse. That is exactly the scope in [plan.md](/home/Users_Work_Space/zsfang/satellite-coverage-sim/plan.md:309) and AC-11 in [docs/humanize261009plan.md](/home/Users_Work_Space/zsfang/satellite-coverage-sim/docs/humanize261009plan.md:87).

Do not relax tolerances. Keep `1e-6 dB` only for exact-sample or strict direct-fallback recomposition checks. Held-out nearest/bilinear errors are diagnostics only, with no post-hoc passing threshold.

**Freeze These Parameters**

Use:

| Area | Final minimal parameter |
| --- | --- |
| Scenes | `flat_synthetic` and archived G05 Qinling mountain 60 m grid |
| Local solver | actual `TerrainLocalSolver`, no mock component arithmetic |
| Radius / step | flat `150 m / 5 m`; Qinling `3000 m / 15 m` |
| Curvature / cap | `effective_radius_m=6371000`, `loss_cap_db=60` |
| Frequencies | `14.5e9 Hz`, `1.0e9 Hz` |
| Heights | `2 m AGL`, `10 m AGL`; convert to scene-specific ellipsoid height before solver/config |
| Slant range | `550000 m`, fixed in both `TerrainLocalSolver` and M1 `direction_sequence` |
| Baseline | `14.5 GHz`, `2 m AGL`, `EIRP=40 dBm`, isotropic `0 dBi`, `az=0`, `el=5` |
| Tables | azimuth steps `30 deg` and `15 deg`; elevations `[0,5,10,15,20,25,30]` |
| Held-out directions | azimuths `7.5 + 15*k`, `k=0..23`; elevations `2.5 + 5*k`, `k=0..5`; 144 directions, disjoint from both table grids |
| Antenna factor | cosine receiver antenna: `peak_gain_dbi=12`, `floor_gain_dbi=-20`, `exponent=2`, `boresight_enu=[0,1,1]`, `basis=receiver_enu` |
| Single factors | `power+10 dB`; cosine antenna; `frequency=1 GHz`; `direction=15/7.5`; `height=10 m AGL` |
| Joint cases | `direction=15/7.5 + cosine antenna`; `frequency=1 GHz + height=10 m AGL` |

For cache identities, build separate tables where the local identity changes: baseline `14.5 GHz/2 m`, `1 GHz/2 m`, `14.5 GHz/10 m`, and `1 GHz/10 m`, for both scenes and both azimuth resolutions. Power and antenna changes may reuse the same local table; frequency, height, range, terrain, radius, step, cap, curvature, or source changes must not.

This follows the current identity design: local tables exclude FSPL, power, and antenna gain, but bind frequency, receiver height, finite slant range, terrain scope, cap, model fingerprint, and averaging semantics in [direction_table.py](/home/Users_Work_Space/zsfang/satellite-coverage-sim/src/satellite_coverage/engine/direction_table.py:89). The docs also explicitly say slant range remains a cache dependency, not a removable convenience in [docs/M2.md](/home/Users_Work_Space/zsfang/satellite-coverage-sim/docs/M2.md:24).

**Accuracy Protocol**

Run three separate comparisons:

1. `strict_fallback`: query with explicit error tolerance and fallback solver. Non-sample held-out directions should become direct fallback because interpolation error is not certified. These can be checked against direct local/M1 recomposition at `1e-6 dB`.

2. `nearest_raw_diagnostic`: query nearest without an error tolerance. Preserve every `known`, `not_applicable`, `not_computed`, `failed`, cap, and fallback row in the denominator.

3. `bilinear_raw_diagnostic`: same as nearest. Do not cross incompatible status/cap/visibility stencils. Current code correctly falls back on incompatible stencils in [direction_table.py](/home/Users_Work_Space/zsfang/satellite-coverage-sim/src/satellite_coverage/engine/direction_table.py:311).

For non-exact nearest/bilinear rows, report signed error, absolute error, status, cap flag, fallback reason, and denominator. No “pass” claim.

**M1 Crosscheck**

For every supported factor row, run actual `calculate_links` with `direction_sequence`, same scene receiver, same `slant_range_m=550000`, same frequency, same antenna, same power, and terrain enabled. Compare:

- geometry: azimuth, elevation, slant range
- FSPL and receiver antenna gain
- direct terrain local `used_loss_db`, raw/cap/status
- received power and margin

The current M1 path evaluates terrain, then composes the scalar budget in [links.py](/home/Users_Work_Space/zsfang/satellite-coverage-sim/src/satellite_coverage/engine/links.py:80), so this is the right end-to-end guard against accidentally testing only component addition.

**Cost Protocol**

Use five repeats for hot query and direct timing, report median and range. Record cold build, disk reload, JSON storage bytes, table sample count, fallback rate, and status denominators.

Break-even should be reported as:

`Q_build = ceil(build_s / (direct_s - query_s))` only if `query_s < direct_s`.

Also report existing-cache reuse:

`Q_reload = ceil(reload_s / (direct_s - query_s))` only if `query_s < direct_s`.

If `query_s >= direct_s`, write `no_finite_break_even`. This is important, not a failure to hide. It matches the cost formula in [plan.md](/home/Users_Work_Space/zsfang/satellite-coverage-sim/plan.md:373).

**Missing Negative Checks**

Add these to the frozen evidence checklist before results:

- Reusing a `14.5 GHz` table for `1 GHz` must raise/reject.
- Reusing a `2 m AGL` table for `10 m AGL` must raise/reject.
- Reusing a `550 km` table for any changed slant range, for example `551 km`, must raise/reject.
- Reusing flat scene cache for Qinling, or changing radius/step/cap/curvature/source hash, must raise/reject.
- Held-out strict query with `error_tolerance_db` must direct-fallback, not silently interpolate.
- Query without fallback solver must return `fallback_required` where strict direct solve is needed.
- `0 deg` and `360 deg` azimuth equivalence should be retained.
- Elevation `0` and below must keep `not_applicable`, not become zero loss.
- Cap-triggered rows must remain in denominators with both raw and used loss.
- Qinling source hashes and receiver/ground height conversion must be recorded before running, so the real scene is not selected or adjusted after seeing errors.

No experiments are claimed here. This is only the pre-results design integration recommendation, and I did not modify files.
