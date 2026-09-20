"""Pure APIx statistical engine.

This package must not import FastAPI, collectors, SQLAlchemy sessions, or
network code.
"""

from apix_index.availability import availability_ratio, blend, compute_availability_adjustment
from apix_index.coverage import route_coverage_pct
from apix_index.elasticity import elasticity_by_period, log_log_elasticity
from apix_index.engine import compute
from apix_index.frequency import to_frequency
from apix_index.jevons import carli, compute_jevons, dutot, jevons, jevons_se, log_relatives
from apix_index.smoothing import centred_geometric_ma
from apix_index.decimal_math import geometric_mean
from apix_index.types import KAPPA, MethodConfig, WeightSet
from apix_index.young import aggregate_apw, aggregate_carriers, aggregate_routes, compute_young

__all__ = [
    "KAPPA",
    "MethodConfig",
    "WeightSet",
    "aggregate_apw",
    "aggregate_carriers",
    "aggregate_routes",
    "availability_ratio",
    "blend",
    "carli",
    "centred_geometric_ma",
    "compute",
    "compute_availability_adjustment",
    "compute_jevons",
    "compute_young",
    "dutot",
    "elasticity_by_period",
    "geometric_mean",
    "jevons",
    "jevons_se",
    "log_log_elasticity",
    "log_relatives",
    "route_coverage_pct",
    "to_frequency",
]
