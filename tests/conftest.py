"""Shared packaging validation against the current checkout."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def distribution_directory(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build once unless a release validation explicitly selects its artifacts."""
    selected = os.environ.get("OHANA_TEST_DIST")
    if selected:
        return Path(selected).resolve()
    directory = tmp_path_factory.mktemp("agent-distribution")
    result = subprocess.run(
        [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(directory)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return directory


@pytest.fixture(scope="session")
def wheel_path(distribution_directory: Path) -> Path:
    wheels = list(distribution_directory.glob("ohana_agent-*.whl"))
    assert len(wheels) == 1, "Select exactly one Agent wheel for validation"
    return wheels[0]


@pytest.fixture(scope="session")
def sdist_path(distribution_directory: Path) -> Path:
    archives = list(distribution_directory.glob("ohana_agent-*.tar.gz"))
    assert len(archives) == 1, "Select exactly one Agent source archive for validation"
    return archives[0]
