from pathlib import Path
from unittest.mock import MagicMock, patch
from archunpack.engines._zip import ZipEngine
from archunpack.engines.factory import ENGINE_REGISTRY


def test_zip_registry() -> None:
    assert "zip" in ENGINE_REGISTRY
    assert ENGINE_REGISTRY["zip"] is ZipEngine


def test_zip_supported_format() -> None:
    assert ZipEngine.supported_format() == "zip"


def test_zip_availability() -> None:
    engine = ZipEngine()
    res = engine.test_availability()
    assert res.is_ok()
    assert res.unwrap() == "library"


@patch("pyzipper.AESZipFile")
def test_zip_extract_pyzipper_success(mock_aes: MagicMock, tmp_path: Path) -> None:
    engine = ZipEngine()
    archive = tmp_path / "test.zip"
    archive.touch()
    out_dir = tmp_path / "out"

    res = engine.extract([archive], out_dir, "secret")
    assert res.is_ok()
    assert res.unwrap() == out_dir
    
    mock_aes.assert_called_once_with(archive, "r")
    mock_aes_instance = mock_aes.return_value.__enter__.return_value
    mock_aes_instance.setpassword.assert_called_once_with(b"secret")
    mock_aes_instance.extractall.assert_called_once_with(path=str(out_dir))


@patch("pyzipper.AESZipFile")
@patch("zipfile.ZipFile")
def test_zip_extract_zipfile_fallback_success(
    mock_zf: MagicMock, mock_aes: MagicMock, tmp_path: Path
) -> None:
    # pyzipper throws error, zipfile handles it
    mock_aes.side_effect = RuntimeError("Not an AES zip")
    
    engine = ZipEngine()
    archive = tmp_path / "test.zip"
    archive.touch()
    out_dir = tmp_path / "out"

    res = engine.extract([archive], out_dir, "secret")
    assert res.is_ok()
    assert res.unwrap() == out_dir
    
    mock_zf.assert_called_once_with(archive, "r")
    mock_zf_instance = mock_zf.return_value.__enter__.return_value
    mock_zf_instance.setpassword.assert_called_once_with(b"secret")
    mock_zf_instance.extractall.assert_called_once_with(path=str(out_dir))


@patch("pyzipper.AESZipFile")
@patch("zipfile.ZipFile")
def test_zip_extract_pwd_fail(
    mock_zf: MagicMock, mock_aes: MagicMock, tmp_path: Path
) -> None:
    # Both library paths fail and raise BadPassword
    mock_aes.side_effect = RuntimeError("Bad password")
    mock_zf.side_effect = RuntimeError("Bad password")

    engine = ZipEngine()
    archive = tmp_path / "test.zip"
    archive.touch()
    out_dir = tmp_path / "out"

    with patch("archunpack.config.Config.detect_7zip", return_value=None):
        res = engine.extract([archive], out_dir, "wrong")
        assert res.is_fail()
        assert res.error_code == "PASSWORD_FAIL"


@patch("pyzipper.AESZipFile")
@patch("zipfile.ZipFile")
@patch("subprocess.run")
def test_zip_extract_cli_fallback(
    mock_run: MagicMock, mock_zf: MagicMock, mock_aes: MagicMock, tmp_path: Path
) -> None:
    # Library throws decryptions errors
    mock_aes.side_effect = RuntimeError("Decryption error")
    mock_zf.side_effect = RuntimeError("Decryption error")

    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = b"Ok"
    mock_res.stderr = b""
    mock_run.return_value = mock_res

    engine = ZipEngine()
    archive = tmp_path / "test.zip"
    archive.touch()
    out_dir = tmp_path / "out"

    with patch("archunpack.config.Config.detect_7zip", return_value=Path("c:/bin/7z.exe")):
        res = engine.extract([archive], out_dir, "secret")
        assert res.is_ok()
        assert res.unwrap() == out_dir
        
        mock_run.assert_called_once()
        cmd_arg = mock_run.call_args[0][0]
        assert "7z.exe" in cmd_arg[0]
        assert "-psecret" in cmd_arg
