"""Read explicitly declared legacy labels without inferring physical meaning."""

from dataclasses import dataclass
import math
from pathlib import Path
import re

import numpy as np

from ..data_sources.manifest import checksum_sha256, SourceIntegrityError
from ..domain.validation import ArtifactValidationStatus


def verify_file(path, expected_checksum):
    if not isinstance(expected_checksum, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_checksum):
        raise ValueError("expected checksum must be sha256:<64 lowercase hex digits>")
    actual = checksum_sha256(path)
    if actual != expected_checksum:
        raise SourceIntegrityError(f"checksum mismatch for {path}: expected {expected_checksum}, got {actual}")
    return actual


@dataclass(frozen=True)
class LabelSpec:
    label_type: str
    unit: str
    included_effects: tuple[str, ...]
    evidence: str
    normalization: dict | None = None
    affected_by_cf01: bool | None = None

    def __post_init__(self):
        allowed = {"received_power": {"dBm", "dBW"}, "path_loss": {"dB"},
                   "net_loss": {"dB"}, "normalized": {"dimensionless"}, "unknown": {"unknown"}}
        if self.label_type not in allowed or self.unit not in allowed[self.label_type]:
            raise ValueError("label type and unit are incompatible")
        if not isinstance(self.evidence, str) or not self.evidence.strip():
            raise ValueError("label evidence must be supplied")
        if not isinstance(self.included_effects, tuple) or not self.included_effects:
            raise ValueError("included_effects must explicitly declare effects or unknown")
        if any(not isinstance(x, str) or not x for x in self.included_effects) or len(set(self.included_effects)) != len(self.included_effects):
            raise ValueError("effects must be unique nonempty strings")
        if self.affected_by_cf01 is not None and type(self.affected_by_cf01) is not bool:
            raise ValueError("affected_by_cf01 must be boolean or null")
        if self.label_type != "normalized" and self.normalization is not None:
            raise ValueError("normalization only applies to normalized labels")
        if self.normalization is not None:
            n = self.normalization
            if not isinstance(n, dict) or set(n) != {"formula", "scale", "offset", "output_unit", "output_label_type"}:
                raise ValueError("normalization requires affine inverse formula and units")
            if n["formula"] != "physical = stored * scale + offset":
                raise ValueError("only the declared affine inverse is supported")
            for k in ("scale", "offset"):
                if isinstance(n[k], bool) or not isinstance(n[k], (int, float)) or not math.isfinite(n[k]):
                    raise ValueError("normalization parameters must be finite")
            if n["scale"] == 0:
                raise ValueError("normalization must be invertible")
            if n["output_label_type"] not in {"received_power", "path_loss", "net_loss"} or n["output_unit"] not in allowed[n["output_label_type"]]:
                raise ValueError("invalid denormalized label/unit")


def physical_values(values, spec):
    """Return physical values and semantic label; unavailable conversions fail."""
    a = np.asarray(values)
    if a.dtype.kind not in "fiu" or not a.size or not np.isfinite(a).all():
        raise ValueError("physical comparison requires nonempty, finite real arrays")
    a = a.astype(np.float64)
    if spec.label_type == "unknown":
        raise ValueError("cannot infer physical units for unknown labels")
    unit, label = spec.unit, spec.label_type
    if label == "normalized":
        if spec.normalization is None:
            raise ValueError("missing inverse normalization parameters; dB error prohibited")
        n = spec.normalization
        a = a * n["scale"] + n["offset"]
        unit, label = n["output_unit"], n["output_label_type"]
    if unit == "dBW":
        a = a + 30.0
        unit = "dBm"
    if not np.isfinite(a).all():
        raise ValueError("nonfinite values after physical conversion")
    return a, unit, label


def mean_absolute_error_db(left, left_spec, right, right_spec):
    a, au, al = physical_values(left, left_spec)
    b, bu, bl = physical_values(right, right_spec)
    if a.shape != b.shape or (au, al) != (bu, bl) or set(left_spec.included_effects) != set(right_spec.included_effects):
        raise ValueError("incompatible shape, label, units or included effects")
    if "unknown" in left_spec.included_effects:
        raise ValueError("unknown effects cannot support a physical comparison")
    return float(np.mean(np.abs(a - b)))


def audit_legacy_array(path, spec, expected_checksum):
    checksum = verify_file(path, expected_checksum)
    a = np.load(path, allow_pickle=False)
    if not isinstance(a, np.ndarray) or a.dtype.kind not in "fiu" or not a.size:
        raise ValueError("legacy adapter requires a nonempty real numeric NPY array")
    finite = np.isfinite(a)
    physical = None
    issue = None
    try:
        values, unit, label = physical_values(a, spec)
        physical = {"unit": unit, "label_type": label, "min": float(values.min()),
                    "max": float(values.max()), "mean": float(values.mean())}
    except ValueError as exc:
        issue = str(exc)
    return {
        "path": str(Path(path).resolve()), "checksum": checksum,
        "shape": list(a.shape), "dtype": str(a.dtype),
        "label_type": spec.label_type, "unit": spec.unit,
        "included_effects": list(spec.included_effects), "label_evidence": spec.evidence,
        "normalization": spec.normalization, "finite_fraction": float(finite.mean()),
        "physical_summary": physical, "conversion_issue": issue,
        "artifact_status": (ArtifactValidationStatus.INVALIDATED_BY_CF_01.value
                            if spec.affected_by_cf01 else ArtifactValidationStatus.LEGACY_UNVALIDATED.value),
        "cf01_applicability": spec.affected_by_cf01,
    }
