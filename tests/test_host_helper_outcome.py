"""A failed privileged helper is reported with its cause."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from ohana_agent.host.chrony import ChronyRestartRequester
from ohana_agent.host.helper_outcome import HelperOutcome


class FakeSystemd:
    """Answer ``systemctl show`` like the helper run on Konoha on 26 September."""

    def __init__(self, runs: list[dict[str, str]], target: dict[str, str]) -> None:
        self.runs = runs
        self.target = target
        self.calls = 0

    def __call__(self, command, **_kwargs):
        unit = command[2]
        if unit == "chrony.service":
            values = self.target
        else:
            values = self.runs[min(self.calls, len(self.runs) - 1)]
            self.calls += 1
        properties = [part.split("=", 1)[1] for part in command[3:]]
        stdout = "\n".join(f"{name}={values.get(name, '')}" for name in properties)
        return SimpleNamespace(stdout=stdout, returncode=0)


def _outcome(tmp_path: Path, systemd: FakeSystemd, **kwargs) -> HelperOutcome:
    systemctl = tmp_path / "systemctl"
    systemctl.write_text("", encoding="utf-8")
    clock = iter(range(1000))
    return HelperOutcome(
        "ohana-chrony-restart.service",
        "chrony.service",
        systemctl_path=systemctl,
        runner=systemd,
        sleep=lambda _seconds: None,
        monotonic=lambda: float(next(clock)),
        **kwargs,
    )


BEFORE = {"ExecMainExitTimestampMonotonic": "100", "ActiveState": "inactive"}


def test_masked_target_is_named_in_the_failure(tmp_path) -> None:
    systemd = FakeSystemd(
        [
            BEFORE,
            {**BEFORE},  # the path unit has not triggered the helper yet
            {
                "ActiveState": "failed",
                "Result": "exit-code",
                "ExecMainStatus": "1",
                "ExecMainExitTimestampMonotonic": "200",
            },
        ],
        {"LoadState": "masked", "UnitFileState": "masked", "ActiveState": "inactive"},
    )
    outcome = _outcome(tmp_path, systemd)

    baseline = outcome.baseline()
    with pytest.raises(RuntimeError, match="chrony.service est masqué") as error:
        outcome.wait(baseline)
    assert "exit-code" in str(error.value)


def test_successful_helper_run_returns(tmp_path) -> None:
    systemd = FakeSystemd(
        [
            BEFORE,
            {
                "ActiveState": "inactive",
                "Result": "success",
                "ExecMainStatus": "0",
                "ExecMainExitTimestampMonotonic": "200",
            },
        ],
        {},
    )
    outcome = _outcome(tmp_path, systemd)

    outcome.wait(outcome.baseline())


def test_helper_still_running_is_left_to_shikamaru(tmp_path) -> None:
    systemd = FakeSystemd([BEFORE, {**BEFORE, "ActiveState": "activating"}], {})
    outcome = _outcome(tmp_path, systemd, wait_seconds=3)

    outcome.wait(outcome.baseline())


def test_without_systemctl_nothing_is_awaited(tmp_path) -> None:
    outcome = HelperOutcome(
        "ohana-chrony-restart.service",
        "chrony.service",
        systemctl_path=tmp_path / "absent",
        runner=lambda *_args, **_kwargs: pytest.fail("systemctl must not run"),
    )

    assert outcome.baseline() is None
    outcome.wait(None)


def test_chrony_repair_fails_with_the_helper_cause(tmp_path) -> None:
    path_unit = tmp_path / "ohana-chrony-restart.path"
    path_unit.write_text("[Path]\n", encoding="utf-8")
    systemd = FakeSystemd(
        [
            BEFORE,
            {
                "ActiveState": "failed",
                "Result": "exit-code",
                "ExecMainStatus": "1",
                "ExecMainExitTimestampMonotonic": "200",
            },
        ],
        {"LoadState": "masked"},
    )
    requester = ChronyRestartRequester(
        request_path=tmp_path / "run" / "chrony-restart.request",
        path_unit=path_unit,
        outcome=_outcome(tmp_path, systemd),
    )

    with pytest.raises(RuntimeError, match="masqué"):
        requester.request_restart()
    assert requester.request_path.is_file()
