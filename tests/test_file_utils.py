import logging
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from archunpack.config import Config
from archunpack.file_utils import (
    MAGIC_SIGNATURES,
    identify_type,
    normalize_type,
    is_skippable,
    detect_encryption,
    find_archive_files,
    group_split_volumes,
    ensure_output_path,
    safe_delete,
    detect_archive_type_from_path,
)


def test_identify_type_7z(tmp_path: Path) -> None:
    f = tmp_path / "test.7z"
    f.write_bytes(MAGIC_SIGNATURES["7z"][0] + b"\x00" * 20)
    res = identify_type(f)
    assert res.is_ok()
    assert res.unwrap() == "7z"


def test_identify_type_zip_cad(tmp_path: Path) -> None:
    # Test zip signature even with a spoofed .CAD extension
    f = tmp_path / "test.CAD"
    f.write_bytes(MAGIC_SIGNATURES["zip"][0] + b"\x00" * 20)
    res = identify_type(f)
    assert res.is_ok()
    assert res.unwrap() == "zip"


def test_identify_type_rar5(tmp_path: Path) -> None:
    f = tmp_path / "test.rar"
    f.write_bytes(MAGIC_SIGNATURES["rar5"][0] + b"\x00" * 20)
    res = identify_type(f)
    assert res.is_ok()
    assert res.unwrap() == "rar5"


def test_identify_type_tar(tmp_path: Path) -> None:
    f = tmp_path / "test.tar"
    # tar signature is at offset 257
    content = b"\x00" * 257 + MAGIC_SIGNATURES["tar"][0] + b"\x00" * 250
    f.write_bytes(content)
    res = identify_type(f)
    assert res.is_ok()
    assert res.unwrap() == "tar"


def test_identify_type_tar_gz(tmp_path: Path) -> None:
    # A .tar.gz file has gz signature but is identified as tar.gz because of its suffix
    f = tmp_path / "test.tar.gz"
    f.write_bytes(MAGIC_SIGNATURES["gz"][0] + b"\x00" * 20)
    res = identify_type(f)
    assert res.is_ok()
    assert res.unwrap() == "tar.gz"


def test_identify_type_unknown(tmp_path: Path) -> None:
    f = tmp_path / "test.txt"
    f.write_bytes(b"hello world this is some random text file")
    res = identify_type(f)
    assert res.is_fail()
    assert res.error_code == "UNKNOWN_SIGNATURE"


def test_normalize_type() -> None:
    assert normalize_type("rar5") == "rar"
    assert normalize_type("rar4") == "rar"
    assert normalize_type("gz") == "tar.gz"
    assert normalize_type("bz2") == "tar.bz2"
    assert normalize_type("xz") == "tar.xz"
    assert normalize_type("zip") == "zip"


def test_is_skippable() -> None:
    config = Config()
    # 1. Skip extensions
    assert is_skippable(Path("a.mp4"), config) is True
    assert is_skippable(Path("a.txt"), config) is True
    assert is_skippable(Path("a.7z"), config) is False

    # 2. Prefix skip
    assert is_skippable(Path("._temp.7z"), config) is True
    assert is_skippable(Path("normal.7z"), config) is False


def test_group_split_volumes() -> None:
    files = [
        Path("c:/arch.7z.001"),
        Path("c:/arch.7z.002"),
        Path("c:/arch.7z.003"),
        Path("c:/other.zip"),
        Path("c:/another.z01"),
        Path("c:/another.z02"),
        Path("c:/another.zip"),
    ]
    grouped = group_split_volumes(files)

    assert len(grouped) == 3
    # Check 7z split volume
    key_7z = str(Path("c:/arch.7z.001"))
    assert key_7z in grouped
    assert grouped[key_7z] == [
        Path("c:/arch.7z.001"),
        Path("c:/arch.7z.002"),
        Path("c:/arch.7z.003"),
    ]

    # Check zip split volume
    key_zip = str(Path("c:/another.zip"))
    assert key_zip in grouped
    assert grouped[key_zip] == [
        Path("c:/another.zip"),
        Path("c:/another.z01"),
        Path("c:/another.z02"),
    ]

    # Check non-split single file
    key_other = str(Path("c:/other.zip"))
    assert key_other in grouped
    assert grouped[key_other] == [Path("c:/other.zip")]


def test_group_split_volumes_gap(caplog: pytest.LogCaptureFixture) -> None:
    files = [
        Path("c:/arch.7z.001"),
        # missing 002
        Path("c:/arch.7z.003"),
    ]
    with caplog.at_level(logging.WARNING):
        grouped = group_split_volumes(files)
    
    assert len(grouped) == 1
    assert "Split volume gap detected" in caplog.text


def test_ensure_output_path() -> None:
    source_root = Path("c:/source")
    output_root = Path("d:/output")

    # Single archive
    src = Path("c:/source/a/b/file.7z")
    out = ensure_output_path(src, source_root, output_root)
    assert out.resolve() == Path("d:/output/a/b/file").resolve()

    # Split volume
    src_split = Path("c:/source/a/b/file.7z.001")
    out_split = ensure_output_path(src_split, source_root, output_root)
    assert out_split.resolve() == Path("d:/output/a/b/file").resolve()

    # tar.gz double extension
    src_tgz = Path("c:/source/file.tar.gz")
    out_tgz = ensure_output_path(src_tgz, source_root, output_root)
    assert out_tgz.resolve() == Path("d:/output/file").resolve()


def test_safe_delete(tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    
    outside = tmp_path / "outside.txt"
    outside.touch()

    inside_file = allowed_root / "inside.txt"
    inside_file.touch()

    inside_dir = allowed_root / "inside_dir"
    inside_dir.mkdir()
    (inside_dir / "child.txt").touch()

    # 1. Try to delete outside
    res = safe_delete(outside, allowed_root)
    assert res.is_fail()
    assert res.error_code == "OUT_OF_BOUNDS_DELETE"
    assert outside.exists()

    # 2. Delete inside file
    res = safe_delete(inside_file, allowed_root)
    assert res.is_ok()
    assert not inside_file.exists()

    # 3. Delete inside dir
    res = safe_delete(inside_dir, allowed_root)
    assert res.is_ok()
    assert not inside_dir.exists()


def test_detect_archive_type_from_path() -> None:
    assert detect_archive_type_from_path(Path("a.tar.gz")) == "tar.gz"
    assert detect_archive_type_from_path(Path("a.tgz")) == "tar.gz"
    assert detect_archive_type_from_path(Path("a.7z.001")) == "7z"
    assert detect_archive_type_from_path(Path("a.zip")) == "zip"
    assert detect_archive_type_from_path(Path("a.z02")) == "zip"
    assert detect_archive_type_from_path(Path("a.rar")) == "rar"
    assert detect_archive_type_from_path(Path("a.txt")) is None


def test_find_archive_files(tmp_path: Path) -> None:
    config = Config()
    (tmp_path / "a.7z").touch()
    (tmp_path / "b.mp4").touch() # skippable
    (tmp_path / "._ignore.zip").touch() # skippable prefix
    
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.zip").touch()

    files = find_archive_files(tmp_path, config)
    assert len(files) == 2
    paths = {f.name for f in files}
    assert "a.7z" in paths
    assert "c.zip" in paths


@patch("py7zr.SevenZipFile")
@patch("zipfile.ZipFile")
@patch("rarfile.RarFile")
def test_detect_encryption(
    mock_rar: MagicMock, mock_zip: MagicMock, mock_7z: MagicMock, tmp_path: Path
) -> None:
    # 7z encrypted
    mock_7z_instance = mock_7z.return_value.__enter__.return_value
    mock_7z_instance.needs_password.return_value = True
    
    f_7z = tmp_path / "test.7z"
    f_7z.touch()
    res = detect_encryption(f_7z, "7z")
    assert res.is_ok()
    assert res.unwrap() is True

    # zip not encrypted
    mock_zip_instance = mock_zip.return_value.__enter__.return_value
    mock_info = MagicMock()
    mock_info.flag_bits = 0  # not encrypted
    mock_zip_instance.infolist.return_value = [mock_info]
    
    f_zip = tmp_path / "test.zip"
    f_zip.touch()
    res = detect_encryption(f_zip, "zip")
    assert res.is_ok()
    assert res.unwrap() is False

    # rar encrypted
    mock_rar_instance = mock_rar.return_value.__enter__.return_value
    mock_rar_instance.needs_password.return_value = True
    
    f_rar = tmp_path / "test.rar"
    f_rar.touch()
    res = detect_encryption(f_rar, "rar")
    assert res.is_ok()
    assert res.unwrap() is True

    # tar always False
    f_tar = tmp_path / "test.tar"
    f_tar.touch()
    res = detect_encryption(f_tar, "tar")
    assert res.is_ok()
    assert res.unwrap() is False
