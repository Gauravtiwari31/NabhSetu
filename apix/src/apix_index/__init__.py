"""apix_index -- the APIx index engine. Pure, typed, and I/O-free by design."""
from .aggregate import aggregate_apw, aggregate_carriers, aggregate_routes, to_frequency
from .availability import availability_ratio, blend
from .elementary import carli, dutot, jevons, jevons_se, log_relatives
from .engine import compute
from .smoothing import centred_geometric_ma, geometric_mean
from .types import CELL, FLIGHT, KAPPA, IndexResult, MethodConfig, WeightSet
from .uncertainty import delta_method_se, flight_block_bootstrap

__version__ = "1.0.0"
__all__ = [
    "compute", "MethodConfig", "WeightSet", "IndexResult",
    "jevons", "dutot", "carli", "jevons_se", "log_relatives",
    "availability_ratio", "blend", "centred_geometric_ma", "geometric_mean",
    "aggregate_carriers", "aggregate_routes", "aggregate_apw", "to_frequency",
    "flight_block_bootstrap", "delta_method_se",
    "KAPPA", "CELL", "FLIGHT",
]
