"""Capability exceptions."""


class CapabilityError(Exception):
    """Base exception for capability errors."""


class CapabilityAlreadyRegisteredError(CapabilityError):
    """Raised when a capability is already registered."""


class CapabilityNotFoundError(CapabilityError):
    """Raised when a capability cannot be found."""


class CapabilityDependencyError(CapabilityError):
    """Raised when capability dependencies are invalid."""


class CapabilityDependencyCycleError(CapabilityDependencyError):
    """Raised when a dependency cycle is detected."""
