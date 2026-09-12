from abc import ABC, abstractmethod

from ohana_agent.observation.observer_result import ObserverResult


class BaseCheck(ABC):
    """Base class for observer checks."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the check name."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Return the check description."""

    @abstractmethod
    def execute(self) -> ObserverResult:
        """Execute the check and return an observer result."""
