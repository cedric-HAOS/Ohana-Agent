import pytest

from ohana_agent.observation.checks import BaseCheck
from ohana_agent.observation.observer_result import ObserverResult


def test_base_check_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        BaseCheck()


def test_base_check_requires_name() -> None:
    class InvalidCheck(BaseCheck):
        @property
        def description(self) -> str:
            return "invalid"

        def execute(self) -> ObserverResult:
            return ObserverResult(success=True, latency=1.0)

    with pytest.raises(TypeError):
        InvalidCheck()


def test_base_check_requires_description() -> None:
    class InvalidCheck(BaseCheck):
        @property
        def name(self) -> str:
            return "invalid"

        def execute(self) -> ObserverResult:
            return ObserverResult(success=True, latency=1.0)

    with pytest.raises(TypeError):
        InvalidCheck()


def test_base_check_requires_execute() -> None:
    class InvalidCheck(BaseCheck):
        @property
        def name(self) -> str:
            return "invalid"

        @property
        def description(self) -> str:
            return "Invalid check"

    with pytest.raises(TypeError):
        InvalidCheck()


def test_base_check_accepts_complete_implementation() -> None:
    class ValidCheck(BaseCheck):
        @property
        def name(self) -> str:
            return "valid"

        @property
        def description(self) -> str:
            return "Valid check"

        def execute(self) -> ObserverResult:
            return ObserverResult(success=True, latency=1.0)

    check = ValidCheck()

    assert check.name == "valid"
    assert check.description == "Valid check"
    assert check.execute().success is True
