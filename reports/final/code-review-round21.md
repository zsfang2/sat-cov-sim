- [P2] Do not swallow cache identity mismatches — /home/Users_Work_Space/zsfang/satellite-coverage-sim/src/satellite_coverage/engine/direction_table.py:241-241
  When a provider returns a response whose terrain contract or cap does not match the descriptor, this code raises `CacheMismatch` and immediately catches it because `CacheMismatch` subclasses `ValueError`. In that scenario `DirectionTable.build()` records a failed sample under the requested descriptor instead of refusing the cache, so a misbound or buggy solver can produce a cache file that appears identity-valid. Let `CacheMismatch` propagate while still converting ordinary numerical solver failures to failed samples.
The direction-table cache can silently accept provider identity/scope mismatches as failed samples, undermining the cache binding guarantees. This should be fixed before considering the patch correct.

Review comment:

- [P2] Do not swallow cache identity mismatches — /home/Users_Work_Space/zsfang/satellite-coverage-sim/src/satellite_coverage/engine/direction_table.py:241-241
  When a provider returns a response whose terrain contract or cap does not match the descriptor, this code raises `CacheMismatch` and immediately catches it because `CacheMismatch` subclasses `ValueError`. In that scenario `DirectionTable.build()` records a failed sample under the requested descriptor instead of refusing the cache, so a misbound or buggy solver can produce a cache file that appears identity-valid. Let `CacheMismatch` propagate while still converting ordinary numerical solver failures to failed samples.
