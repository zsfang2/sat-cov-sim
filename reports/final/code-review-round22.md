- [P2] Clamp cell-horizon cuts to the raster extent — /home/Users_Work_Space/zsfang/satellite-coverage-sim/src/satellite_coverage/geometry/cell_horizon.py:32-35
  When a valid request uses a fine-resolution grid or a radius that extends outside a small DEM, `first`/`last` are derived only from the ray length, so this loop enumerates every hypothetical grid line out to `radius_m` even beyond the raster. With the allowed 100 km radius and sub-meter grids this can create millions of cuts or effectively hang before reporting `outside_dem`; clamp to the actual row/column range or add the same boundary-crossing budget used by `cell_profile`.
The patch adds an unbounded boundary traversal in the cell-horizon path that can make valid fine-resolution or out-of-extent terrain requests hang or consume excessive memory.

Review comment:

- [P2] Clamp cell-horizon cuts to the raster extent — /home/Users_Work_Space/zsfang/satellite-coverage-sim/src/satellite_coverage/geometry/cell_horizon.py:32-35
  When a valid request uses a fine-resolution grid or a radius that extends outside a small DEM, `first`/`last` are derived only from the ray length, so this loop enumerates every hypothetical grid line out to `radius_m` even beyond the raster. With the allowed 100 km radius and sub-meter grids this can create millions of cuts or effectively hang before reporting `outside_dem`; clamp to the actual row/column range or add the same boundary-crossing budget used by `cell_profile`.
