from ohana_agent.plugins.runtime.discovery.local_directory_provider import (
    LocalDirectoryProvider,
)


def test_local_directory_provider_returns_empty_tuple_when_root_does_not_exist(
    tmp_path,
) -> None:
    provider = LocalDirectoryProvider(tmp_path / "missing")

    assert provider.discover() == ()


def test_local_directory_provider_returns_empty_tuple_when_root_is_not_directory(
    tmp_path,
) -> None:
    file_path = tmp_path / "plugins"
    file_path.write_text("", encoding="utf-8")

    provider = LocalDirectoryProvider(file_path)

    assert provider.discover() == ()


def test_local_directory_provider_ignores_files(tmp_path) -> None:
    (tmp_path / "README.md").write_text("", encoding="utf-8")

    provider = LocalDirectoryProvider(tmp_path)

    assert provider.discover() == ()


def test_local_directory_provider_ignores_directories_without_plugin_file(
    tmp_path,
) -> None:
    (tmp_path / "dns").mkdir()

    provider = LocalDirectoryProvider(tmp_path)

    assert provider.discover() == ()


def test_local_directory_provider_discovers_directory_with_plugin_file(
    tmp_path,
) -> None:
    plugin_dir = tmp_path / "dns"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.py").write_text("", encoding="utf-8")

    provider = LocalDirectoryProvider(tmp_path)

    descriptors = provider.discover()

    assert len(descriptors) == 1
    assert descriptors[0].name == "dns"
    assert descriptors[0].path == plugin_dir


def test_local_directory_provider_discovers_multiple_plugins_sorted_by_name(
    tmp_path,
) -> None:
    mqtt_dir = tmp_path / "mqtt"
    dns_dir = tmp_path / "dns"

    mqtt_dir.mkdir()
    dns_dir.mkdir()

    (mqtt_dir / "plugin.py").write_text("", encoding="utf-8")
    (dns_dir / "plugin.py").write_text("", encoding="utf-8")

    provider = LocalDirectoryProvider(tmp_path)

    descriptors = provider.discover()

    assert [descriptor.name for descriptor in descriptors] == ["dns", "mqtt"]
