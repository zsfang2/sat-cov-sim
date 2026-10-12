- [P2] Guard benchmark-risk check for invalid change records — /home/Users_Work_Space/zsfang/satellite-coverage-sim/src/satellite_coverage/domain/release.py:208-211
  When `numerical_change_records` is malformed (for example `None` or a tuple containing a non-`NumericalChangeRecord`) and an approval is present, `readiness_issues` records `numerical_change_records` as a blocking issue but this branch still calls `_benchmark_recompute_risk`. That helper then iterates/accesses the invalid records and raises `TypeError`/`AttributeError` instead of the intended `RegenerationBlocked`, so the release gate can crash rather than fail closed with actionable issues.
The regeneration gate has an invalid-evidence path that raises an unexpected exception instead of the documented blocking error. This is a correctness issue in the newly added release policy code.

Review comment:

- [P2] Guard benchmark-risk check for invalid change records — /home/Users_Work_Space/zsfang/satellite-coverage-sim/src/satellite_coverage/domain/release.py:208-211
  When `numerical_change_records` is malformed (for example `None` or a tuple containing a non-`NumericalChangeRecord`) and an approval is present, `readiness_issues` records `numerical_change_records` as a blocking issue but this branch still calls `_benchmark_recompute_risk`. That helper then iterates/accesses the invalid records and raises `TypeError`/`AttributeError` instead of the intended `RegenerationBlocked`, so the release gate can crash rather than fail closed with actionable issues.
