# -*- mode: python ; coding: utf-8 -*-
# PyInstaller build: one folder (fast start, fewer antivirus false positives than onefile)
# containing two executables that share the same runtime:
#   SnapNarrate.exe      windowed tray app (what users launch)
#   snapnarrate-cli.exe  console build for doctor / voices / usage / self-test
# Build with scripts/build.ps1 rather than calling this directly.

import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = Path(SPECPATH).parent  # noqa: F821 - provided by PyInstaller
SRC = ROOT / "src"
ICON = str(ROOT / "assets" / "snapnarrate.ico")
VERSION = re.search(r'__version__ = "([^"]+)"', (SRC / "snap_narrate" / "__init__.py").read_text()).group(1)
VERSION_TUPLE = tuple((list(map(int, re.findall(r"\d+", VERSION)[:3])) + [0, 0, 0])[:3]) + (0,)


def version_resource(description, internal_name):
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=VERSION_TUPLE, prodvers=VERSION_TUPLE),
        kids=[
            StringFileInfo(
                [
                    StringTable(
                        "040904B0",
                        [
                            StringStruct("CompanyName", "SnapNarrate"),
                            StringStruct("FileDescription", description),
                            StringStruct("FileVersion", VERSION),
                            StringStruct("InternalName", internal_name),
                            StringStruct("OriginalFilename", f"{internal_name}.exe"),
                            StringStruct("ProductName", "SnapNarrate"),
                            StringStruct("ProductVersion", VERSION),
                        ],
                    )
                ]
            ),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )


def analysis(entry):
    return Analysis(  # noqa: F821
        [str(ROOT / "packaging" / entry)],
        pathex=[str(SRC)],
        # CustomTkinter ships its themes and fonts as data files.
        datas=[(ICON, "assets"), *collect_data_files("customtkinter")],
        # Addons and the pystray backend are imported by name at runtime.
        hiddenimports=collect_submodules("snap_narrate") + ["pystray._win32"],
        excludes=["pytest", "_pytest", "IPython", "matplotlib"],
        noarchive=False,
    )


gui = analysis("entry_gui.py")
cli = analysis("entry_cli.py")

gui_exe = EXE(  # noqa: F821
    PYZ(gui.pure),  # noqa: F821
    gui.scripts,
    [],
    exclude_binaries=True,
    name="SnapNarrate",
    console=False,
    icon=ICON,
    version=version_resource("SnapNarrate", "SnapNarrate"),
    upx=False,
)
cli_exe = EXE(  # noqa: F821
    PYZ(cli.pure),  # noqa: F821
    cli.scripts,
    [],
    exclude_binaries=True,
    name="snapnarrate-cli",
    console=True,
    icon=ICON,
    version=version_resource("SnapNarrate command line", "snapnarrate-cli"),
    upx=False,
)

COLLECT(  # noqa: F821
    gui_exe,
    gui.binaries,
    gui.datas,
    cli_exe,
    cli.binaries,
    cli.datas,
    name="SnapNarrate",
    upx=False,
)
