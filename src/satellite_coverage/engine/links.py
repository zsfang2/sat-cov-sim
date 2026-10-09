"""M1 candidate link sequence: one pipeline for fixed, synthetic and TLE inputs."""

from skyfield.framelib import itrs

from ..config.link import LinkConfig, enabled_losses, sample_times
from ..config.pilot import identity
from ..geometry.antenna import receive_gain
from ..geometry.geodetic import antenna_position, ecef_and_basis, ecef_geometry
from ..geometry.local import relative_enu_geometry, direction_to_enu
from ..orbit.visibility import TS, select_record
from .link_budget import compose_budget
from .terrain_contract import terrain_scope, attach_terrain_contract


def select_tle(catalog, source, times):
    if catalog is None:
        raise ValueError("TLE source requires a catalog")
    norad = source["norad_id"]
    if norad not in catalog.records:
        raise ValueError("NORAD ID is absent from catalog")
    sat = select_record(catalog.records[norad], times[0], source["tle_policy"])
    selection = {"policy": source["tle_policy"], "fixed_over_interval": True,
                 "catalog_sha256": catalog.checksum, "norad_id": norad}
    if sat is None:
        return None, selection, "no_tle_at_or_before_start"
    epoch = sat.epoch.utc_datetime()
    age = max(abs((t-epoch).total_seconds()) for t in (times[0], times[-1])) / 86400
    selection.update(epoch_utc=epoch.isoformat(), record_sha256=sat.record_sha256,
                     uses_future_epoch=epoch > times[0], max_epoch_offset_days=age)
    return sat, selection, "tle_epoch_exceeds_max_age_days" if age > source["max_age_days"] else None


def input_geometry(source, index, time, receiver, satellite):
    mode = source["mode"]
    if mode in ("relative_enu_sequence", "direction_sequence"):
        enu = (source["positions_enu_m"][index] if mode == "relative_enu_sequence"
               else direction_to_enu(**source["directions"][index]))
        position, _ = ecef_and_basis(receiver)
        return {**relative_enu_geometry(enu), "satellite_relative_enu_m": enu,
                "receiver_ecef_m": list(position), "satellite_ecef_m": None,
                "position_meaning": "receiver-relative antenna vector; no height added again"}
    if mode == "fixed_ecef":
        xyz = source["position_ecef_m"]
    else:
        position = satellite.at(TS.from_datetime(time))
        if position.message:
            raise ValueError(f"SGP4: {position.message}")
        xyz = [float(v) for v in position.frame_xyz(itrs).m]
    return ecef_geometry(receiver, xyz)


def calculate_links(config, catalog=None, *, terrain=None):
    config = config if isinstance(config, LinkConfig) else LinkConfig.from_mapping(config)
    data, config_id = config.to_mapping(), config.checksum
    times = sample_times(data)
    receiver = antenna_position(data["receiver"])
    source, budget = data["source"], data["budget"]
    terrain_descriptor = None
    if terrain is not None:
        if budget["losses"]["local"]["enabled"]:
            raise ValueError("disable declared local loss before enabling terrain; duplicate local effects")
        terrain.validate_receiver(receiver)
        terrain_descriptor = terrain.descriptor()
    satellite, unavailable = None, None
    selection = {"policy": "not_applicable", "candidate_id": source["candidate_id"]}
    if source["mode"] == "tle":
        satellite, selection, unavailable = select_tle(catalog, source, times)
    physical_id = identity({"config_checksum": config_id, "terrain": terrain_descriptor, "selection": selection})
    losses = enabled_losses(budget["losses"])
    records = []
    for index, time in enumerate(times):
        record = {"sample_id": f"{data['experiment_id']}:{source['candidate_id']}:{index}",
                  "timestamp_utc": time.isoformat(), "candidate_id": source["candidate_id"],
                  "norad_id": source.get("norad_id"), "config_checksum": config_id,
                  "input_type": source["mode"], "service_eligibility": "unknown", "geometry": None, "budget": None}
        if unavailable:
            record.update(status="not_computed", reason=unavailable)
        else:
            try:
                geometry = input_geometry(source, index, time, receiver, satellite)
                sample_losses = dict(losses)
                if terrain is not None:
                    terrain_result = terrain.evaluate({**geometry, "frequency_hz": budget["frequency_hz"]}, receiver)
                    record["terrain"] = terrain_result
                    record["physical_input_checksum"] = physical_id
                    sample_losses["local"] = {"value": terrain_result["used_loss_db"],
                                              "status": terrain_result["loss_status"],
                                              "reason": "M3 sampled local terrain; outside radius unverified"}
                    geometry["terrain_visibility"] = terrain_result["los_status"]
                antenna = receive_gain(budget["receiver_antenna"], geometry["satellite_relative_enu_m"])
                computed = compose_budget(geometry, budget["frequency_hz"], budget["power"],
                                          antenna["gain_dbi"], sample_losses, budget["threshold"])
                computed["receiver_antenna"] = antenna
                for component in computed["components"]:
                    name = component["name"]
                    component["enabled"] = True if name == "fspl" else budget["losses"][name]["enabled"]
                    if name == "local" and terrain is not None:
                        component.update(enabled=True, solver="local-dominant-knife-edge-v1")
                    component["reference_power"] = "eirp_plus_receive_gain"
                    component["averaging"] = "scalar_mean_power; no stochastic fading or coherent phase"
                record.update(status="computed", geometry=geometry, budget=computed)
                if terrain is not None and geometry["geometrically_above_local_horizontal"] and not terrain_result["coverage_complete"]:
                    record.update(status="not_computed", reason="terrain_coverage_incomplete")
                if computed["received_power"]["status"] == "failed":
                    record.update(status="failed", reason="component_solver_failed")
            except (ValueError, RuntimeError, OverflowError) as exc:
                record.update(status="failed", reason=str(exc))
        if terrain is not None:
            attach_terrain_contract(record, terrain_descriptor, physical_id,
                                    budget['frequency_hz'], receiver)
        records.append(record)
    result = {"schema_version": 1, "request": data, "receiver": receiver, "selection": selection,
            "config_checksum": config_id, "records": records,
            "complete": all(r["status"] == "computed" for r in records),
            "scope": "sampled candidate scalar mean power; declared antenna/losses; no terrain, refraction or service verification",
            "time_grid": "includes both endpoints; final step may be shorter; not an event-window solver",
            "power_meaning": "conditional on declared assumptions; computed geometry does not imply known received power"}
    if terrain is not None:
        result.update(terrain=terrain_descriptor, physical_input_checksum=physical_id,
                      terrain_contract=terrain_scope(terrain_descriptor),
                      scope="M1 plus sampled local terrain within declared radius; outside terrain and service unverified")
    return result
