- [P2] Handle missing package metadata in visibility results — /home/Users_Work_Space/zsfang/satellite-coverage-sim/src/satellite_coverage/orbit/visibility.py:281-281
  When running from a source checkout via `PYTHONPATH` rather than an installed wheel/editable install, `version("satellite-coverage-sim")` raises `PackageNotFoundError`, so `calculate_visibility()` and Explorer visibility jobs fail after doing the propagation work. This repository configures pytest with `pythonpath = ["src"]`, so source-tree test/developer runs hit this path; use a guarded lookup or a fallback value as done in `environment_record()`.
The visibility API can fail in the repository's normal source-tree execution mode because it assumes installed distribution metadata is present. This breaks tests and Explorer jobs despite otherwise valid inputs.

Review comment:

- [P2] Handle missing package metadata in visibility results — /home/Users_Work_Space/zsfang/satellite-coverage-sim/src/satellite_coverage/orbit/visibility.py:281-281
  When running from a source checkout via `PYTHONPATH` rather than an installed wheel/editable install, `version("satellite-coverage-sim")` raises `PackageNotFoundError`, so `calculate_visibility()` and Explorer visibility jobs fail after doing the propagation work. This repository configures pytest with `pythonpath = ["src"]`, so source-tree test/developer runs hit this path; use a guarded lookup or a fallback value as done in `environment_record()`.
