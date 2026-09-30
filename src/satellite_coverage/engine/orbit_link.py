"""A single candidate's sampled TLE-to-power experiment, without service selection."""

from copy import deepcopy
from ..config.pilot import identity, exact_keys
from ..config.link import LinkConfig
from .links import calculate_links


def adapt_request(data):
    exact_keys(data, {"schema_version", "norad_id", "start", "end", "step_s", "tle_policy",
                      "max_age_days", "receiver", "budget"}, "orbit link request")
    budget = data["budget"]
    exact_keys(budget, {"frequency_hz", "power", "receiver_gain_dbi", "losses", "threshold", "assumption_basis"}, "budget")
    common = {k: deepcopy(data[k]) for k in ("schema_version", "start", "end", "step_s", "receiver")}
    common.update(experiment_id="orbit-link", source={"mode": "tle", "candidate_id": data["norad_id"],
                  **{k: data[k] for k in ("norad_id", "tle_policy", "max_age_days")}})
    common["budget"] = {k: deepcopy(budget[k]) for k in ("frequency_hz", "power", "threshold", "assumption_basis")}
    common["budget"]["receiver_antenna"] = {"model": "isotropic", "gain_dbi": budget["receiver_gain_dbi"], "basis": budget["assumption_basis"]}
    common["budget"]["losses"] = {name: {"enabled": True, **loss} for name, loss in budget["losses"].items()}
    return LinkConfig.from_mapping(common)


def calculate_orbit_links(catalog, data):
    result = calculate_links(adapt_request(data), catalog)
    result.update(request=deepcopy(data), config_checksum=identity(data))
    # Retain the first-batch scalar result schema for existing callers.
    for record in result["records"]:
        record["config_checksum"] = result["config_checksum"]
        if record["budget"]:
            record["budget"].pop("receiver_antenna")
            for component in record["budget"]["components"]:
                for key in ("enabled", "reference_power", "averaging"):
                    component.pop(key)
    return result
