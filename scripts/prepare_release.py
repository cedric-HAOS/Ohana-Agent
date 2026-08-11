"""Prepare and validate an Ohana-Agent release."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = ROOT / "pyproject.toml"
DIST_DIRECTORY = ROOT / "dist"
CHECKSUMS_PATH = DIST_DIRECTORY / "SHA256SUMS"
CONFIGURATION_ASSETS = (
    Path("config/infrastructure.example.yaml"),
    Path("config/shikamaru.example.yaml"),
    Path("config/plugins/backup.example.yaml"),
    Path("config/plugins/dhcp.example.yaml"),
    Path("config/plugins/dns.example.yaml"),
    Path("config/plugins/home-assistant-telemetry.example.yaml"),
    Path("config/plugins/mqtt.example.yaml"),
    Path("config/plugins/network.example.yaml"),
    Path("config/plugins/ntp.example.yaml"),
    Path("config/plugins/shelly-telemetry.example.yaml"),
    Path("config/plugins/teleinformation.example.yaml"),
    Path("config/plugins/wireguard.example.yaml"),
    Path("config/plugins/zwave.example.yaml"),
)


def run_command(command: list[str | Path]) -> None:
    """Run a command from the project root."""
    printable_command = " ".join(str(argument) for argument in command)
    print(f"> {printable_command}")

    subprocess.run(
        [str(argument) for argument in command],
        cwd=ROOT,
        check=True,
    )


def read_project_version() -> str:
    """Read the distribution version from pyproject.toml."""
    with PYPROJECT_PATH.open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)

    try:
        version = pyproject["project"]["version"]
    except KeyError as error:
        raise RuntimeError("Missing project.version in pyproject.toml.") from error

    if not isinstance(version, str) or not version.strip():
        raise RuntimeError("project.version must be a non-empty string.")

    return version


def find_distribution_artifacts(version: str) -> tuple[Path, Path]:
    """Return the unique wheel and sdist for the release version."""
    normalized_version = version.replace("-", "_")

    wheels = sorted(DIST_DIRECTORY.glob(f"ohana_agent-{normalized_version}-*.whl"))
    sdists = sorted(DIST_DIRECTORY.glob(f"ohana_agent-{version}.tar.gz"))

    if len(wheels) != 1:
        raise RuntimeError(
            f"Exactly one wheel must exist for version {version}; found {len(wheels)}."
        )

    if len(sdists) != 1:
        raise RuntimeError(
            "Exactly one source distribution must exist for "
            f"version {version}; found {len(sdists)}."
        )

    return wheels[0], sdists[0]


def read_wheel_metadata(wheel: Path) -> str:
    """Return the METADATA file contained in the wheel."""
    with ZipFile(wheel) as archive:
        metadata_files = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]

        if len(metadata_files) != 1:
            raise RuntimeError("The wheel must contain exactly one METADATA file.")

        return archive.read(metadata_files[0]).decode("utf-8")


def validate_wheel_version(
    wheel: Path,
    expected_version: str,
) -> None:
    """Ensure the wheel metadata contains the expected version."""
    metadata = read_wheel_metadata(wheel)
    expected_line = f"Version: {expected_version}"

    if expected_line not in metadata.splitlines():
        raise RuntimeError(
            "The wheel metadata does not contain the expected "
            f"version {expected_version!r}."
        )


def copy_configuration_assets() -> tuple[Path, ...]:
    """Copy every deployable example configuration into the release directory."""
    assets: list[Path] = []
    seen_names: set[str] = set()

    for relative_path in CONFIGURATION_ASSETS:
        source = ROOT / relative_path
        if not source.is_file():
            raise RuntimeError(f"Missing configuration asset: {relative_path}")
        if source.name in seen_names:
            raise RuntimeError(f"Duplicate configuration asset name: {source.name}")
        seen_names.add(source.name)
        destination = DIST_DIRECTORY / source.name
        shutil.copy2(source, destination)
        assets.append(destination)

    return tuple(assets)


def calculate_sha256(path: Path) -> str:
    """Calculate the SHA-256 digest of a file."""
    digest = hashlib.sha256()

    with path.open("rb") as artifact_file:
        for chunk in iter(
            lambda: artifact_file.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def write_checksums(artifacts: tuple[Path, ...]) -> None:
    """Write SHA-256 checksums for release artifacts."""
    lines = [
        f"{calculate_sha256(artifact)}  {artifact.name}"
        for artifact in sorted(
            artifacts,
            key=lambda path: path.name,
        )
    ]

    CHECKSUMS_PATH.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def ensure_clean_worktree() -> None:
    """Ensure the Git working tree has no pending changes."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    if result.stdout.strip():
        raise RuntimeError(
            "The Git working tree is not clean. "
            "Commit or discard pending changes before preparing "
            "the release."
        )


def ensure_release_tag_does_not_exist(version: str) -> None:
    """Ensure the release tag does not already exist locally."""
    tag = f"v{version}"

    result = subprocess.run(
        [
            "git",
            "tag",
            "--list",
            tag,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    if result.stdout.strip():
        raise RuntimeError(f"The Git tag {tag} already exists locally.")


def main() -> int:
    """Prepare all local GitHub release artifacts."""
    version = read_project_version()
    tag = f"v{version}"

    print(f"Preparing Ohana-Agent {tag}")
    print()

    ensure_clean_worktree()
    ensure_release_tag_does_not_exist(version)

    print("Running quality checks...")
    run_command(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            ".",
        ]
    )
    run_command(
        [
            sys.executable,
            "-m",
            "ruff",
            "format",
            "--check",
            ".",
        ]
    )
    run_command(
        [
            sys.executable,
            "-m",
            "pytest",
        ]
    )

    print()
    print("Building release artifacts...")
    run_command(
        [
            sys.executable,
            "scripts/build_release.py",
        ]
    )

    wheel, sdist = find_distribution_artifacts(version)
    validate_wheel_version(wheel, version)
    configuration_assets = copy_configuration_assets()

    print()
    print("Validating clean installation...")
    run_command(
        [
            sys.executable,
            "scripts/test_clean_install.py",
        ]
    )

    print()
    print("Generating SHA-256 checksums...")
    release_assets = (*configuration_assets, wheel, sdist)
    write_checksums(release_assets)

    print()
    print("Release preparation succeeded.")
    print(f"Version : {version}")
    print(f"Tag     : {tag}")
    print("Artifacts:")

    for artifact in (*release_assets, CHECKSUMS_PATH):
        print(f" - {artifact.relative_to(ROOT)}")

    print()
    print("The release is ready to be tagged and published.")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        OSError,
        RuntimeError,
        subprocess.CalledProcessError,
    ) as error:
        print(
            f"Release preparation failed: {error}",
            file=sys.stderr,
        )
        raise SystemExit(1) from error
