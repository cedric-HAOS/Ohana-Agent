from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from monitoring import MonitoringScheduleRegistry


def configuration_with_schedule(schedule: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        topology=SimpleNamespace(
            devices=[
                SimpleNamespace(
                    node="sun-01",
                    metadata={"monitoring_schedule": schedule},
                )
            ]
        )
    )


def test_monitoring_schedule_suspends_outside_period() -> None:
    registry = MonitoringScheduleRegistry()
    registry.replace_from_infrastructure(
        configuration_with_schedule(
            {
                "timezone": "Europe/Paris",
                "periods": [
                    {
                        "days": ["thursday"],
                        "start": "07:00",
                        "end": "22:00",
                    }
                ],
                "startup_grace_seconds": 300,
            }
        )
    )

    before = registry.decision(
        "sun-01",
        datetime(2026, 7, 30, 4, 0, tzinfo=UTC),  # 06:00 Paris
    )
    during_grace = registry.decision(
        "sun-01",
        datetime(2026, 7, 30, 5, 2, tzinfo=UTC),  # 07:02 Paris
    )
    active = registry.decision(
        "sun-01",
        datetime(2026, 7, 30, 5, 6, tzinfo=UTC),  # 07:06 Paris
    )

    assert before.active is False
    assert during_grace.active is False
    assert during_grace.grace_until is not None
    assert active.active is True


def test_monitoring_schedule_rejects_unknown_day() -> None:
    with pytest.raises(ValueError, match="Unknown monitoring period day"):
        MonitoringScheduleRegistry.validate_payload(
            {
                "periods": [{"days": ["holiday"], "start": "07:00", "end": "22:00"}],
            }
        )
