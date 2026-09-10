#!/usr/bin/env python3
"""Build a macOS keyTAB2.app bundle and optional drag-and-drop DMG.

Run from an activated project virtual environment on macOS:

    python deploy/build_.app.py --output ~/Desktop
"""

from __future__ import annotations

import argparse
import importlib.util
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path


APP_NAME = "keyTAB2"
BUNDLE_IDENTIFIER = "org.philipbergwerf.keytab2"
APP_CATEGORY = "public.app-category.music"
DOCUMENT_UTI = "org.philipbergwerf.keytab2.score"
DEFAULT_SOUNDFONT = Path.home() / ".keyTAB2" / "soundfonts" / "FluidR3_GM.sf2"
UNUSED_QT_MODULES = (
    "Qt3DAnimation",
    "Qt3DCore",
    "Qt3DExtras",
    "Qt3DInput",
    "Qt3DLogic",
    "Qt3DRender",
    "QtBluetooth",
    "QtCharts",
    "QtConcurrent",
    "QtDataVisualization",
    "QtGraphs",
    "QtHelp",
    "QtLocation",
    "QtMultimedia",
    "QtMultimediaWidgets",
    "QtNetworkAuth",
    "QtNfc",
    "QtPdf",
    "QtPdfWidgets",
    "QtPositioning",
    "QtQuick",
    "QtQuick3D",
    "QtQuickControls2",
    "QtQuickWidgets",
    "QtRemoteObjects",
    "QtScxml",
    "QtSensors",
    "QtSerialBus",
    "QtSerialPort",
    "QtSpatialAudio",
    "QtSql",
    "QtStateMachine",
    "QtSvg",
    "QtSvgWidgets",
    "QtTest",
    "QtTextToSpeech",
    "QtUiTools",
    "QtWebChannel",
    "QtWebEngineCore",
    "QtWebEngineQuick",
    "QtWebEngineQuickDelegatesQml",
    "QtWebEngineWidgets",
    "QtWebSockets",
    "QtWebView",
    "QtWebViewQuick",
    "QtXml",
    "QtXmlPatterns",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a keyTAB2 macOS application bundle.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path.home() / "Desktop",
        help="Directory for the completed .app, DMG, and temporary build files.",
    )
    parser.add_argument("--no-dmg", action="store_true", help="Build only the .app bundle.")
    parser.add_argument("--keep-build", action="store_true", help="Keep intermediate build files on success.")
    parser.add_argument(
        "--extra-pyinstaller-args",
        nargs=argparse.REMAINDER,
        default=[],
        help="Arguments passed directly to PyInstaller.",
    )
    return parser.parse_args()


def run(command: list[str], *, cwd: Path) -> None:
    print("Running:", " ".join(command))
    subprocess.run(command, cwd=cwd, check=True)


def ensure_build_dependencies(project_root: Path) -> None:
    run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], cwd=project_root)
    if importlib.util.find_spec("PyInstaller") is None:
        run([sys.executable, "-m", "pip", "install", "PyInstaller"], cwd=project_root)


def require_command(name: str) -> str:
    command = shutil.which(name)
    if command is None:
        raise RuntimeError(f"Required macOS command not found: {name}")
    return command


def create_icns(source: Path, work_dir: Path) -> Path:
    if not source.is_file():
        raise RuntimeError(f"Application icon not found: {source}")
    if source.suffix.lower() == ".icns":
        return source

    sips = require_command("sips")
    iconutil = require_command("iconutil")
    iconset = work_dir / "keyTAB2.iconset"
    iconset.mkdir()
    try:
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                pixels = size * scale
                suffix = "@2x" if scale == 2 else ""
                target = iconset / f"icon_{size}x{size}{suffix}.png"
                subprocess.run(
                    [sips, "-z", str(pixels), str(pixels), str(source), "--out", str(target)],
                    check=True,
                    capture_output=True,
                )
        icon = work_dir / "keyTAB2.icns"
        subprocess.run([iconutil, "-c", "icns", str(iconset), "-o", str(icon)], check=True)
        return icon
    finally:
        shutil.rmtree(iconset, ignore_errors=True)


def project_version(project_root: Path) -> str:
    namespace: dict[str, object] = {}
    exec((project_root / "version.py").read_text(encoding="utf-8"), namespace)
    return str(namespace.get("__version__", "dev"))


def copy_qt_licenses(app_path: Path) -> None:
    import PySide6

    package_root = Path(PySide6.__file__).resolve().parent
    destination = app_path / "Contents" / "Resources" / "licenses" / "qt"
    for root in (package_root, package_root / "Qt", package_root / "Qt" / "LICENSES"):
        if not root.is_dir():
            continue
        for license_file in root.glob("**/LICENSE*"):
            if license_file.is_file():
                target = destination / license_file.relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(license_file, target)


def bundle_soundfont(app_path: Path, soundfont: Path = DEFAULT_SOUNDFONT) -> None:
    if not soundfont.is_file():
        raise RuntimeError(
            f"GM soundfont not found: {soundfont}. "
            "Install FluidR3_GM.sf2 at this path before building."
        )
    target = app_path / "Contents" / "Resources" / "soundfonts" / "FluidR3_GM.sf2"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(soundfont, target)


def update_info_plist(app_path: Path, version: str) -> None:
    plist_path = app_path / "Contents" / "Info.plist"
    with plist_path.open("rb") as stream:
        info = plistlib.load(stream)
    info.update(
        {
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleIdentifier": BUNDLE_IDENTIFIER,
            "CFBundleShortVersionString": version,
            "CFBundleVersion": version,
            "LSApplicationCategoryType": APP_CATEGORY,
            "UTExportedTypeDeclarations": [
                {
                    "UTTypeIdentifier": DOCUMENT_UTI,
                    "UTTypeDescription": "keyTAB2 score",
                    "UTTypeConformsTo": ["public.data"],
                    "UTTypeTagSpecification": {
                        "public.filename-extension": ["keytab", "piano"],
                        "public.mime-type": ["application/x-keytab"],
                    },
                }
            ],
            "CFBundleDocumentTypes": [
                {
                    "CFBundleTypeName": "keyTAB2 score",
                    "CFBundleTypeRole": "Editor",
                    "LSItemContentTypes": [DOCUMENT_UTI],
                    "CFBundleTypeExtensions": ["keytab", "piano"],
                    "LSHandlerRank": "Owner",
                },
                {
                    "CFBundleTypeName": "MIDI audio",
                    "CFBundleTypeRole": "Editor",
                    "LSItemContentTypes": ["public.midi"],
                    "CFBundleTypeExtensions": ["mid", "midi"],
                    "LSHandlerRank": "Alternate",
                },
            ],
        }
    )
    with plist_path.open("wb") as stream:
        plistlib.dump(info, stream)


def create_dmg(app_path: Path, work_dir: Path) -> Path:
    hdiutil = require_command("hdiutil")
    staging = work_dir / "dmg-staging"
    staging.mkdir()
    shutil.copytree(app_path, staging / app_path.name)
    (staging / "Applications").symlink_to("/Applications")
    dmg_path = work_dir / f"{APP_NAME}.dmg"
    run(
        [
            hdiutil,
            "create",
            "-volname",
            APP_NAME,
            "-srcfolder",
            str(staging),
            "-format",
            "UDZO",
            "-ov",
            str(dmg_path),
        ],
        cwd=work_dir,
    )
    shutil.rmtree(staging, ignore_errors=True)
    return dmg_path


def main() -> int:
    if sys.platform != "darwin":
        raise SystemExit("This builder must run on macOS.")

    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    output_dir = args.output.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    build_dir = output_dir / "keyTAB2_macos_build"
    shutil.rmtree(build_dir, ignore_errors=True)
    build_dir.mkdir()
    version = project_version(project_root)

    try:
        ensure_build_dependencies(project_root)
        icon = create_icns(project_root / "icons" / "keyTAB.png", build_dir)
        dist_dir = build_dir / "dist"
        run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--windowed",
                f"--name={APP_NAME}",
                f"--icon={icon}",
                f"--distpath={dist_dir}",
                f"--workpath={build_dir / 'work'}",
                f"--specpath={build_dir / 'spec'}",
                "--collect-all=cairocffi",
                "--collect-all=pangocffi",
                "--collect-all=pangocairocffi",
                *(f"--exclude-module=PySide6.{module}" for module in UNUSED_QT_MODULES),
                *args.extra_pyinstaller_args,
                str(project_root / "keyTAB2.py"),
            ],
            cwd=project_root,
        )
        app_path = dist_dir / f"{APP_NAME}.app"
        if not app_path.is_dir():
            raise RuntimeError("PyInstaller did not create the expected application bundle.")
        copy_qt_licenses(app_path)
        shutil.copy2(project_root / "LICENSE", app_path / "Contents" / "Resources" / "LICENSE")
        bundle_soundfont(app_path)
        update_info_plist(app_path, version)

        final_app = output_dir / f"{APP_NAME}.app"
        shutil.rmtree(final_app, ignore_errors=True)
        shutil.move(str(app_path), final_app)
        print(f"Application bundle created: {final_app}")
        if not args.no_dmg:
            dmg = create_dmg(final_app, build_dir)
            final_dmg = output_dir / dmg.name
            final_dmg.unlink(missing_ok=True)
            shutil.move(str(dmg), final_dmg)
            print(f"Installer DMG created: {final_dmg}")
            shutil.rmtree(final_app)
            print(f"Removed standalone application bundle: {final_app}")
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Build failed; retained artifacts at {build_dir}: {error}", file=sys.stderr)
        return 1

    if not args.keep_build:
        shutil.rmtree(build_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())