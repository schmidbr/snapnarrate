from __future__ import annotations

import subprocess
from pathlib import Path


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class ShortcutManager:
    def __init__(self, app_name: str = "Screen Reader") -> None:
        self.app_name = app_name

    @property
    def shortcut_name(self) -> str:
        return f"{self.app_name}.lnk"

    def desktop_shortcut_path(self) -> Path:
        desktop = Path.home() / "Desktop"
        return desktop / self.shortcut_name

    def startup_shortcut_path(self) -> Path:
        startup_dir = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        return startup_dir / self.shortcut_name

    def create_shortcut(
        self,
        destination: Path,
        target: str,
        arguments: str,
        working_dir: str,
        icon_path: str | None = None,
        description: str = "Screen Reader",
    ) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        script = [
            "$WshShell = New-Object -ComObject WScript.Shell",
            f"$Shortcut = $WshShell.CreateShortcut({_ps_quote(str(destination))})",
            f"$Shortcut.TargetPath = {_ps_quote(target)}",
            f"$Shortcut.Arguments = {_ps_quote(arguments)}",
            f"$Shortcut.WorkingDirectory = {_ps_quote(working_dir)}",
            f"$Shortcut.Description = {_ps_quote(description)}",
        ]
        if icon_path:
            script.append(f"$Shortcut.IconLocation = {_ps_quote(icon_path)}")
        script.append("$Shortcut.Save()")
        self._run_powershell(";\n".join(script))
        return destination

    def remove_shortcut(self, destination: Path) -> bool:
        if destination.exists():
            destination.unlink()
            return True
        return False

    def create_desktop_shortcut(
        self,
        target: str,
        arguments: str,
        working_dir: str,
        icon_path: str | None = None,
    ) -> Path:
        return self.create_shortcut(
            destination=self.desktop_shortcut_path(),
            target=target,
            arguments=arguments,
            working_dir=working_dir,
            icon_path=icon_path,
            description="Screen Reader Launcher",
        )

    def create_startup_shortcut(
        self,
        target: str,
        arguments: str,
        working_dir: str,
        icon_path: str | None = None,
    ) -> Path:
        return self.create_shortcut(
            destination=self.startup_shortcut_path(),
            target=target,
            arguments=arguments,
            working_dir=working_dir,
            icon_path=icon_path,
            description="Screen Reader Startup",
        )

    def _run_powershell(self, script: str) -> None:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            raise RuntimeError(f"Failed to create shortcut: {stderr}")

