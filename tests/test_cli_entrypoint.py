"""Tests for the public CLI entry point declared in the wheel."""

from configparser import ConfigParser
from io import StringIO
from pathlib import Path
from zipfile import ZipFile

import pytest

DIST_DIRECTORY = Path("dist")
EXPECTED_CONSOLE_SCRIPT = "ohana-agent"
EXPECTED_ENTRY_POINT = "main:main"
EXPECTED_FREEBOX_CONSOLE_SCRIPT = "ohana-agent-authorize-freebox"
EXPECTED_FREEBOX_ENTRY_POINT = "plugins.wireguard.authorize_freebox:main"


@pytest.fixture(scope="session")
def wheel_path() -> Path:
    """Return the unique Ohana-Agent wheel from dist."""
    assert DIST_DIRECTORY.is_dir(), (
        "The dist directory does not exist. Run `python -m build` before pytest."
    )

    wheels = list(DIST_DIRECTORY.glob("ohana_agent-*.whl"))

    assert len(wheels) == 1, (
        "Exactly one Ohana-Agent wheel must exist in dist/. "
        "Clean dist/ and run `python -m build` again."
    )

    return wheels[0]


@pytest.fixture(scope="session")
def wheel_members(wheel_path: Path) -> set[str]:
    """Return all files contained in the wheel."""
    with ZipFile(wheel_path) as archive:
        return set(archive.namelist())


@pytest.fixture(scope="session")
def entry_points_content(
    wheel_path: Path,
    wheel_members: set[str],
) -> str:
    """Read the wheel entry_points.txt metadata file."""
    matching_files = [
        member
        for member in wheel_members
        if member.endswith(".dist-info/entry_points.txt")
    ]

    assert len(matching_files) == 1, (
        "Exactly one entry_points.txt file must exist in the wheel."
    )

    with ZipFile(wheel_path) as archive:
        return archive.read(matching_files[0]).decode("utf-8")


@pytest.fixture(scope="session")
def entry_points_parser(
    entry_points_content: str,
) -> ConfigParser:
    """Parse the wheel entry point metadata."""
    parser = ConfigParser()
    parser.optionxform = str
    parser.read_file(StringIO(entry_points_content))

    return parser


def test_wheel_contains_entry_points_metadata(
    wheel_members: set[str],
) -> None:
    """Include the metadata used by installers to create CLI scripts."""
    matching_files = [
        member
        for member in wheel_members
        if member.endswith(".dist-info/entry_points.txt")
    ]

    assert len(matching_files) == 1


def test_console_scripts_section_is_declared(
    entry_points_parser: ConfigParser,
) -> None:
    """Declare the standard console_scripts entry point group."""
    assert entry_points_parser.has_section("console_scripts")


def test_ohana_agent_console_script_is_declared(
    entry_points_parser: ConfigParser,
) -> None:
    """Expose the public ohana-agent executable."""
    console_scripts = entry_points_parser["console_scripts"]

    assert EXPECTED_CONSOLE_SCRIPT in console_scripts


def test_ohana_agent_console_script_targets_main(
    entry_points_parser: ConfigParser,
) -> None:
    """Route the public executable to the supported Python callable."""
    console_scripts = entry_points_parser["console_scripts"]

    assert console_scripts[EXPECTED_CONSOLE_SCRIPT] == EXPECTED_ENTRY_POINT


def test_freebox_authorization_console_script_is_declared(
    entry_points_parser: ConfigParser,
) -> None:
    """Expose the installed Freebox authorization executable."""
    console_scripts = entry_points_parser["console_scripts"]

    assert EXPECTED_FREEBOX_CONSOLE_SCRIPT in console_scripts
    assert (
        console_scripts[EXPECTED_FREEBOX_CONSOLE_SCRIPT] == EXPECTED_FREEBOX_ENTRY_POINT
    )
