"""YAML adapter for the typed scenario configuration boundary."""

from __future__ import annotations

from pathlib import Path

import yaml

from .models import ConfigError, ScenarioConfig


def load_scenario_config(path: str | Path) -> ScenarioConfig:
    """Load a YAML file into a strictly validated ``ScenarioConfig``."""

    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"unable to read scenario config: {config_path}") from exc
    return ScenarioConfig.from_mapping(raw)
