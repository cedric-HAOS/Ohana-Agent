"""Validate an Ohana-Agent installation in a clean virtual environment."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST_DIRECTORY = ROOT / "dist"
PACKAGE_NAME = "ohana-agent"


def find_wheel() -> Path:
    """Return the unique Ohana-Agent wheel from dist."""
    wheels = sorted(DIST_DIRECTORY.glob("ohana_agent-*.whl"))

    if len(wheels) != 1:
        raise RuntimeError(
            "Exactly one Ohana-Agent wheel must exist in dist/. "
            "Run `python scripts/build_release.py` first."
        )

    return wheels[0]


def virtual_environment_python(environment: Path) -> Path:
    """Return the Python executable for the current platform."""
    if os.name == "nt":
        return environment / "Scripts" / "python.exe"

    return environment / "bin" / "python"


def virtual_environment_cli(environment: Path) -> Path:
    """Return the installed Ohana-Agent executable."""
    if os.name == "nt":
        return environment / "Scripts" / "ohana-agent.exe"

    return environment / "bin" / "ohana-agent"


def virtual_environment_katsuyu_cli(environment: Path) -> Path:
    """Return the installed Katsuyu worker executable."""
    if os.name == "nt":
        return environment / "Scripts" / "ohana-katsuyu.exe"

    return environment / "bin" / "ohana-katsuyu"


def run_command(
    command: list[str | Path],
    *,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command and display its output."""
    printable_command = " ".join(str(argument) for argument in command)
    print(f"> {printable_command}")

    result = subprocess.run(
        [str(argument) for argument in command],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.stdout:
        print(result.stdout.rstrip())

    if result.stderr:
        print(result.stderr.rstrip())

    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed with exit code {result.returncode}: {printable_command}"
        )

    return result


def main() -> int:
    """Validate installation and execution from a clean environment."""
    wheel = find_wheel()

    print(f"Testing clean installation from {wheel.name}")
    print()

    temporary_root = Path(tempfile.mkdtemp(prefix="ohana-agent-install-"))
    environment = temporary_root / "venv"

    try:
        print("Creating isolated virtual environment...")
        run_command(
            [
                sys.executable,
                "-m",
                "venv",
                environment,
            ]
        )

        python_executable = virtual_environment_python(environment)
        cli_executable = virtual_environment_cli(environment)
        katsuyu_executable = virtual_environment_katsuyu_cli(environment)

        print()
        print("Installing the wheel...")
        run_command(
            [
                python_executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                wheel,
            ]
        )

        if not cli_executable.is_file():
            raise RuntimeError(f"The CLI executable was not created: {cli_executable}")
        if not katsuyu_executable.is_file():
            raise RuntimeError(
                f"The Katsuyu executable was not created: {katsuyu_executable}"
            )

        print()
        print("Checking installed package metadata...")
        metadata_result = run_command(
            [
                python_executable,
                "-c",
                (
                    "from importlib.metadata import metadata, version; "
                    "data = metadata('ohana-agent'); "
                    "print(data['Name']); "
                    "print(version('ohana-agent'))"
                ),
            ]
        )

        metadata_lines = [
            line.strip() for line in metadata_result.stdout.splitlines() if line.strip()
        ]

        if len(metadata_lines) < 2:
            raise RuntimeError("The installed distribution metadata is incomplete.")

        if metadata_lines[0] != PACKAGE_NAME:
            raise RuntimeError(
                f"Unexpected installed package name: {metadata_lines[0]!r}"
            )

        print()
        print("Checking CLI help...")
        help_result = run_command(
            [
                cli_executable,
                "--help",
            ]
        )

        expected_options = {
            "--config",
            "--infrastructure",
            "--dns-config",
            "--backup-config",
            "--ntp-config",
            "--log-level",
            "--version",
        }

        missing_options = {
            option for option in expected_options if option not in help_result.stdout
        }

        if missing_options:
            raise RuntimeError(
                "Missing CLI options: " + ", ".join(sorted(missing_options))
            )

        print()
        print("Checking Katsuyu CLI help...")
        katsuyu_help = run_command([katsuyu_executable, "--help"])
        expected_katsuyu_options = {
            "--base-url",
            "--token-file",
            "--worker-id",
            "--poll-seconds",
            "--once",
        }
        missing_katsuyu_options = {
            option
            for option in expected_katsuyu_options
            if option not in katsuyu_help.stdout
        }
        if missing_katsuyu_options:
            raise RuntimeError(
                "Missing Katsuyu CLI options: "
                + ", ".join(sorted(missing_katsuyu_options))
            )

        print()
        print("Checking CLI version...")
        version_result = run_command(
            [
                cli_executable,
                "--version",
            ]
        )

        installed_version = metadata_lines[1]

        if installed_version not in version_result.stdout:
            raise RuntimeError(
                "The CLI version does not match the installed package "
                f"version {installed_version!r}."
            )

        print()
        print("Checking invalid argument handling...")

        invalid_result = subprocess.run(
            [
                str(cli_executable),
                "--unknown-option",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        if invalid_result.returncode == 0:
            raise RuntimeError("The CLI accepted an unknown option.")

        print()
        print("Clean installation validation succeeded.")
        print(f"Installed version: {installed_version}")
        print(f"Executable: {cli_executable}")

        return 0

    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
