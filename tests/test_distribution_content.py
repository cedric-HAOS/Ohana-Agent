"""Tests for the contents of built distribution artifacts."""

import tarfile
from pathlib import Path
from zipfile import ZipFile

import pytest

DIST_DIRECTORY = Path("dist")


@pytest.fixture(scope="session")
def wheel_path() -> Path:
    """Return the unique wheel available in the distribution directory."""
    wheels = list(DIST_DIRECTORY.glob("ohana_agent-*.whl"))

    assert DIST_DIRECTORY.is_dir(), (
        "The dist directory does not exist. Run `python -m build` before pytest."
    )
    assert len(wheels) == 1, (
        "Exactly one Ohana-Agent wheel must exist in dist/. "
        "Clean dist/ and run `python -m build` again."
    )

    return wheels[0]


@pytest.fixture(scope="session")
def sdist_path() -> Path:
    """Return the unique source distribution available in dist."""
    source_distributions = list(DIST_DIRECTORY.glob("ohana_agent-*.tar.gz"))

    assert DIST_DIRECTORY.is_dir(), (
        "The dist directory does not exist. Run `python -m build` before pytest."
    )
    assert len(source_distributions) == 1, (
        "Exactly one Ohana-Agent source distribution must exist in dist/. "
        "Clean dist/ and run `python -m build` again."
    )

    return source_distributions[0]


@pytest.fixture(scope="session")
def wheel_members(wheel_path: Path) -> set[str]:
    """Return all files contained in the wheel."""
    with ZipFile(wheel_path) as archive:
        return set(archive.namelist())


@pytest.fixture(scope="session")
def sdist_members(sdist_path: Path) -> set[str]:
    """Return normalized paths contained in the source distribution."""
    with tarfile.open(sdist_path, mode="r:gz") as archive:
        members: set[str] = set()

        for member in archive.getmembers():
            path_parts = Path(member.name).parts

            if len(path_parts) < 2:
                continue

            normalized_path = Path(*path_parts[1:]).as_posix()
            members.add(normalized_path)

        return members


def test_distribution_contains_wheel_and_sdist(
    wheel_path: Path,
    sdist_path: Path,
) -> None:
    """Provide the two supported distribution artifact formats."""
    assert wheel_path.is_file()
    assert wheel_path.suffix == ".whl"

    assert sdist_path.is_file()
    assert sdist_path.name.endswith(".tar.gz")


def test_wheel_contains_runtime_modules(
    wheel_members: set[str],
) -> None:
    """Include the application modules required at runtime."""
    required_modules = {
        "main.py",
        "application.py",
        "bootstrap.py",
        "production_agent.py",
        "configuration/configuration.py",
        "core/event_bus.py",
        "infrastructure/infrastructure.py",
        "observer/observation.py",
    }

    assert required_modules <= wheel_members

    required_packages = (
        "builder/",
        "configuration/",
        "core/",
        "health/",
        "infrastructure/",
        "loader/",
        "memory/",
        "mqtt/",
        "observer/",
        "plugin/",
        "plugins/",
        "recovery/",
        "scheduler/",
    )

    for package_prefix in required_packages:
        assert any(member.startswith(package_prefix) for member in wheel_members), (
            f"Missing runtime package in wheel: {package_prefix}"
        )


def test_wheel_contains_distribution_metadata(
    wheel_members: set[str],
) -> None:
    """Include standard metadata and the console entry point."""
    required_metadata_suffixes = (
        ".dist-info/METADATA",
        ".dist-info/WHEEL",
        ".dist-info/RECORD",
        ".dist-info/entry_points.txt",
        ".dist-info/licenses/LICENSE",
    )

    for suffix in required_metadata_suffixes:
        assert any(member.endswith(suffix) for member in wheel_members), (
            f"Missing wheel metadata: {suffix}"
        )


def test_wheel_excludes_non_runtime_resources(
    wheel_members: set[str],
) -> None:
    """Exclude development, deployment and local configuration files."""
    forbidden_prefixes = (
        "tests/",
        "scripts/",
        "docs/",
        "deployment/",
        "config/",
        "build/",
        "dist/",
    )

    forbidden_files = {
        "pyproject.toml",
        "MANIFEST.in",
    }

    assert not any(member.startswith(forbidden_prefixes) for member in wheel_members)
    assert forbidden_files.isdisjoint(wheel_members)


def test_sdist_contains_project_sources(
    sdist_members: set[str],
) -> None:
    """Include files needed to inspect and rebuild the project."""
    required_files = {
        "README.md",
        "LICENSE",
        "MANIFEST.in",
        "pyproject.toml",
        "main.py",
        "application.py",
        "bootstrap.py",
        "production_agent.py",
    }

    assert required_files <= sdist_members


def test_sdist_contains_linux_deployment_resources(
    sdist_members: set[str],
) -> None:
    """Include the reference Linux deployment resources."""
    required_files = {
        "deployment/install.sh",
        "deployment/update.sh",
        "deployment/systemd/ohana-agent.service",
        "docs/Deployment/Linux-Filesystem.md",
    }

    assert required_files <= sdist_members


def test_sdist_contains_configuration_examples_only(
    sdist_members: set[str],
) -> None:
    """Include examples without publishing active configuration."""
    required_examples = {
        "config/shikamaru.example.yaml",
        "config/infrastructure.example.yaml",
        "config/plugins/dns.example.yaml",
        "config/plugins/ntp.example.yaml",
        "config/plugins/mqtt.example.yaml",
        "config/plugins/network.example.yaml",
    }

    forbidden_active_configuration = {
        "config/shikamaru.yaml",
        "config/infrastructure.yaml",
        "config/plugins/dns.yaml",
        "config/plugins/ntp.yaml",
        "config/plugins/mqtt.yaml",
        "config/plugins/network.yaml",
    }

    assert required_examples <= sdist_members
    assert forbidden_active_configuration.isdisjoint(sdist_members)


def test_sdist_contains_tests_without_generated_artifacts(
    sdist_members: set[str],
) -> None:
    """Include tests while excluding caches and build outputs."""
    required_tests = {
        "tests/test_package_metadata.py",
        "tests/test_distribution_content.py",
    }

    forbidden_path_parts = {
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "build",
        "dist",
    }

    assert required_tests <= sdist_members

    for member in sdist_members:
        path_parts = set(Path(member).parts)

        assert path_parts.isdisjoint(forbidden_path_parts)
        assert not member.endswith((".pyc", ".pyo"))
