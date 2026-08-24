"""Rung 0: the deterministic fare simulator.

THIS IS NOT A COLLECTION SOURCE AND ITS OUTPUT IS NOT A MEASUREMENT.

It exists so the full pipeline -- clean, decompose, index, serve, chart -- runs
end to end with no network, no API key and no terms-of-service exposure, which
is what makes CI meaningful and what makes the demo survive a dead conference
wifi. Every quote it produces is stamped `is_synthetic = 1`, and every chart
drawn from it must be watermarked SYNTHETIC (Part 8: "label synthetic data
SYNTHETIC", "never fabricate").

The generative model is documented rather than tuned to flatter the index. It
reproduces four features of real airfare data that the index engine has to
survive:

  1. A U-SHAPED LEAD-TIME CURVE. Fares fall from tau=45 to a trough around
     tau=21-30, then rise sharply approaching departure. This is what makes
     tau* estimable and is the shape the elasticity module must recover.
  2. A DISCRETE FARE LADDER. Airlines price from RBDs, so the within-cell fare
     distribution is multi-modal, not lognormal-smooth.
  3. DAY-OF-WEEK SEASONALITY in the departure date, which is the confound the
     7-day centred geometric moving average exists to annihilate.
  4. SURGE EPISODES WITH BUCKET CLOSURE. During a surge the cheap fare families
     stop being offered. This is the phenomenon the availability adjustment
     addresses, and without it in the simulator that feature cannot be
     demonstrated or tested.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Sequence

import numpy as np

# The fare ladder. Multipliers on the cell's base level, in ascending order --
# the cheap buckets are the ones that close first during a surge.
FARE_LADDER: List[dict] = [
    {"family": "SAVER",     "rbd": "U", "mult": 1.00, "close_order": 0},
    {"family": "ECOVALUE",  "rbd": "T", "mult": 1.18, "close_order": 1},
    {"family": "FLEXI",     "rbd": "L", "mult": 1.42, "close_order": 2},
    {"family": "COMFORT",   "rbd": "Q", "mult": 1.75, "close_order": 3},
    {"family": "LASTSEAT",  "rbd": "Y", "mult": 2.30, "close_order": 4},
]


@dataclass
class SurgeEpisode:
    """A demand surge: fares rise AND cheap buckets close.

    This is the demo that proves the team understands price measurement rather
    than data plumbing -- a naive matched index reports ZERO inflation through
    one of these, because the only quote still observable never changed price.
    """
    start: date
    end: date
    routes: Sequence[str]
    intensity: float = 0.35       # peak log-uplift on the fare level
    closure: float = 0.6          # peak share of the ladder that closes

    def factor(self, d: date) -> float:
        """Triangular profile: ramps up to the midpoint, then back down."""
        if not (self.start <= d <= self.end):
            return 0.0
        span = (self.end - self.start).days or 1
        pos = (d - self.start).days / span
        return float(1.0 - abs(2.0 * pos - 1.0))


@dataclass
class SyntheticConfig:
    seed: int = 20260822
    apw_windows: Sequence[int] = (1, 7, 15, 30, 45)
    flights_per_cell: int = 6
    noise_sd: float = 0.035            # idiosyncratic log noise per quote
    drift_annual: float = 0.06         # 6% a year underlying fare drift
    tau_trough: float = 26.0           # where the U-shape bottoms out
    # Calibrated so a T+1 fare is about 2.5x the trough and a T+45 fare about
    # 1.03x -- the shape real Indian domestic fares show. Higher curvature
    # generates last-seat fares that trip the plausibility gate, which would
    # be the simulator manufacturing its own outliers.
    tau_curvature: float = 0.085
    dow_amplitude: float = 0.055       # Fri/Sun departures dearer
    fare_per_km: float = 4.1           # anchors the level to something plausible
    surges: List[SurgeEpisode] = field(default_factory=list)


class SyntheticSource:
    """Deterministic given (config.seed, route, carrier, date, tau, flight)."""

    name = "synthetic_replay"
    rung = 0
    type = "simulator"
    legal_basis = ("Not a collection source. Deterministic simulator for offline "
                   "demo and CI. No host is contacted and no terms apply.")

    def __init__(self, config: SyntheticConfig, routes: List[dict], carriers: List[dict]):
        self.config = config
        self.routes = {r["route"]: r for r in routes}
        self.carriers = {c["iata"]: c for c in carriers}

    # -- deterministic per-observation randomness -------------------------
    def _rng(self, *parts) -> np.random.Generator:
        """A generator keyed by the observation identity, so the same quote is
        the same number on every run regardless of iteration order."""
        key = "|".join(str(p) for p in parts).encode("utf-8")
        digest = hashlib.sha256(key).digest()
        return np.random.default_rng(int.from_bytes(digest[:8], "big") ^ self.config.seed)

    # -- the model --------------------------------------------------------
    def _lead_time_factor(self, tau: int) -> float:
        """log-quadratic in ln(tau), minimised at tau_trough.

        This is exactly the functional form the elasticity module fits, so a
        successful recovery of tau* is a real round-trip test of that module
        rather than a coincidence.
        """
        c = self.config
        return float(c.tau_curvature * (np.log(max(tau, 1)) - np.log(c.tau_trough)) ** 2)

    def _dow_factor(self, d: date) -> float:
        # Friday (4) and Sunday (6) departures are the expensive ones.
        weights = {0: -0.2, 1: -0.6, 2: -0.5, 3: 0.2, 4: 1.0, 5: -0.3, 6: 0.8}
        return float(self.config.dow_amplitude * weights[d.weekday()])

    def _base_level(self, route: str, carrier: str) -> float:
        r = self.routes[route]
        c = self.carriers[carrier]
        km = float(r.get("gc_distance_km") or 1000.0)
        # Distance is sublinear in fare: short sectors carry a fixed-cost floor.
        level = 1450.0 + self.config.fare_per_km * (km ** 0.92)
        if c.get("model") == "FSC":
            level *= 1.14
        if r.get("is_rcs"):
            # UDAN/RCS sectors are price-capped and behave completely
            # differently -- that heterogeneity is the point of including them.
            level = min(level, 2500.0) * 0.92
        return float(level)

    def _surge(self, route: str, dep: date):
        up, close = 0.0, 0.0
        for s in self.config.surges:
            if route in s.routes or "*" in s.routes:
                f = s.factor(dep)
                up += s.intensity * f
                close = max(close, s.closure * f)
        return up, close

    # -- generation -------------------------------------------------------
    def collect(self, collected_on: date, routes: Optional[Sequence[str]] = None) -> List[dict]:
        """Produce one collection cycle: every route x carrier x tau x flight x family."""
        cfg = self.config
        target_routes = list(routes) if routes else list(self.routes)
        origin_day = date(2026, 1, 1)
        out: List[dict] = []

        for route in target_routes:
            r = self.routes[route]
            for carrier, c in self.carriers.items():
                base = self._base_level(route, carrier)
                for tau in cfg.apw_windows:
                    dep = collected_on + timedelta(days=int(tau))
                    up, closure = self._surge(route, dep)

                    # How much of the ladder is still on sale. Cheap buckets go
                    # first, which is what censors a naive matched index.
                    n_open = max(1, int(round(len(FARE_LADDER) * (1.0 - closure))))
                    open_families = sorted(FARE_LADDER, key=lambda f: f["close_order"])
                    open_families = open_families[len(FARE_LADDER) - n_open:] if closure > 0 else FARE_LADDER

                    drift = cfg.drift_annual * ((collected_on - origin_day).days / 365.0)
                    common = (np.log(base) + drift + self._lead_time_factor(tau)
                              + self._dow_factor(dep) + up)

                    for f_i in range(cfg.flights_per_cell):
                        flight_number = f"{carrier}-{2000 + hash((route, carrier)) % 300 + f_i}"
                        frng = self._rng("flight", route, carrier, flight_number)
                        # A stable per-flight effect: the 07:10 DEL-BOM is
                        # consistently pricier than the 23:40, every day.
                        flight_effect = float(frng.normal(0.0, 0.05))
                        dep_hour = int(frng.integers(5, 22))

                        for fam in open_families:
                            rng = self._rng(cfg.seed, route, carrier, flight_number,
                                            collected_on.isoformat(), tau, fam["family"])
                            log_p = (common + flight_effect + np.log(fam["mult"])
                                     + float(rng.normal(0.0, cfg.noise_sd)))
                            total = float(np.exp(log_p))
                            out.append({
                                "route": route, "carrier": carrier,
                                "flight_number": flight_number,
                                "departure_date": dep.isoformat(),
                                "departure_time_local": f"{dep_hour:02d}:{int(frng.integers(0,60)):02d}",
                                "arrival_time_local": None,
                                "apw_days": int(tau), "cabin": "economy",
                                "fare_family": fam["family"], "rbd": fam["rbd"], "stops": 0,
                                "currency": "INR",
                                "total_fare": round(total, 2),
                                "seats_remaining_shown": int(rng.integers(1, 9)),
                                "is_sold_out": 0,
                                "is_synthetic": 1,
                                "origin_iata": r["origin_iata"], "dest_iata": r["dest_iata"],
                                "collected_date": collected_on.isoformat(),
                            })

                    # Record the closed buckets explicitly as sold out. They are
                    # a PRICE SIGNAL, not missing data (Part 4, section 8).
                    for fam in FARE_LADDER:
                        if fam not in open_families:
                            out.append({
                                "route": route, "carrier": carrier,
                                "flight_number": f"{carrier}-CLOSED",
                                "departure_date": dep.isoformat(),
                                "departure_time_local": None, "arrival_time_local": None,
                                "apw_days": int(tau), "cabin": "economy",
                                "fare_family": fam["family"], "rbd": fam["rbd"], "stops": 0,
                                "currency": "INR", "total_fare": None,
                                "seats_remaining_shown": 0, "is_sold_out": 1,
                                "is_synthetic": 1,
                                "origin_iata": r["origin_iata"], "dest_iata": r["dest_iata"],
                                "collected_date": collected_on.isoformat(),
                            })
        return out


def default_surges(routes: Sequence[str]) -> List[SurgeEpisode]:
    """Two episodes, so the availability demo has something to show.

    A festival-weekend surge on the leisure sectors and a sharper, shorter
    disruption episode on the metro trunk.
    """
    leisure = [r for r in routes if r.startswith(("DEL-GOI", "DEL-SXR", "BOM-GOI", "DEL-IXL"))]
    trunk = [r for r in routes if r in ("DEL-BOM", "BOM-DEL", "DEL-BLR", "BLR-DEL")]
    return [
        SurgeEpisode(date(2026, 10, 16), date(2026, 11, 2), leisure or ["*"],
                     intensity=0.38, closure=0.62),
        SurgeEpisode(date(2026, 9, 4), date(2026, 9, 11), trunk or ["*"],
                     intensity=0.26, closure=0.48),
    ]
