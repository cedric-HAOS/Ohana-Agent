from ohana_agent.observation import ObserverResult
from ohana_agent.observation.checks import FakeCheck


def test_fake_check_returns_success_by_default() -> None:
    check = FakeCheck()

    result = check.execute()

    assert result.success is True


def test_fake_check_returns_zero_latency_by_default() -> None:
    check = FakeCheck()

    result = check.execute()

    assert result.latency == 0.0


def test_fake_check_returns_configured_result() -> None:
    expected = ObserverResult(success=False, latency=42.0)

    check = FakeCheck(result=expected)

    assert check.execute() is expected


def test_fake_check_can_return_failure() -> None:
    check = FakeCheck(
        result=ObserverResult(
            success=False,
            latency=12.0,
            message="fake failure",
        )
    )

    result = check.execute()

    assert result.failed is True
    assert result.message == "fake failure"


def test_fake_check_has_name() -> None:
    check = FakeCheck()

    assert check.name == "fake"


def test_fake_check_has_description() -> None:
    check = FakeCheck()

    assert check.description == "Fake observation check"
