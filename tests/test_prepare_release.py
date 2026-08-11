"""Tests for the release preparation helpers."""

from __future__ import annotations

from pathlib import Path

from scripts import prepare_release


def test_configuration_assets_match_deployable_examples() -> None:
    assert {path.as_posix() for path in prepare_release.CONFIGURATION_ASSETS} == {
        "config/infrastructure.example.yaml",
        "config/shikamaru.example.yaml",
        "config/plugins/backup.example.yaml",
        "config/plugins/dhcp.example.yaml",
        "config/plugins/dns.example.yaml",
        "config/plugins/home-assistant-telemetry.example.yaml",
        "config/plugins/mqtt.example.yaml",
        "config/plugins/network.example.yaml",
        "config/plugins/ntp.example.yaml",
        "config/plugins/shelly-telemetry.example.yaml",
        "config/plugins/teleinformation.example.yaml",
        "config/plugins/wireguard.example.yaml",
        "config/plugins/zwave.example.yaml",
    }


def test_copy_configuration_assets_populates_dist(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_root = tmp_path / "source"
    dist_directory = tmp_path / "dist"
    dist_directory.mkdir()
    relative_assets = (Path("config/first.example.yaml"), Path("config/second.yaml"))
    for relative_path in relative_assets:
        source = source_root / relative_path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(relative_path.name, encoding="utf-8")
    monkeypatch.setattr(prepare_release, "ROOT", source_root)
    monkeypatch.setattr(prepare_release, "DIST_DIRECTORY", dist_directory)
    monkeypatch.setattr(prepare_release, "CONFIGURATION_ASSETS", relative_assets)

    assets = prepare_release.copy_configuration_assets()

    assert assets == (
        dist_directory / "first.example.yaml",
        dist_directory / "second.yaml",
    )
    assert (dist_directory / "first.example.yaml").read_text(encoding="utf-8") == (
        "first.example.yaml"
    )
