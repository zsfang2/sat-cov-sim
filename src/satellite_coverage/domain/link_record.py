"""Scalar link quantities with explicit missingness and effect accounting."""

from dataclasses import asdict, dataclass
from enum import Enum
import math


class QuantityStatus(str, Enum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"
    NOT_COMPUTED = "not_computed"
    FAILED = "failed"


@dataclass(frozen=True)
class Quantity:
    value: float | None
    unit: str
    status: QuantityStatus
    reason: str

    def __post_init__(self):
        if not isinstance(self.status, QuantityStatus):
            raise ValueError("quantity status must be QuantityStatus")
        if self.unit not in {"dB", "dBm", "dBi"} or not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("quantity requires a supported unit and reason")
        if self.status is QuantityStatus.KNOWN:
            if isinstance(self.value, bool) or not isinstance(self.value, (int, float)) or not math.isfinite(self.value):
                raise ValueError("known quantity requires a finite number")
        elif self.value is not None:
            raise ValueError("unavailable quantity must have value=null")

    def to_mapping(self):
        return asdict(self)


@dataclass(frozen=True)
class LossComponent:
    name: str
    quantity: Quantity
    effects: tuple[str, ...]
    solver: str

    def __post_init__(self):
        if not self.name or not self.solver or self.quantity.unit != "dB":
            raise ValueError("loss requires name, solver and dB units")
        if not isinstance(self.effects, tuple) or not self.effects or any(not isinstance(x, str) or not x for x in self.effects):
            raise ValueError("loss requires explicit effects")
        if len(set(self.effects)) != len(self.effects):
            raise ValueError("duplicate effects within component")


def compose_received_power(eirp_dbm: float, receiver_gain_dbi: float,
                           components: tuple[LossComponent, ...]) -> Quantity:
    for value in (eirp_dbm, receiver_gain_dbi):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("power and gain must be finite")
    effects = {"transmit_gain", "receive_gain"}
    names = set()
    for component in components:
        if component.name in names or effects.intersection(component.effects):
            raise ValueError("duplicate component or effect in link budget")
        effects.update(component.effects)
        names.add(component.name)
    unavailable = [c for c in components if c.quantity.status is not QuantityStatus.KNOWN]
    if unavailable:
        status = (QuantityStatus.FAILED if any(c.quantity.status is QuantityStatus.FAILED for c in unavailable)
                  else QuantityStatus.NOT_COMPUTED)
        return Quantity(None, "dBm", status, "unavailable_components:" + ",".join(c.name for c in unavailable))
    return Quantity(eirp_dbm + receiver_gain_dbi - math.fsum(c.quantity.value for c in components),
                    "dBm", QuantityStatus.KNOWN, "scalar_mean_power_budget")
