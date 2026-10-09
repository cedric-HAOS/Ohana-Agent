from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from ohana_agent.configuration.administration import DHCPAdministrationConfig
from ohana_agent.host import adguard_reservations
from ohana_agent.host.adguard_reservations import (
    AdGuardAPI,
    load_config,
    read_reserved_names,
    read_state,
    reconcile,
    write_state,
)
from ohana_agent.host.dhcp import DEFAULT_SETTINGS, DnsmasqDHCPRepository


class FakeAdGuard:
    def __init__(self, entries=()):
        self.rules = set(entries)
        self.changes = []
        self.fail_after_change = False

    def entries(self):
        return self.rules.copy()

    def change(self, action, entry):
        self.changes.append((action, entry))
        if action == "add":
            self.rules.add(entry)
        else:
            self.rules.discard(entry)
        if self.fail_after_change:
            self.fail_after_change = False
            raise httpx.ReadTimeout("ambiguous response")


@pytest.fixture
def dhcp(tmp_path):
    updates = {
        name: tmp_path / Path(field.default).name
        for name, field in DHCPAdministrationConfig.model_fields.items()
        if name.endswith("_path") and isinstance(field.default, Path)
    }
    config = DHCPAdministrationConfig(**updates)
    config.main_config_path.write_text(
        DnsmasqDHCPRepository._render_main(
            DEFAULT_SETTINGS,
            "infra-01",
        ),
        encoding="utf-8",
    )
    for name in updates:
        if "reservations" in name:
            updates[name].write_text("# empty category\n", encoding="utf-8")
    config.server_reservations_path.write_text(
        "dhcp-host=AA:BB:CC:DD:EE:02,192.168.1.20,ha-01\n",
        encoding="utf-8",
    )
    # Deliberately invalid: reading the dynamic lease database would fail.
    config.leases_path.write_text("dynamic-client must never be read", encoding="utf-8")
    return config


def test_reservations_only_without_active_leases(dhcp):
    assert read_reserved_names(dhcp) == {("ha-01.ohana.lan", "192.168.1.20")}


def test_fqdn_is_not_suffixed_twice(dhcp):
    dhcp.server_reservations_path.write_text(
        "dhcp-host=AA:BB:CC:DD:EE:02,192.168.1.20,ha-01.ohana.lan\n",
    )
    assert read_reserved_names(dhcp) == {("ha-01.ohana.lan", "192.168.1.20")}


def test_missing_category_cannot_be_interpreted_as_deleted_reservations(dhcp):
    dhcp.critical_reservations_path.unlink()
    with pytest.raises(ValueError, match="Missing DHCP"):
        read_reserved_names(dhcp)


@pytest.mark.parametrize("hostname", ["ha-01.other.lan", "a-", "a" * 64])
def test_invalid_names_are_rejected(dhcp, hostname):
    dhcp.server_reservations_path.write_text(
        f"dhcp-host=AA:BB:CC:DD:EE:02,192.168.1.20,{hostname}\n",
    )
    with pytest.raises(ValueError):
        read_reserved_names(dhcp)


def test_create_change_delete_and_preserve_manual_rules(tmp_path):
    state = tmp_path / "state.json"
    manual = ("manual.ohana.lan", "192.168.1.80")
    outside = ("example.org", "192.168.1.90")
    old = ("ha-01.ohana.lan", "192.168.1.20")
    new = ("ha-01.ohana.lan", "192.168.1.21")
    api = FakeAdGuard({manual, outside})
    assert reconcile({old}, api, state) == (1, 0)
    assert reconcile({new}, api, state) == (1, 1)
    assert reconcile(set(), api, state) == (0, 1)
    assert api.rules == {manual, outside}
    assert read_state(state) == set()


def test_manual_collision_aborts_before_all_mutations(tmp_path):
    state = tmp_path / "state.json"
    api = FakeAdGuard({("ha-01.ohana.lan", "192.168.1.99")})
    with pytest.raises(ValueError, match="Conflicting manual"):
        reconcile({("ha-01.ohana.lan", "192.168.1.20")}, api, state)
    assert not api.changes
    assert not state.exists()


def test_dry_run_does_not_write_state_or_remote_rules(tmp_path):
    state = tmp_path / "state.json"
    api = FakeAdGuard()
    assert reconcile(
        {("ha-01.ohana.lan", "192.168.1.20")}, api, state, dry_run=True
    ) == (1, 0)
    assert not state.exists()
    assert not api.changes


def test_unchanged_cycle_does_not_rewrite_state(tmp_path):
    state = tmp_path / "state.json"
    entry = ("ha-01.ohana.lan", "192.168.1.20")
    write_state(state, {entry})
    before = state.stat().st_mtime_ns
    api = FakeAdGuard({entry})
    assert reconcile({entry}, api, state) == (0, 0)
    assert state.stat().st_mtime_ns == before
    assert not api.changes


def test_retry_after_ambiguous_add_can_remove_the_pending_rule(tmp_path):
    state = tmp_path / "state.json"
    entry = ("ha-01.ohana.lan", "192.168.1.20")
    api = FakeAdGuard()
    api.fail_after_change = True
    with pytest.raises(httpx.ReadTimeout):
        reconcile({entry}, api, state)
    assert read_state(state) == {entry}
    assert reconcile(set(), api, state) == (0, 1)
    assert not api.rules


def test_retry_after_ambiguous_delete_is_idempotent(tmp_path):
    state = tmp_path / "state.json"
    entry = ("ha-01.ohana.lan", "192.168.1.20")
    write_state(state, {entry})
    api = FakeAdGuard({entry})
    api.fail_after_change = True
    with pytest.raises(httpx.ReadTimeout):
        reconcile(set(), api, state)
    assert reconcile(set(), api, state) == (0, 0)
    assert read_state(state) == set()


def test_corrupt_or_outside_domain_state_never_removes_rules(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "rewrites": [{"domain": "example.org", "answer": "192.168.1.20"}],
            }
        )
    )
    api = FakeAdGuard({("example.org", "192.168.1.20")})
    with pytest.raises(ValueError, match="outside"):
        reconcile(set(), api, state)
    assert not api.changes


def test_api_matches_official_endpoints_and_does_not_follow_redirects():
    calls = []

    def handle(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(
                200, json=[{"domain": "ha-01.ohana.lan", "answer": "192.168.1.20"}]
            )
        return httpx.Response(200)

    api = AdGuardAPI(
        {"url": "http://192.168.1.11", "username": "admin", "password": "test"}
    )
    api.client.close()
    api.client = httpx.Client(transport=httpx.MockTransport(handle))
    try:
        assert api.entries() == {("ha-01.ohana.lan", "192.168.1.20")}
        api.change("add", ("ha-01.ohana.lan", "192.168.1.20"))
        assert str(calls[0].url) == "http://192.168.1.11/control/rewrite/list"
        assert str(calls[1].url) == "http://192.168.1.11/control/rewrite/add"
        assert json.loads(calls[1].content) == {
            "domain": "ha-01.ohana.lan",
            "answer": "192.168.1.20",
        }
    finally:
        api.close()


@pytest.mark.parametrize("dhcp_enabled", [True, None])
def test_dhcp_replication_must_be_explicitly_disabled(tmp_path, dhcp_enabled):
    config = tmp_path / "sync.yaml"
    config.write_text(
        json.dumps(
            {
                "origin": {},
                "replica": {},
                "features": {
                    "dns": {"rewrites": True},
                    "dhcp": {"serverConfig": dhcp_enabled, "staticLeases": False},
                },
            }
        )
    )
    with pytest.raises(ValueError, match="DHCP replication disabled"):
        load_config(config)


@pytest.mark.parametrize("replica_matches", [True, False])
def test_cli_verifies_replica_even_when_native_sync_reports_success(
    tmp_path, monkeypatch, capsys, replica_matches
):
    config = tmp_path / "sync.yaml"
    config.write_text(
        json.dumps(
            {
                "origin": {"url": "http://192.168.1.11", "password": "secret"},
                "replica": {"url": "http://192.168.1.12", "password": "secret"},
                "features": {
                    "dns": {"rewrites": True},
                    "dhcp": {"serverConfig": False, "staticLeases": False},
                },
            }
        )
    )
    rule = ("ha-01.ohana.lan", "192.168.1.20")
    origin = FakeAdGuard({rule})
    replica = FakeAdGuard({rule} if replica_matches else set())
    clients = iter([origin, replica])
    for client in (origin, replica):
        client.close = lambda: None
    monkeypatch.setattr(adguard_reservations, "AdGuardAPI", lambda _: next(clients))
    monkeypatch.setattr(
        "sys.argv", ["sync", "--config", str(config), "--verify-replica"]
    )
    assert adguard_reservations.main() == (0 if replica_matches else 1)
    output = capsys.readouterr()
    assert "secret" not in output.out + output.err
