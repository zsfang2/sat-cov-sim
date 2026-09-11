"""Immutable NumPy array values with explicit semantic metadata."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .units import ArrayUnit, DomainStateError


@dataclass(frozen=True, eq=False)
class DomainArray:
    """An immutable array plus unit, coordinate system, and named axes."""

    values: np.ndarray
    unit: ArrayUnit
    coordinate_system: str
    axes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.unit, ArrayUnit):
            raise DomainStateError("unit must be an ArrayUnit")
        _require_text("coordinate_system", self.coordinate_system)
        if not isinstance(self.axes, tuple):
            raise DomainStateError("axes must be a tuple")
        if any(not isinstance(axis, str) or not axis or axis != axis.strip() for axis in self.axes):
            raise DomainStateError("axes must contain non-empty trimmed names")
        if len(self.axes) != len(set(self.axes)):
            raise DomainStateError("axes must contain unique names")

        try:
            source = np.asarray(self.values)
        except (TypeError, ValueError) as exc:
            raise DomainStateError("values must be a regular NumPy-compatible array") from exc
        if source.ndim != len(self.axes):
            raise DomainStateError("axes count must match array dimensions")
        if not (
            np.issubdtype(source.dtype, np.number)
            or np.issubdtype(source.dtype, np.bool_)
        ) or np.issubdtype(source.dtype, np.complexfloating):
            raise DomainStateError("values dtype must be real numeric or boolean")
        if np.issubdtype(source.dtype, np.number) and not np.isfinite(source).all():
            raise DomainStateError("values must contain only finite numbers")

        contiguous = np.ascontiguousarray(source)
        immutable = np.frombuffer(
            contiguous.tobytes(order="C"),
            dtype=contiguous.dtype,
        ).reshape(contiguous.shape)
        object.__setattr__(self, "values", immutable)

    @property
    def shape(self) -> tuple[int, ...]:
        return self.values.shape

    @property
    def dtype(self) -> np.dtype:
        return self.values.dtype


def _require_text(name: str, value: object) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise DomainStateError(f"{name} must be non-empty and trimmed")
