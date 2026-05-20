from pathlib import Path
from unittest.mock import patch
import pytest
from archunpack.config import Config


def test_default_config() -> None:
    config = Config()
    assert config.source_dir is None
    assert config.output_dir is None
    assert config.password_file is None
    assert config.max_depth == 5
    assert config.delete_intermediate is True
    assert config.overwrite_mode == "skip"
    assert config.max_parallel == 0
    assert config.log_dir == Path("./logs")
    assert config.log_level == "INFO"
    assert ".mp4" in config.skip_extensions
    assert "._" in config.skip_prefixes
    assert config.seven_zip_path is None
    assert config.winrar_path is None


def test_from_args() -> None:
    config = Config.from_args(
        source_dir="c:/src",
        output_dir="c:/out",
        max_depth=10,
        overwrite_mode="overwrite",
        dummy_field="ignored",
    )
    assert config.source_dir == Path("c:/src")
    assert config.output_dir == Path("c:/out")
    assert config.max_depth == 10
    assert config.overwrite_mode == "overwrite"


def test_invalid_overwrite_mode() -> None:
    with pytest.raises(ValueError, match="overwrite_mode must be"):
        Config(overwrite_mode="invalid")

    with pytest.raises(ValueError, match="overwrite_mode must be"):
        Config.from_args(overwrite_mode="invalid")


def test_detect_7zip(tmp_path: Path) -> None:
    # 1. Test when which finds it
    fake_exe = tmp_path / "7z.exe"
    fake_exe.touch()
    with patch("shutil.which", return_value=str(fake_exe)):
        found = Config.detect_7zip()
        assert found == fake_exe

    # 2. Test when which returns None, registry fails, check normal path
    with patch("shutil.which", return_value=None), \
         patch("pathlib.Path.exists", autospec=True, side_effect=lambda self: self.as_posix().endswith("7-Zip/7z.exe")):
        found = Config.detect_7zip()
        assert found is not None
        assert found.name == "7z.exe"


def test_detect_winrar(tmp_path: Path) -> None:
    # 1. Test when which finds it
    fake_exe = tmp_path / "WinRAR.exe"
    fake_exe.touch()
    with patch("shutil.which", return_value=str(fake_exe)):
        found = Config.detect_winrar()
        assert found == fake_exe

    # 2. Test when which returns None, check standard path
    with patch("shutil.which", return_value=None), \
         patch("pathlib.Path.exists", autospec=True, side_effect=lambda self: self.as_posix().endswith("WinRAR/WinRAR.exe")):
        found = Config.detect_winrar()
        assert found is not None
        assert found.name == "WinRAR.exe"


def test_ensure_dirs(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    output_dir = tmp_path / "output"
    config = Config(log_dir=log_dir, output_dir=output_dir)

    assert not log_dir.exists()
    assert not output_dir.exists()

    config.ensure_dirs()

    assert log_dir.exists()
    assert output_dir.exists()
