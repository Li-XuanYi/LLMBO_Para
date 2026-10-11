"""Validated six-parameter space and reversible search transforms."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Sequence

PARAMETER_NAMES = (
    "Negative electrode active material volume fraction",
    "Positive electrode active material volume fraction",
    "Negative particle diffusivity [m2.s-1]",
    "Positive particle diffusivity [m2.s-1]",
    "Negative electrode conductivity [S.m-1]",
    "Positive electrode conductivity [S.m-1]",
)


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    lower: float
    upper: float
    transform: str
    unit: str

    def __post_init__(self) -> None:
        if self.transform not in {"linear", "log10"}:
            raise ValueError(f"unsupported transform for {self.name}: {self.transform}")
        if not (math.isfinite(self.lower) and math.isfinite(self.upper) and self.lower < self.upper):
            raise ValueError(f"{self.name} requires finite lower < upper bounds")
        if self.transform == "log10" and self.lower <= 0:
            raise ValueError(f"{self.name} logarithmic bounds must be positive")


@dataclass(frozen=True)
class ParameterSpace:
    specs: tuple[ParameterSpec, ...]
    negative_porosity: float | None = None
    positive_porosity: float | None = None
    tolerance: float = 1e-12

    def __post_init__(self) -> None:
        if tuple(s.name for s in self.specs) != PARAMETER_NAMES:
            raise ValueError("parameter specs must use the documented six-parameter order")
        if any(s.lower <= 0 for s in self.specs) or any(s.upper > 1 for s in self.specs[:2]):
            raise ValueError("all six parameters must be positive; solid volume fractions cannot exceed one")
        for value in (self.negative_porosity, self.positive_porosity):
            if value is not None and (isinstance(value, bool) or not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError("electrode porosity must be in [0, 1]")
        for spec, porosity in zip(self.specs[:2], (self.negative_porosity, self.positive_porosity)):
            if porosity is not None and spec.lower + porosity > 1 + self.tolerance:
                raise ValueError("parameter bounds and fixed porosity leave no feasible electrode fraction")

    @classmethod
    def from_bounds(
        cls,
        bounds: Mapping[str, Sequence[float]],
        transforms: Mapping[str, str],
        units: Mapping[str, str],
        *,
        negative_porosity: float | None = None,
        positive_porosity: float | None = None,
    ) -> "ParameterSpace":
        specs = []
        for name in PARAMETER_NAMES:
            if name not in bounds or name not in transforms or name not in units:
                raise ValueError(f"missing parameter definition: {name}")
            lo, hi = bounds[name]
            if isinstance(lo, bool) or isinstance(hi, bool):
                raise ValueError("parameter bounds cannot be booleans")
            specs.append(ParameterSpec(name, float(lo), float(hi), transforms[name], units[name]))
        return cls(tuple(specs), negative_porosity, positive_porosity)

    @property
    def dimension(self) -> int:
        return len(self.specs)

    def validate(self, values: Sequence[float]) -> tuple[float, ...]:
        if len(values) != self.dimension:
            raise ValueError(f"expected {self.dimension} parameters; got {len(values)}")
        point = tuple(float(x) for x in values)
        for value, spec in zip(point, self.specs):
            if not math.isfinite(value) or value < spec.lower or value > spec.upper:
                raise ValueError(f"{spec.name}={value} is outside [{spec.lower}, {spec.upper}]")
        if self.negative_porosity is not None and point[0] + self.negative_porosity > 1 + self.tolerance:
            raise ValueError("negative solid fraction plus fixed porosity exceeds one")
        if self.positive_porosity is not None and point[1] + self.positive_porosity > 1 + self.tolerance:
            raise ValueError("positive solid fraction plus fixed porosity exceeds one")
        return point

    def normalize(self, values: Sequence[float]) -> tuple[float, ...]:
        point = self.validate(values)
        result = []
        for value, spec in zip(point, self.specs):
            low = math.log10(spec.lower) if spec.transform == "log10" else spec.lower
            high = math.log10(spec.upper) if spec.transform == "log10" else spec.upper
            transformed = math.log10(value) if spec.transform == "log10" else value
            result.append((transformed - low) / (high - low))
        return tuple(result)

    def denormalize(self, normalized: Sequence[float]) -> tuple[float, ...]:
        if len(normalized) != self.dimension:
            raise ValueError(f"expected {self.dimension} normalized values")
        values = []
        for value, spec in zip(normalized, self.specs):
            x = float(value)
            if not math.isfinite(x) or x < -self.tolerance or x > 1 + self.tolerance:
                raise ValueError("normalized parameters must lie in [0, 1]")
            x = min(1.0, max(0.0, x))
            low = math.log10(spec.lower) if spec.transform == "log10" else spec.lower
            high = math.log10(spec.upper) if spec.transform == "log10" else spec.upper
            mapped = low + x * (high - low)
            values.append(10**mapped if spec.transform == "log10" else mapped)
        return self.validate(values)
