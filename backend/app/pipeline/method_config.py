from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import yaml

from apix_index.types import MethodConfig, WeightSet
from app.config.settings import Settings

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def config_dir(settings: Settings | None = None) -> Path:
    if settings and settings.index_config_dir:
        return Path(settings.index_config_dir)
    return DEFAULT_CONFIG_DIR


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"index configuration file is missing: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a mapping")
    return payload


def load_method_config(settings: Settings | None = None, *, omega_preset: str | None = None) -> MethodConfig:
    payload = _load_yaml(config_dir(settings) / "method.yaml")
    preset = omega_preset or payload.get("omega_preset") or "uniform"
    presets = payload.get("omega_presets") or {}
    omega_raw = presets.get(preset) or payload.get("omega")
    omega = None
    if omega_raw:
        omega = {int(key): Decimal(str(value)) for key, value in omega_raw.items()}
    # Chain-linkage onto an earlier published base (see config/method.yaml).
    # Disabled leaves the index on its own base period = 100.
    linkage = payload.get("linkage") or {}
    link_on = bool(linkage.get("enabled"))
    link_factor = Decimal(str(linkage["link_factor"])) if link_on else None
    link_label = linkage.get("label") if link_on else None
    return MethodConfig(
        method_version=str(payload.get("method_version", "1.0.0")),
        apw_windows=tuple(int(item) for item in payload.get("apw_windows", (1, 7, 15, 30, 45))),
        n_min=int(payload.get("n_min", 5)),
        tukey_k=Decimal(str(payload.get("tukey_k", "3.0"))),
        hampel_z=Decimal(str(payload.get("hampel_z", "3.5"))),
        jump_sigma=Decimal(str(payload.get("jump_sigma", "3.0"))),
        dow_window=int(payload.get("dow_window", 7)),
        bootstrap_draws=int(payload.get("bootstrap_draws", 200)),
        bootstrap_seed=int(payload.get("bootstrap_seed", 20260822)),
        ci_level=Decimal(str(payload.get("ci_level", "0.90"))),
        omega=omega,
        omega_preset=str(preset),
        variant=payload.get("variant", "T"),
        basis=payload.get("basis", "book"),
        apply_availability_adjustment=bool(payload.get("apply_availability_adjustment", True)),
        apply_dow_smoothing=bool(payload.get("apply_dow_smoothing", True)),
        base_period=payload.get("base_period"),
        link_factor=link_factor,
        link_label=link_label,
    )


def load_basket(settings: Settings | None = None) -> dict:
    return _load_yaml(config_dir(settings) / "basket.yaml")


def load_weight_set(settings: Settings | None = None) -> tuple[WeightSet, dict]:
    payload = _load_yaml(config_dir(settings) / "weights.yaml")
    weights = WeightSet.from_mapping(
        payload.get("route_weights") or {},
        payload.get("carrier_weights") or {},
        weights_version=str(payload.get("version", "v1")),
        source=str(payload.get("source", "declared")),
    )
    return weights, payload
