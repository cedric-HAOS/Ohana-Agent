#!/usr/bin/env bash

set -Eeuo pipefail

readonly SERVICE_NAME="ohana-agent"
readonly SERVICE_USER="ohana-agent"
readonly SERVICE_GROUP="ohana-agent"

readonly INSTALL_ROOT="/opt/ohana-agent"
readonly VENV_PATH="${INSTALL_ROOT}/venv"
readonly CONFIG_ROOT="/etc/ohana-agent"
readonly SYSTEMD_UNIT="/etc/systemd/system/${SERVICE_NAME}.service"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
readonly PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

PYTHON_BIN="${PYTHON_BIN:-python3.13}"
PACKAGE_SOURCE="${1:-${PROJECT_ROOT}}"

log() {
    printf '[ohana-agent] %s\n' "$*"
}

fail() {
    printf '[ohana-agent] ERROR: %s\n' "$*" >&2
    exit 1
}

require_root() {
    [[ "${EUID}" -eq 0 ]] \
        || fail "This script must be run as root."
}

require_command() {
    command -v "$1" >/dev/null 2>&1 \
        || fail "Required command not found: $1"
}

validate_environment() {
    id "${SERVICE_USER}" >/dev/null 2>&1 \
        || fail "System user not found: ${SERVICE_USER}"

    getent group "${SERVICE_GROUP}" >/dev/null \
        || fail "System group not found: ${SERVICE_GROUP}"

    [[ -d "${CONFIG_ROOT}" ]] \
        || fail "Configuration directory not found: ${CONFIG_ROOT}"

    [[ -f "${CONFIG_ROOT}/shikamaru.yaml" ]] \
        || fail "Configuration file not found: ${CONFIG_ROOT}/shikamaru.yaml"

    [[ -f "${CONFIG_ROOT}/infrastructure.yaml" ]] \
        || fail \
            "Configuration file not found: " \
            "${CONFIG_ROOT}/infrastructure.yaml"

    [[ -f "${CONFIG_ROOT}/plugins/dhcp.yaml" ]] \
        || fail \
            "Configuration file not found: " \
            "${CONFIG_ROOT}/plugins/dhcp.yaml"

    [[ -f "${CONFIG_ROOT}/plugins/dns.yaml" ]] \
        || fail \
            "Configuration file not found: " \
            "${CONFIG_ROOT}/plugins/dns.yaml"

    [[ -f "${CONFIG_ROOT}/plugins/ntp.yaml" ]] \
        || fail \
            "Configuration file not found: " \
            "${CONFIG_ROOT}/plugins/ntp.yaml"

    [[ -f "${CONFIG_ROOT}/plugins/mqtt.yaml" ]] \
        || fail \
            "Configuration file not found: " \
            "${CONFIG_ROOT}/plugins/mqtt.yaml"

    [[ -f "${CONFIG_ROOT}/plugins/network.yaml" ]] \
        || fail \
            "Configuration file not found: " \
            "${CONFIG_ROOT}/plugins/network.yaml"

    [[ -f "${CONFIG_ROOT}/plugins/zwave.yaml" ]] \
        || fail \
            "Configuration file not found: " \
            "${CONFIG_ROOT}/plugins/zwave.yaml"

    [[ -f "${CONFIG_ROOT}/plugins/wireguard.yaml" ]] \
        || fail \
            "Configuration file not found: " \
            "${CONFIG_ROOT}/plugins/wireguard.yaml"

    [[ -f "${CONFIG_ROOT}/plugins/shelly-telemetry.yaml" ]] \
        || fail \
            "Configuration file not found: " \
            "${CONFIG_ROOT}/plugins/shelly-telemetry.yaml"

    [[ -e "${PACKAGE_SOURCE}" ]] \
        || fail "Package source not found: ${PACKAGE_SOURCE}"

    [[ ! -e "${VENV_PATH}" ]] \
        || fail \
            "${VENV_PATH} already exists. " \
            "Use deployment/update.sh."

    [[ -f \
        "${PROJECT_ROOT}/deployment/systemd/${SERVICE_NAME}.service" ]] \
        || fail "Reference systemd unit not found."
}

install_application() {
    log "Creating Python environment in ${VENV_PATH}."

    install \
        -d \
        -o root \
        -g root \
        -m 0755 \
        "${INSTALL_ROOT}"

    "${PYTHON_BIN}" -m venv "${VENV_PATH}"

    "${VENV_PATH}/bin/python" \
        -m pip install \
        --upgrade \
        pip

    "${VENV_PATH}/bin/python" \
        -m pip install \
        "${PACKAGE_SOURCE}"

    "${VENV_PATH}/bin/ohana-agent" --version
}

install_service() {
    local source_unit

    source_unit="${PROJECT_ROOT}/deployment/systemd/${SERVICE_NAME}.service"

    install \
        -o root \
        -g root \
        -m 0644 \
        "${source_unit}" \
        "${SYSTEMD_UNIT}"

    systemctl daemon-reload
    systemctl enable "${SERVICE_NAME}.service"

    log "Installed systemd unit: ${SYSTEMD_UNIT}"
}

main() {
    require_root

    require_command "${PYTHON_BIN}"
    require_command getent
    require_command id
    require_command install
    require_command systemctl

    validate_environment
    install_application
    install_service

    log "Installation completed."
    log "The service has been enabled but not started."
    log "Start it with: systemctl start ${SERVICE_NAME}"
}

main "$@"
