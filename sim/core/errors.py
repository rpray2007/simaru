class SimError(Exception):
    """Base error for the simulation runtime."""


class ReplayCacheMiss(SimError):
    """Raised when a replay run cannot find a cached model call."""


class ValidationError(SimError):
    """Raised when model output fails semantic validation."""


class ConfigError(SimError):
    """Raised when configuration cannot be loaded or merged."""
