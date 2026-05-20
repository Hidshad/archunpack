from pathlib import Path
from archunpack.config import Config
from archunpack.scanner import Scanner
from archunpack.file_utils import MAGIC_SIGNATURES


def test_scanner_mixed_dir(tmp_path: Path) -> None:
    # 1. mixed dir scanning
    (tmp_path / "a.7z").write_bytes(MAGIC_SIGNATURES["7z"][0] + b"\x00" * 20)
    (tmp_path / "b.zip").write_bytes(MAGIC_SIGNATURES["zip"][0] + b"\x00" * 20)
    (tmp_path / "c.rar").write_bytes(MAGIC_SIGNATURES["rar5"][0] + b"\x00" * 20)

    config = Config()
    scanner = Scanner(config)
    res = scanner.scan(tmp_path)
    assert res.is_ok()
    summary = res.unwrap()

    assert summary.total_files == 3
    assert summary.type_distribution["7z"] == 1
    assert summary.type_distribution["zip"] == 1
    assert summary.type_distribution["rar"] == 1
    assert len(summary.tasks) == 3


def test_scanner_prefix_skip(tmp_path: Path) -> None:
    # 2. ._ prefixes skipped
    (tmp_path / "a.7z").write_bytes(MAGIC_SIGNATURES["7z"][0] + b"\x00" * 20)
    (tmp_path / "._b.zip").write_bytes(MAGIC_SIGNATURES["zip"][0] + b"\x00" * 20)

    config = Config()
    scanner = Scanner(config)
    summary = scanner.scan(tmp_path).unwrap()
    assert summary.total_files == 1
    assert len(summary.tasks) == 1
    assert summary.tasks[0].file_paths[0].name == "a.7z"


def test_scanner_ignored_extensions(tmp_path: Path) -> None:
    # 3. uncompressed extensions ignored
    (tmp_path / "a.7z").write_bytes(MAGIC_SIGNATURES["7z"][0] + b"\x00" * 20)
    (tmp_path / "video.mp4").touch()
    (tmp_path / "doc.txt").touch()

    config = Config()
    scanner = Scanner(config)
    summary = scanner.scan(tmp_path).unwrap()
    
    # find_archive_files will skip mp4 and txt based on skip_extensions,
    # so they aren't even scanned or marked as ignored_files (as they are blacklisted)
    assert summary.total_files == 1
    assert len(summary.tasks) == 1


def test_scanner_unrecognized_signature_ignored(tmp_path: Path) -> None:
    # 7. unrecognized signature fallback
    # If file has non-archive extension and bad signature, it gets skipped and goes to ignored_files
    (tmp_path / "unknown.xyz").write_bytes(b"some random content here")

    config = Config()
    # Add .xyz to whitelist or make it not skippable
    config.skip_extensions = []
    
    scanner = Scanner(config)
    summary = scanner.scan(tmp_path).unwrap()
    
    assert summary.total_files == 1
    assert summary.ignored_count == 1
    assert len(summary.ignored_files) == 1
    assert "unknown.xyz" in summary.ignored_files[0]


def test_scanner_cad_spoof(tmp_path: Path) -> None:
    # 4. spoof suffix .CAD
    (tmp_path / "test.CAD").write_bytes(MAGIC_SIGNATURES["zip"][0] + b"\x00" * 20)

    config = Config()
    config.skip_extensions = [] # make sure CAD is not skipped
    scanner = Scanner(config)
    summary = scanner.scan(tmp_path).unwrap()

    assert len(summary.tasks) == 1
    assert summary.tasks[0].real_type == "zip"


def test_scanner_split_volumes(tmp_path: Path) -> None:
    # 5. split volume grouping
    (tmp_path / "arch.7z.001").write_bytes(MAGIC_SIGNATURES["7z"][0] + b"\x00" * 20)
    (tmp_path / "arch.7z.002").write_bytes(b"\x00" * 20)
    (tmp_path / "arch.7z.003").write_bytes(b"\x00" * 20)

    config = Config()
    scanner = Scanner(config)
    summary = scanner.scan(tmp_path).unwrap()

    assert summary.total_files == 3
    assert len(summary.tasks) == 1
    assert len(summary.tasks[0].file_paths) == 3
    assert summary.tasks[0].real_type == "7z"


def test_scanner_empty_dir(tmp_path: Path) -> None:
    # 8. empty dir scanning
    config = Config()
    scanner = Scanner(config)
    summary = scanner.scan(tmp_path).unwrap()

    assert summary.total_files == 0
    assert len(summary.tasks) == 0


def test_scanner_last_summary(tmp_path: Path) -> None:
    # 9. get_last_summary
    (tmp_path / "a.7z").write_bytes(MAGIC_SIGNATURES["7z"][0] + b"\x00" * 20)
    config = Config()
    scanner = Scanner(config)
    
    assert scanner.get_last_summary() is None
    
    summary = scanner.scan(tmp_path).unwrap()
    assert scanner.get_last_summary() is summary
