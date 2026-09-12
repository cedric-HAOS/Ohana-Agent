"""Capability manager."""

from __future__ import annotations

from collections import deque

from ohana_agent.core.capability.capability import Capability
from ohana_agent.core.capability.capability_state import CapabilityState
from ohana_agent.core.capability.exceptions import (
    CapabilityAlreadyRegisteredError,
    CapabilityDependencyCycleError,
    CapabilityDependencyError,
    CapabilityNotFoundError,
)


class CapabilityManager:
    """Register, lookup and orchestrate capabilities."""

    def __init__(self) -> None:
        """Initialize the capability manager."""
        self._capabilities: dict[str, Capability] = {}

    def register(self, capability: Capability) -> None:
        """Register a capability."""
        if capability.capability_id in self._capabilities:
            raise CapabilityAlreadyRegisteredError(
                f"Capability already registered: {capability.capability_id}"
            )

        self._capabilities[capability.capability_id] = capability
        capability.transition_to(CapabilityState.REGISTERED)

    def unregister(self, capability_id: str) -> None:
        """Unregister a capability."""
        if capability_id not in self._capabilities:
            raise CapabilityNotFoundError(f"Capability not found: {capability_id}")

        del self._capabilities[capability_id]

    def get(self, capability_id: str) -> Capability:
        """Return a capability by id."""
        try:
            return self._capabilities[capability_id]
        except KeyError as exc:
            raise CapabilityNotFoundError(
                f"Capability not found: {capability_id}"
            ) from exc

    def exists(self, capability_id: str) -> bool:
        """Return whether a capability exists."""
        return capability_id in self._capabilities

    def list(self) -> list[Capability]:
        """Return all registered capabilities."""
        return list(self._capabilities.values())

    def list_running(self) -> list[Capability]:
        """Return running capabilities."""
        return [
            capability
            for capability in self._capabilities.values()
            if capability.state == CapabilityState.RUNNING
        ]

    def list_in_error(self) -> list[Capability]:
        """Return capabilities in error."""
        return [
            capability
            for capability in self._capabilities.values()
            if capability.state == CapabilityState.ERROR
        ]

    def initialize(self, capability_id: str) -> None:
        """Initialize a capability."""
        capability = self.get(capability_id)
        self._ensure_required_dependencies_exist(capability)
        capability.initialize()

    def start(self, capability_id: str) -> None:
        """Start a capability."""
        capability = self.get(capability_id)
        self._ensure_required_dependencies_running(capability)
        capability.start()

    def stop(self, capability_id: str) -> None:
        """Stop a capability."""
        capability = self.get(capability_id)
        capability.stop()

    def restart(self, capability_id: str) -> None:
        """Restart a capability."""
        self.stop(capability_id)
        self.start(capability_id)

    def dependency_order(self) -> list[str]:
        """Return capability ids sorted by dependency order."""
        self._ensure_all_required_dependencies_exist()

        graph: dict[str, list[str]] = {
            capability_id: [] for capability_id in self._capabilities
        }
        indegree: dict[str, int] = {
            capability_id: 0 for capability_id in self._capabilities
        }

        for capability in self._capabilities.values():
            for dependency_id in capability.dependencies:
                graph[dependency_id].append(capability.capability_id)
                indegree[capability.capability_id] += 1

        queue = deque(
            capability_id for capability_id, degree in indegree.items() if degree == 0
        )

        ordered: list[str] = []

        while queue:
            capability_id = queue.popleft()
            ordered.append(capability_id)

            for dependent_id in graph[capability_id]:
                indegree[dependent_id] -= 1
                if indegree[dependent_id] == 0:
                    queue.append(dependent_id)

        if len(ordered) != len(self._capabilities):
            raise CapabilityDependencyCycleError("Capability dependency cycle detected")

        return ordered

    def reverse_dependency_order(self) -> list[str]:
        """Return capability ids sorted by reverse dependency order."""
        return list(reversed(self.dependency_order()))

    def _ensure_required_dependencies_exist(self, capability: Capability) -> None:
        for dependency_id in capability.dependencies:
            if dependency_id not in self._capabilities:
                raise CapabilityDependencyError(
                    f"Missing dependency '{dependency_id}' "
                    f"for capability '{capability.capability_id}'"
                )

    def _ensure_all_required_dependencies_exist(self) -> None:
        for capability in self._capabilities.values():
            self._ensure_required_dependencies_exist(capability)

    def _ensure_required_dependencies_running(self, capability: Capability) -> None:
        self._ensure_required_dependencies_exist(capability)

        for dependency_id in capability.dependencies:
            dependency = self.get(dependency_id)
            if dependency.state != CapabilityState.RUNNING:
                raise CapabilityDependencyError(
                    f"Dependency '{dependency_id}' is not running "
                    f"for capability '{capability.capability_id}'"
                )
