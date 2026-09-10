"""Command line runner and compact PNG/NumPy output writer."""

from __future__ import annotations

import argparse
from pathlib import Path
import numpy as np

from .scenario import CoverageScenario


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a satellite coverage scenario")
    parser.add_argument("config", help="YAML scenario configuration")
    parser.add_argument("--output", default="output", help="Output directory")
    args = parser.parse_args()
    result = CoverageScenario.from_yaml(args.config).run()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    np.save(output / "total_loss_db.npy", result.total_loss_db)
    np.save(output / "received_power_dbm.npy", result.received_power_dbm)
    for name, data in result.components.items():
        np.save(output / f"{name}.npy", data)
    try:
        import matplotlib.pyplot as plt
        plt.imsave(output / "received_power_dbm.png", result.received_power_dbm, cmap="viridis")
    except ImportError:
        pass
    print(f"satellite={result.satellite.norad_id} elevation={result.satellite.elevation_deg:.2f} deg")
    print(f"received power: {result.received_power_dbm.min():.1f} to {result.received_power_dbm.max():.1f} dBm")

