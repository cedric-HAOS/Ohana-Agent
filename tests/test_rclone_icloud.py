from __future__ import annotations

import json
import os
from subprocess import CompletedProcess

from plugins.backup.rclone_icloud import RcloneICloudConfigurator


def test_icloud_configuration_requires_and_completes_two_factor(tmp_path) -> None:
    binary = tmp_path / "rclone"
    binary.write_text("binary", encoding="utf-8")
    config = tmp_path / "rclone.conf"
    commands: list[list[str]] = []

    def runner(command, **kwargs):
        del kwargs
        commands.append(command)
        if command[1] == "listremotes":
            return CompletedProcess(command, 0, stdout="icloud:\n", stderr="")
        if "--continue" not in command:
            return CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "State": "icloud-2fa-state",
                        "Option": {"Name": "config_2fa"},
                    }
                ),
                stderr="",
            )
        config.write_text("[icloud]\ntype = iclouddrive\n", encoding="utf-8")
        return CompletedProcess(command, 0, stdout='{"State":""}', stderr="")

    configurator = RcloneICloudConfigurator(
        binary=str(binary),
        config_path=str(config),
        remote_name="icloud",
        runner=runner,
    )

    started = configurator.connect(
        apple_id="user@example.com",
        password="apple-password",
    )
    assert started["requires_two_factor"] is True
    assert started["connected"] is False

    completed = configurator.connect(two_factor_code="123456")
    assert completed["connected"] is True
    assert completed["configured"] is True
    if os.name != "nt":
        assert config.stat().st_mode & 0o777 == 0o600
    continue_command = next(command for command in commands if "--continue" in command)
    assert continue_command[continue_command.index("--result") + 1] == "123456"
    configuration_commands = [
        command for command in commands if command[1:3] == ["config", "create"]
    ]
    assert configuration_commands
    assert all("--obscure" in command for command in configuration_commands)


def test_icloud_status_reports_missing_binary(tmp_path) -> None:
    configurator = RcloneICloudConfigurator(
        binary=str(tmp_path / "missing-rclone"),
        config_path=str(tmp_path / "rclone.conf"),
        remote_name="icloud",
    )

    assert configurator.status() == {
        "binary_available": False,
        "configured": False,
        "requires_two_factor": False,
        "remote_name": "icloud",
    }
