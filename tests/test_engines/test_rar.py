from pathlib import Path
from unittest.mock import MagicMock, patch
from archunpack.engines._rar import RarEngine
from archunpack.engines.factory import ENGINE_REGISTRY


def test_rar_registry() -> None:
    assert "rar" in ENGINE_REGISTRY
    assert ENGINE_REGISTRY["rar"] is RarEngine


def test_rar_supported_format() -> None:
    assert RarEngine.supported_format() == "rar"


def test_rar_availability() -> None:
    engine = RarEngine()
    with patch("sys.modules", {"rarfile": MagicMock()}):
        res = engine.test_availability()
        assert res.is_ok()
        assert res.unwrap() == "library"


@patch("rarfile.RarFile")
def test_rar_extract_library_success(mock_rf: MagicMock, tmp_path: Path) -> None:
    engine = RarEngine()
    archive = tmp_path / "test.rar"
    archive.touch()
    out_dir = tmp_path / "out"

    res = engine.extract([archive], out_dir, "secret")
    assert res.is_ok()
    assert res.unwrap() == out_dir

    mock_rf.assert_called_once_with(archive, "r")
    mock_rf_instance = mock_rf.return_value.__enter__.return_value
    mock_rf_instance.extractall.assert_called_once_with(path=str(out_dir), pwd="secret")


@patch("rarfile.RarFile")
@patch("subprocess.run")
def test_rar_extract_winrar_fallback(
    mock_run: MagicMock, mock_rf: MagicMock, tmp_path: Path
) -> None:
    # Library throws exception (e.g. unrar missing or encryption issue)
    mock_rf.side_effect = RuntimeError("Unrar executable not found")

    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = b"Extracted successfully"
    mock_res.stderr = b""
    mock_run.return_value = mock_res

    engine = RarEngine()
    archive = tmp_path / "test.rar"
    archive.touch()
    out_dir = tmp_path / "out"

    with patch("archunpack.config.Config.detect_winrar", return_value=Path("c:/bin/WinRAR.exe")), \
         patch("archunpack.config.Config.detect_7zip", return_value=None):
        res = engine.extract([archive], out_dir, "secret")
        assert res.is_ok()
        assert res.unwrap() == out_dir
        
        mock_run.assert_called_once()
        cmd_arg = mock_run.call_args[0][0]
        assert "WinRAR.exe" in cmd_arg[0]
        assert "-psecret" in cmd_arg


@patch("rarfile.RarFile")
@patch("subprocess.run")
def test_rar_extract_7z_fallback(
    mock_run: MagicMock, mock_rf: MagicMock, tmp_path: Path
) -> None:
    # Library throws exception, winrar is missing, 7z handles it
    mock_rf.side_effect = RuntimeError("Library failed")

    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = b"Ok"
    mock_res.stderr = b""
    mock_run.return_value = mock_res

    engine = RarEngine()
    archive = tmp_path / "test.rar"
    archive.touch()
    out_dir = tmp_path / "out"

    with patch("archunpack.config.Config.detect_winrar", return_value=None), \
         patch("archunpack.config.Config.detect_7zip", return_value=Path("c:/bin/7z.exe")):
        res = engine.extract([archive], out_dir, "secret")
        assert res.is_ok()
        assert res.unwrap() == out_dir
        
        mock_run.assert_called_once()
        cmd_arg = mock_run.call_args[0][0]
        assert "7z.exe" in cmd_arg[0]
        assert "-psecret" in cmd_arg


@patch("rarfile.RarFile")
def test_rar_extract_pwd_fail(mock_rf: MagicMock, tmp_path: Path) -> None:
    # Library throws incorrect password, no CLI executables
    mock_rf.side_effect = RuntimeError("Password incorrect")

    engine = RarEngine()
    archive = tmp_path / "test.rar"
    archive.touch()
    out_dir = tmp_path / "out"

    with patch("archunpack.config.Config.detect_winrar", return_value=None), \
         patch("archunpack.config.Config.detect_7zip", return_value=None):
        res = engine.extract([archive], out_dir, "wrong")
        assert res.is_fail()
        assert res.error_code == "PASSWORD_FAIL"
