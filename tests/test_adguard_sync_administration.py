"""Prove validation, secret masking and independent engine activation."""

import json
import subprocess
from copy import deepcopy
from types import SimpleNamespace

import pytest
import yaml

from ohana_agent.host.adguard_sync import AdGuardSyncAdministration


@pytest.fixture
def administration(tmp_path, monkeypatch):
    import os

    if hasattr(os, "chown"):
        import grp

        monkeypatch.setattr(os, "chown", lambda *args: None)
        monkeypatch.setattr(grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=123))
    configuration = tmp_path / "sync.yaml"
    configuration.write_text(
        yaml.safe_dump(
            {
                "origin": {
                    "url": "http://192.168.1.11",
                    "username": "admin",
                    "password": "origin-secret",
                },
                "replica": {
                    "url": "http://192.168.1.12",
                    "username": "admin",
                    "password": "replica-secret",
                },
                "features": {"dhcp": {"serverConfig": False, "staticLeases": False}},
                "cron": "",
                "api": {"port": 0},
            }
        ),
        encoding="utf-8",
    )
    binary, helper = tmp_path / "binary", tmp_path / "helper"
    binary.touch()
    helper.touch()
    commands = []
    system = {"active": False, "enabled": False}

    def runner(command, **kwargs):
        commands.append(tuple(command))
        assert kwargs["timeout"] <= 90
        if command[1] == "is-active":
            return subprocess.CompletedProcess(
                command,
                0 if system["active"] else 3,
                "active" if system["active"] else "inactive",
                "",
            )
        if command[1] == "is-enabled":
            return subprocess.CompletedProcess(
                command,
                0 if system["enabled"] else 1,
                "enabled" if system["enabled"] else "disabled",
                "",
            )
        return subprocess.CompletedProcess(command, 0, "", "")

    probe = SimpleNamespace(validate_access=lambda settings: {"dns_healthy": True})
    repository = AdGuardSyncAdministration(
        configuration=configuration,
        state=tmp_path / "state.json",
        binary=binary,
        helper=helper,
        command_runner=runner,
        probe=probe,
    )
    return repository, commands, system


def payload(repository):
    value = repository.read()
    return {
        role: {
            "url": value[role]["url"],
            "username": value[role]["username"],
            "password": "",
        }
        for role in ("origin", "replica")
    }


def test_read_masks_both_passwords_and_embedded_credentials(administration):
    repository, _, _ = administration
    assert "secret" not in json.dumps(repository.read())
    document = yaml.safe_load(repository.configuration.read_text())
    document["origin"]["url"] = "http://user:private-password@192.168.1.11"
    repository.configuration.write_text(yaml.safe_dump(document), encoding="utf-8")
    assert repository.read()["origin"]["url"] == ""
    assert "private-password" not in json.dumps(repository.read())


def test_save_keeps_secrets_and_features_after_read_only_validation(administration):
    repository, commands, _ = administration
    original = yaml.safe_load(repository.configuration.read_text())
    request = payload(repository)
    request["origin"]["username"] = "new-admin"
    validated = []
    repository.probe.validate_access = lambda settings: (
        validated.append(yaml.safe_load(settings.sync_config_path.read_text()))
        or {"dns_healthy": True}
    )
    response = repository.write(request)
    saved = yaml.safe_load(repository.configuration.read_text())
    assert saved["origin"]["password"] == "origin-secret"
    assert saved["replica"]["password"] == "replica-secret"
    assert saved["features"] == original["features"]
    assert validated == [saved]
    assert "secret" not in json.dumps(response)
    assert not any("sudo" in command[0] for command in commands)


def test_invalid_access_never_replaces_saved_configuration(administration):
    repository, _, _ = administration
    before = repository.configuration.read_bytes()

    def fail(_settings):
        raise ValueError("https://private:password@secret-host")

    repository.probe.validate_access = fail
    with pytest.raises(ValueError, match="non validés") as error:
        repository.write(payload(repository))
    assert "secret" not in str(error.value)
    assert repository.configuration.read_bytes() == before
    assert list(repository.configuration.parent.glob(".adguard-sync-*")) == []


def test_save_is_refused_while_the_timer_is_active(administration):
    repository, _, system = administration
    system["active"] = True
    before = repository.configuration.read_bytes()
    with pytest.raises(ValueError, match="Désactiver"):
        repository.write(payload(repository))
    assert repository.configuration.read_bytes() == before


@pytest.mark.parametrize("enabled", [True, False])
def test_activation_uses_only_the_fixed_privileged_command(administration, enabled):
    repository, commands, _ = administration
    repository.set_enabled({"enabled": enabled})
    assert (
        "/usr/bin/sudo",
        "-n",
        str(repository.helper),
        "activate" if enabled else "deactivate",
    ) in commands


@pytest.mark.parametrize("value", [None, 1, "true", [], {}])
def test_activation_requires_an_actual_boolean(administration, value):
    repository, commands, _ = administration
    with pytest.raises(ValueError):
        repository.set_enabled({"enabled": value})
    assert commands == []


def test_privileged_activation_refuses_failed_api_before_systemd(administration):
    repository, commands, _ = administration

    def reject(settings):
        raise ValueError("private API error")

    repository.probe.validate_access = reject
    with pytest.raises(ValueError, match="non validés"):
        repository.privileged_set_enabled(True)
    assert commands == []
    assert not repository.state.exists()


def test_successful_activation_persists_restore_intent(administration):
    repository, commands, _ = administration
    repository.privileged_set_enabled(True)
    assert (
        "/usr/bin/systemctl",
        "enable",
        "--now",
        "adguardhome-sync.timer",
    ) in commands
    assert json.loads(repository.state.read_text()) == {
        "schema_version": 1,
        "enabled": True,
    }
    repository.privileged_set_enabled(False)
    assert ("/usr/bin/systemctl", "stop", "adguardhome-sync.service") in commands
    assert json.loads(repository.state.read_text())["enabled"] is False


def test_unknown_fields_do_not_reach_the_sync_configuration(administration):
    repository, _, _ = administration
    request = deepcopy(payload(repository))
    request["replica"]["insecureSkipVerify"] = True
    with pytest.raises(ValueError):
        repository.write(request)


def test_activation_rolls_back_when_restore_intent_cannot_be_saved(
    administration, monkeypatch
):
    repository, commands, _ = administration
    repository.state.write_text('{"schema_version":1,"enabled":false}')
    before = repository.state.read_bytes()
    replace = __import__("os").replace

    def reject_state(source, destination):
        if destination == repository.state:
            raise OSError("storage failure")
        return replace(source, destination)

    monkeypatch.setattr("ohana_agent.host.adguard_sync.os.replace", reject_state)
    with pytest.raises(OSError):
        repository.privileged_set_enabled(True)
    assert repository.state.read_bytes() == before
    assert ("/usr/bin/systemctl", "disable", "adguardhome-sync.timer") in commands
    assert ("/usr/bin/systemctl", "stop", "adguardhome-sync.timer") in commands


@pytest.mark.skipif(__import__("os").name != "posix", reason="POSIX advisory locks")
def test_busy_capability_lock_has_a_bounded_wait(administration, monkeypatch):
    import fcntl

    repository, commands, _ = administration
    moments = iter([0, 2, 6])
    monkeypatch.setattr(
        "ohana_agent.host.adguard_sync.monotonic", lambda: next(moments)
    )
    monkeypatch.setattr("ohana_agent.host.adguard_sync.sleep", lambda seconds: None)

    def busy(*args):
        raise BlockingIOError()

    monkeypatch.setattr(fcntl, "flock", busy)
    with pytest.raises(ValueError, match="déjà en cours"):
        with repository._file_lock():
            pytest.fail("The locked operation must not start")
    assert commands == []
