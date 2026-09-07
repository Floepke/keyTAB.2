#!/usr/bin/env python3
"""Build a Linux x86_64 AppImage for keyTAB2.

Run on a Linux machine from an activated project virtual environment:

    python deploy/build_AppImage.py --output ~/Desktop

The script installs the Python build dependencies when missing, creates a
PyInstaller onedir bundle, stages it in an AppDir, and invokes linuxdeploy.
Build files remain in the output directory when a packaging step fails.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.request import urlretrieve


LINUXDEPLOY_URL = (
    "https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/"
    "linuxdeploy-x86_64.AppImage"
)
APP_ID = "org.philipbergwerf.keytab2"
APP_NAME = "keyTAB2"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a keyTAB2 AppImage.")
    parser.add_argument(
        "--output",
        default=str(Path.home() / "Desktop"),
        help="Directory for the completed AppImage and temporary build files.",
    )
    parser.add_argument(
        "--keep-build",
        action="store_true",
        help="Keep intermediate build files after a successful build.",
    )
    parser.add_argument(
        "--extra-pyinstaller-args",
        nargs=argparse.REMAINDER,
        default=[],
        help="Arguments passed directly to PyInstaller.",
    )
    return parser.parse_args()


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    print("Running:", " ".join(command))
    subprocess.run(command, cwd=cwd, env=env, check=True)


def ensure_python_build_dependencies(project_root: Path) -> None:
    run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], cwd=project_root)
    if importlib.util.find_spec("PyInstaller") is None:
        run([sys.executable, "-m", "pip", "install", "PyInstaller"], cwd=project_root)


def download_linuxdeploy(tools_dir: Path) -> Path:
    tools_dir.mkdir(parents=True, exist_ok=True)
    linuxdeploy = tools_dir / "linuxdeploy.AppImage"
    if not linuxdeploy.exists():
        print(f"Downloading {LINUXDEPLOY_URL}")
        urlretrieve(LINUXDEPLOY_URL, linuxdeploy)
    linuxdeploy.chmod(linuxdeploy.stat().st_mode | 0o111)
    return linuxdeploy


def find_library_path(name: str) -> Path | None:
    """Locate a shared library reported by ldconfig on common Linux systems."""
    result = subprocess.run(["ldconfig", "-p"], capture_output=True, text=True, check=False)
    if result.returncode:
        return None
    for line in result.stdout.splitlines():
        if name not in line or " => " not in line:
            continue
        candidate = Path(line.rsplit(" => ", 1)[1].strip())
        if candidate.is_file():
            return candidate
    return None


def write_desktop_file(appdir: Path) -> Path:
    desktop_file = appdir / "usr" / "share" / "applications" / f"{APP_NAME}.desktop"
    desktop_file.parent.mkdir(parents=True, exist_ok=True)
    desktop_file.write_text(
        "[Desktop Entry]\n"
        f"Name={APP_NAME}\n"
        "Comment=Music notation editor\n"
        f"Exec={APP_NAME}\n"
        f"Icon={APP_NAME}\n"
        "Type=Application\n"
        "Categories=AudioVideo;Audio;Music;\n"
        "Terminal=false\n",
        encoding="utf-8",
    )
    return desktop_file


def write_apprun(appdir: Path) -> None:
    apprun = appdir / "AppRun"
    apprun.write_text(
        "#!/bin/sh\n"
        "HERE=\"$(dirname \"$(readlink -f \"$0\")\")\"\n"
        "export LD_LIBRARY_PATH=\"$HERE/usr/lib:$HERE/usr/lib/keyTAB2/_internal:$LD_LIBRARY_PATH\"\n"
        "exec \"$HERE/usr/bin/keyTAB2\" \"$@\"\n",
        encoding="utf-8",
    )
    apprun.chmod(apprun.stat().st_mode | 0o111)


def app_version(project_root: Path) -> str:
    version_file = project_root / "version.py"
    namespace: dict[str, object] = {}
    exec(version_file.read_text(encoding="utf-8"), namespace)
    return str(namespace.get("__version__", "dev"))


def main() -> int:
    args = parse_args()
    if platform.system() != "Linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise SystemExit("AppImage builds must run on Linux x86_64.")

    project_root = Path(__file__).resolve().parents[1]
    entry_script = project_root / "keyTAB2.py"
    icon_source = project_root / "icons" / "keyTAB.png"
    if not entry_script.is_file() or not icon_source.is_file():
        raise SystemExit("Expected keyTAB2.py and icons/keyTAB.png in the project root.")

    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    build_root = output_dir / "keyTAB2_build"
    shutil.rmtree(build_root, ignore_errors=True)
    build_root.mkdir()

    try:
        ensure_python_build_dependencies(project_root)
        work_dir = build_root / "work"
        spec_dir = build_root / "spec"
        dist_dir = build_root / "dist"
        run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--onedir",
                f"--name={APP_NAME}",
                f"--distpath={dist_dir}",
                f"--workpath={work_dir}",
                f"--specpath={spec_dir}",
                "--collect-all=PySide6",
                "--collect-all=cairocffi",
                "--collect-all=pangocffi",
                "--collect-all=pangocairocffi",
                *args.extra_pyinstaller_args,
                str(entry_script),
            ],
            cwd=project_root,
        )

        bundle_dir = dist_dir / APP_NAME
        executable = bundle_dir / APP_NAME
        if not executable.is_file():
            raise RuntimeError("PyInstaller did not produce the expected executable.")

        appdir = build_root / "AppDir"
        app_library_dir = appdir / "usr" / "lib" / APP_NAME
        app_library_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(bundle_dir, app_library_dir)
        launcher = appdir / "usr" / "bin" / APP_NAME
        launcher.parent.mkdir(parents=True, exist_ok=True)
        launcher.symlink_to(Path("../lib") / APP_NAME / APP_NAME)

        icon_target = appdir / "usr" / "share" / "icons" / "hicolor" / "512x512" / "apps" / f"{APP_NAME}.png"
        icon_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(icon_source, icon_target)
        desktop_file = write_desktop_file(appdir)
        write_apprun(appdir)

        linuxdeploy = download_linuxdeploy(build_root / "tools")
        environment = os.environ | {
            "APPIMAGE_EXTRACT_AND_RUN": "1",
            "LINUXDEPLOY_OUTPUT_VERSION": app_version(project_root),
        }
        deploy_command = [
            str(linuxdeploy),
            "--appdir",
            str(appdir),
            "--executable",
            str(launcher),
            "--desktop-file",
            str(desktop_file),
            "--icon-file",
            str(icon_target),
        ]
        for library_name in ("libcairo.so", "libpango-1.0.so", "libpangocairo-1.0.so"):
            library_path = find_library_path(library_name)
            if library_path is not None:
                deploy_command.extend(("--library", str(library_path)))
            else:
                print(f"Warning: {library_name} was not found; install its development/runtime package before building.")
        run([*deploy_command, "--output", "appimage"], cwd=build_root, env=environment)

        produced = sorted(build_root.glob("*.AppImage"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not produced:
            raise RuntimeError("linuxdeploy completed without creating an AppImage.")
        final_image = output_dir / f"{APP_NAME}-{app_version(project_root)}-x86_64.AppImage"
        shutil.move(str(produced[0]), final_image)
        final_image.chmod(final_image.stat().st_mode | 0o111)
        print(f"Build complete: {final_image}")
    except (OSError, subprocess.CalledProcessError, RuntimeError) as error:
        print(f"Build failed; retained artifacts at {build_root}: {error}", file=sys.stderr)
        return 1

    if not args.keep_build:
        shutil.rmtree(build_root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())