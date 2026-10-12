- [P2] Guard the explorer entry point — /home/Users_Work_Space/zsfang/satellite-coverage-sim/src/satellite_coverage/explorer/__main__.py:3-3
  Importing `satellite_coverage.explorer.__main__` currently starts the HTTP server because `main()` runs at module import time. This breaks tooling that imports package modules for discovery or validation (for example, `pkgutil`/import-all checks) by binding a socket or blocking instead of merely importing; wrap the call in an `if __name__ == "__main__":` guard so `python -m satellite_coverage.explorer` still works without import side effects.
The explorer __main__ module has an import-time side effect that can start or fail the server during module discovery. This should be fixed before the patch is considered correct.

Review comment:

- [P2] Guard the explorer entry point — /home/Users_Work_Space/zsfang/satellite-coverage-sim/src/satellite_coverage/explorer/__main__.py:3-3
  Importing `satellite_coverage.explorer.__main__` currently starts the HTTP server because `main()` runs at module import time. This breaks tooling that imports package modules for discovery or validation (for example, `pkgutil`/import-all checks) by binding a socket or blocking instead of merely importing; wrap the call in an `if __name__ == "__main__":` guard so `python -m satellite_coverage.explorer` still works without import side effects.
