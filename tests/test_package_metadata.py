"""Tests for the Python package metadata."""

import tomllib
from pathlib import Path
from typing import Any

PYPROJECT_PATH = Path("pyproject.toml")


def load_pyproject() -> dict[str, Any]:
    """Load the project configuration."""
    with PYPROJECT_PATH.open("rb") as file:
        return tomllib.load(file)


def test_package_uses_setuptools_build_backend() -> None:
    """Build the distribution with the supported setuptools backend."""
    pyproject = load_pyproject()
    build_system = pyproject["build-system"]

    assert build_system["build-backend"] == "setuptools.build_meta"
    assert "setuptools>=77" in build_system["requires"]
    assert "wheel" in build_system["requires"]


def test_package_declares_public_metadata() -> None:
    """Expose the metadata required for a public release."""
    project = load_pyproject()["project"]

    assert project["name"] == "ohana-agent"
    assert project["version"] == "1.7.0"
    assert project["description"]
    assert project["readme"] == "README.md"
    assert project["requires-python"] == ">=3.13"
    assert project["license"] == "MIT"
    assert project["license-files"] == ["LICENSE"]


def test_package_declares_author() -> None:
    """Identify the package author."""
    project = load_pyproject()["project"]

    assert project["authors"] == [{"name": "Cédric Harnois"}]


def test_package_declares_runtime_dependencies() -> None:
    """Declare only runtime dependencies as mandatory."""
    dependencies = load_pyproject()["project"]["dependencies"]

    assert dependencies == [
        "PyYAML>=6.0",
        "pydantic>=2,<3",
        "dnspython>=2.7,<3",
        "paho-mqtt>=2,<3",
    ]

    assert "pytest" not in dependencies
    assert "ruff" not in dependencies
    assert "build" not in dependencies


def test_package_declares_development_dependencies() -> None:
    """Keep development tools outside runtime dependencies."""
    project = load_pyproject()["project"]

    assert project["optional-dependencies"]["development"] == [
        "build",
        "pytest",
        "ruff",
    ]


def test_package_declares_console_entry_point() -> None:
    """Expose the production command-line entry point."""
    project = load_pyproject()["project"]

    assert project["scripts"] == {
        "ohana-agent": "main:main",
    }


def test_package_declares_project_urls() -> None:
    """Expose the official project resources."""
    urls = load_pyproject()["project"]["urls"]

    repository = "https://github.com/cedric-HAOS/Ohana-Agent"

    assert urls["Homepage"] == repository
    assert urls["Repository"] == repository
    assert urls["Issues"] == f"{repository}/issues"


def test_package_excludes_tests_and_demo_scripts() -> None:
    """Exclude development-only packages from the distribution."""
    package_find = load_pyproject()["tool"]["setuptools"]["packages"]["find"]

    assert "tests*" in package_find["exclude"]
    assert "scripts*" in package_find["exclude"]
