from dataclasses import asdict, dataclass, field
import math
from pathlib import Path
import yaml


@dataclass(frozen=True)
class Rules:
    body_min: float = 0
    body_max: float = 100
    upper_min: float = 0
    upper_max: float = 100
    lower_min: float = 0
    lower_max: float = 100
    range_min: float = 0
    direction: str = "any"
    top_n: int = 0  # keep only the N largest-range candles in the window (0 = keep all)


@dataclass(frozen=True)
class Config:
    volatility_window: int = 20
    lookback: int = 42
    recent_window: int = 14
    horizon: int = 42
    max_sources: int = 200
    depth: float = (
        0  # >0: total surface depth is capped at this value (strengths are normalised); 0 = legacy
    )
    include_launch: bool = False
    anchor: str = "close"
    dent_scale: float = 1  # scales candle dents after depth normalization
    strength: float = 1
    sigma_x: float = 2
    sigma_y: float = 1
    kernel: str = "gaussian"
    projection: str = "reflect"
    ring_weight: float = 1
    scale_factor: float = 3
    scale_beta: float = 0.5
    price_mirror: bool = False
    coupling: float = 0.15
    damping: float = 0.15
    tau: float = 3
    acceleration_clip: float = 3
    push: float = 1.0  # multiplies the launch velocity (how hard the ball is pushed)
    throw: float = 1.0  # multiplies the launch acceleration (how hard it is thrown)
    initial_estimator: str = "difference"
    background_k: float = 0
    background_window: int = 100
    rtol: float = 1e-8
    atol: float = 1e-10
    max_step: float = 0.25
    samples_per_bar: int = 5
    bar_minutes: int = 1
    seed: int = 7
    touch_delta: int = 1
    touch_width: float = 0.25
    noise: float = 0.12
    ensemble_paths: int = 100
    ensemble_dt: float = 0.1
    rules: Rules = field(default_factory=Rules)

    def validate(self):
        for key in (
            "volatility_window",
            "lookback",
            "recent_window",
            "horizon",
            "max_sources",
            "samples_per_bar",
            "bar_minutes",
            "ensemble_paths",
            "background_window",
        ):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{key} must be a positive integer")
        for key in (
            "sigma_x",
            "sigma_y",
            "tau",
            "rtol",
            "atol",
            "max_step",
            "ensemble_dt",
            "scale_factor",
        ):
            if not math.isfinite(getattr(self, key)) or getattr(self, key) <= 0:
                raise ValueError(f"{key} must be finite and positive")
        for key in (
            "coupling",
            "damping",
            "background_k",
            "noise",
            "acceleration_clip",
            "touch_width",
            "depth",
            "push",
            "throw",
            "dent_scale",
        ):
            if not math.isfinite(getattr(self, key)) or getattr(self, key) < 0:
                raise ValueError(f"{key} must be finite and nonnegative")
        if not math.isfinite(self.strength) or not math.isfinite(self.scale_beta):
            raise ValueError("Strength and scale beta must be finite")
        if not 0 <= self.ring_weight <= 1 or self.touch_delta < 0:
            raise ValueError("Invalid ring weight or touch tolerance")
        if self.anchor not in ("close", "high", "low", "body_mid", "upper_mid", "lower_mid"):
            raise ValueError("Unknown anchor")
        if self.kernel not in ("gaussian", "causal"):
            raise ValueError("Unknown kernel")
        if self.projection not in ("none", "reflect", "translate", "persist", "scramble", "scale"):
            raise ValueError("Unknown projection")
        if self.initial_estimator not in ("difference", "kalman"):
            raise ValueError("Unknown initial estimator")
        for name in ("body", "upper", "lower"):
            lo, hi = getattr(self.rules, name + "_min"), getattr(self.rules, name + "_max")
            if not 0 <= lo <= hi <= 100:
                raise ValueError(f"Invalid {name} percentage bounds")
        if (
            isinstance(self.rules.top_n, bool)
            or not isinstance(self.rules.top_n, int)
            or self.rules.top_n < 0
        ):
            raise ValueError("top_n must be a nonnegative integer")
        if (
            self.rules.direction not in ("any", "bullish", "bearish")
            or not math.isfinite(self.rules.range_min)
            or self.rules.range_min < 0
        ):
            raise ValueError("Invalid selection rule")
        return self

    @classmethod
    def smooth(cls):
        """Shallow, smooth landscape: bounded depth, wide kernels, gentle background bowl."""
        return cls(
            depth=3,
            sigma_x=4,
            sigma_y=2,
            coupling=0.5,
            background_k=0.02,
            acceleration_clip=1,
            tau=2,
        ).validate()

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, obj):
        obj = dict(obj)
        obj["rules"] = Rules(**obj.get("rules", {}))
        return cls(**obj).validate()

    @classmethod
    def load(cls, path):
        return cls.from_dict(yaml.safe_load(Path(path).read_text()) or {})
