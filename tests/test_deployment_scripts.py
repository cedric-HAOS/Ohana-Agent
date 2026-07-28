"""Tests for the reference Linux deployment scripts."""

from pathlib import Path

INSTALL_SCRIPT = Path("deployment/install.sh")
UPDATE_SCRIPT = Path("deployment/update.sh")


def read_script(path: Path) -> str:
    """Read a deployment script."""
    return path.read_text(encoding="utf-8")


def test_linux_deployment_scripts_exist() -> None:
    """Provide the reference installation and update scripts."""
    assert INSTALL_SCRIPT.is_file()
    assert UPDATE_SCRIPT.is_file()


def test_deployment_scripts_use_strict_bash_mode() -> None:
    """Stop deployment scripts on unexpected command failures."""
    for path in (INSTALL_SCRIPT, UPDATE_SCRIPT):
        script = read_script(path)

        assert script.startswith("#!/usr/bin/env bash\n")
        assert "set -Eeuo pipefail" in script


def test_install_script_uses_reference_linux_paths() -> None:
    """Install the application according to the Linux contract."""
    script = read_script(INSTALL_SCRIPT)

    assert 'INSTALL_ROOT="/opt/ohana-agent"' in script
    assert 'VENV_PATH="${INSTALL_ROOT}/venv"' in script
    assert 'CONFIG_ROOT="/etc/ohana-agent"' in script
    assert 'SYSTEMD_UNIT="/etc/systemd/system/${SERVICE_NAME}.service"' in script


def test_install_script_requires_prepared_system_resources() -> None:
    """Leave system preparation to Ohana-Installer."""
    script = read_script(INSTALL_SCRIPT)

    assert 'id "${SERVICE_USER}"' in script
    assert 'getent group "${SERVICE_GROUP}"' in script
    assert '[[ -d "${CONFIG_ROOT}" ]]' in script

    assert "useradd" not in script
    assert "groupadd" not in script


def test_install_script_does_not_manage_configuration() -> None:
    """Require configuration without copying or replacing it."""
    script = read_script(INSTALL_SCRIPT)

    assert '"${CONFIG_ROOT}/shikamaru.yaml"' in script
    assert '"${CONFIG_ROOT}/infrastructure.yaml"' in script
    assert '"${CONFIG_ROOT}/plugins/dhcp.yaml"' in script
    assert '"${CONFIG_ROOT}/plugins/dns.yaml"' in script
    assert '"${CONFIG_ROOT}/plugins/ntp.yaml"' in script
    assert '"${CONFIG_ROOT}/plugins/mqtt.yaml"' in script
    assert '"${CONFIG_ROOT}/plugins/network.yaml"' in script
    assert '"${CONFIG_ROOT}/plugins/zwave.yaml"' in script
    assert '"${CONFIG_ROOT}/plugins/wireguard.yaml"' in script
    assert '"${CONFIG_ROOT}/plugins/shelly-telemetry.yaml"' in script

    assert "shikamaru.example.yaml" not in script
    assert "infrastructure.example.yaml" not in script
    assert "dhcp.example.yaml" not in script
    assert "dns.example.yaml" not in script
    assert "ntp.example.yaml" not in script
    assert "mqtt.example.yaml" not in script
    assert "network.example.yaml" not in script
    assert "zwave.example.yaml" not in script
    assert "wireguard.example.yaml" not in script
    assert "shelly-telemetry.example.yaml" not in script


def test_install_script_enables_without_starting_service() -> None:
    """Allow configuration review before the first service start."""
    script = read_script(INSTALL_SCRIPT)

    assert 'systemctl enable "${SERVICE_NAME}.service"' in script
    assert 'systemctl start "${SERVICE_NAME}.service"' not in script


def test_update_script_updates_package_and_systemd_unit() -> None:
    """Update the installed package and reference service unit."""
    script = read_script(UPDATE_SCRIPT)

    assert '"${VENV_PATH}/bin/python"' in script
    assert "-m pip install" in script
    assert "--upgrade" in script
    assert '"${PACKAGE_SOURCE}"' in script
    assert "systemctl daemon-reload" in script


def test_update_script_preserves_configuration_and_service_state() -> None:
    """Leave configuration untouched and preserve stopped services."""
    script = read_script(UPDATE_SCRIPT)

    assert "/etc/ohana-agent" not in script
    assert "shikamaru.yaml" not in script
    assert "infrastructure.yaml" not in script
    assert "dhcp.yaml" not in script
    assert "dns.yaml" not in script
    assert "ntp.yaml" not in script
    assert "mqtt.yaml" not in script
    assert "network.yaml" not in script
    assert "zwave.yaml" not in script
    assert "wireguard.yaml" not in script
    assert "shelly-telemetry.yaml" not in script

    assert "systemctl is-active --quiet" in script
    assert "SERVICE_WAS_ACTIVE=false" in script
    assert 'if [[ "${SERVICE_WAS_ACTIVE}" == true ]]' in script
