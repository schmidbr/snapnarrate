from __future__ import annotations

from pathlib import Path

from snap_narrate import versioning


def test_get_app_version_prefers_metadata(monkeypatch) -> None:
    versioning.get_app_version.cache_clear()
    monkeypatch.setattr("snap_narrate.versioning.importlib_metadata.version", lambda name: "9.9.9")
    assert versioning.get_app_version() == "9.9.9"


def test_get_app_version_falls_back_to_pyproject(monkeypatch, tmp_path: Path) -> None:
    versioning.get_app_version.cache_clear()

    def raise_not_found(name):  # noqa: ANN001
        raise versioning.importlib_metadata.PackageNotFoundError

    monkeypatch.setattr("snap_narrate.versioning.importlib_metadata.version", raise_not_found)
    monkeypatch.setattr("snap_narrate.versioning.package_version", "")

    fake_pkg = tmp_path / "x" / "y"
    fake_pkg.mkdir(parents=True, exist_ok=True)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nversion = \"1.2.3\"\n", encoding="utf-8")
    monkeypatch.setattr("snap_narrate.versioning.Path.resolve", lambda self: fake_pkg / "versioning.py")

    assert versioning.get_app_version() == "1.2.3"


def test_get_app_version_returns_unknown_when_unavailable(monkeypatch) -> None:
    versioning.get_app_version.cache_clear()

    def raise_generic(name):  # noqa: ANN001
        raise RuntimeError("boom")

    monkeypatch.setattr("snap_narrate.versioning.importlib_metadata.version", raise_generic)
    monkeypatch.setattr("snap_narrate.versioning.package_version", "")
    monkeypatch.setattr("snap_narrate.versioning.Path.open", lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError()))
    assert versioning.get_app_version() == "unknown"


def test_get_app_version_falls_back_to_package_version(monkeypatch) -> None:
    versioning.get_app_version.cache_clear()

    def raise_not_found(name):  # noqa: ANN001
        raise versioning.importlib_metadata.PackageNotFoundError

    monkeypatch.setattr("snap_narrate.versioning.importlib_metadata.version", raise_not_found)
    monkeypatch.setattr("snap_narrate.versioning.package_version", "0.4.2")

    assert versioning.get_app_version() == "0.4.2"
