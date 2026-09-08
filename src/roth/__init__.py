"""Stable matching with capacities, with no runtime dependencies in the core."""

from .matching import deferred_acceptance, verify_matching

__version__ = "0.3.0"
__all__ = ["deferred_acceptance", "verify_matching"]
