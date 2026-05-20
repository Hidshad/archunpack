from pathlib import Path
from unittest.mock import MagicMock, patch
from archunpack.engines._tar import TarEngine
from archunpack.engines.factory import ENGINE_REGISTRY


def test_tar_registry() -> None:
    for fmt in ("tar", "tar.gz", "tar.bz2", "tar.xz"):
        assert fmt in ENGINE_REGISTRY
        assert ENGINE_REGISTRY[fmt] is TarEngine


def test_tar_supported_format() -> None:
    assert TarEngine.supported_format() == "tar"


def test_tar_availability() -> None:
    engine = TarEngine()
    res = engine.test_availability()
    assert res.is_ok()
    assert res.unwrap() == "library"


@patch("tarfile.open")
def test_tar_extract_plain(mock_open: MagicMock, tmp_path: Path) -> None:
    engine = TarEngine()
    archive = tmp_path / "test.tar"
    archive.touch()
    out_dir = tmp_path / "out"

    res = engine.extract([archive], out_dir, password=None)
    assert res.is_ok()
    assert res.unwrap() == out_dir

    mock_open.assert_called_once_with(str(archive), "r")
    mock_open.return_value.__enter__.return_value.extractall.assert_called_once_with(
        path=str(out_dir)
    )


@patch("tarfile.open")
def test_tar_extract_gz(mock_open: MagicMock, tmp_path: Path) -> None:
    engine = TarEngine()
    archive = tmp_path / "test.tar.gz"
    archive.touch()
    out_dir = tmp_path / "out"

    res = engine.extract([archive], out_dir, password="ignored_pwd")
    assert res.is_ok()
    assert res.unwrap() == out_dir

    mock_open.assert_called_once_with(str(archive), "r:gz")


@patch("tarfile.open")
def test_tar_extract_bz2(mock_open: MagicMock, tmp_path: Path) -> None:
    engine = TarEngine()
    archive = tmp_path / "test.tbz2"
    archive.touch()
    out_dir = tmp_path / "out"

    res = engine.extract([archive], out_dir, password=None)
    assert res.is_ok()
    assert res.unwrap() == out_dir

    mock_open.assert_called_once_with(str(archive), "r:bz2")


@patch("tarfile.open")
def test_tar_extract_xz(mock_open: MagicMock, tmp_path: Path) -> None:
    engine = TarEngine()
    archive = tmp_path / "test.tar.xz"
    archive.touch()
    out_dir = tmp_path / "out"

    res = engine.extract([archive], out_dir, password=None)
    assert res.is_ok()
    assert res.unwrap() == out_dir

    mock_open.assert_called_once_with(str(archive), "r:xz")
