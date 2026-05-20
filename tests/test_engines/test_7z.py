from pathlib import Path
from unittest.mock import MagicMock, patch
from archunpack.engines._7z import SevenZEngine
from archunpack.engines.factory import ENGINE_REGISTRY
from archunpack.types import Result


def test_7z_registry() -> None:
    # 9. SevenZEngine is registered
    assert "7z" in ENGINE_REGISTRY
    assert ENGINE_REGISTRY["7z"] is SevenZEngine


def test_7z_supported_format() -> None:
    # 1. supported_format() returns "7z"
    assert SevenZEngine.supported_format() == "7z"


def test_7z_availability_library() -> None:
    # 2. test_availability() finds py7zr -> "library"
    engine = SevenZEngine()
    with patch.dict("sys.modules", {"py7zr": MagicMock()}):
        res = engine.test_availability()
        assert res.is_ok()
        assert res.unwrap() == "library"


def test_7z_availability_cli() -> None:
    # 3. test_availability() falls back to CLI if py7zr is missing but 7z.exe exists
    engine = SevenZEngine()
    with patch.dict("sys.modules", {"py7zr": None}), \
         patch("archunpack.config.Config.detect_7zip", return_value=Path("c:/bin/7z.exe")):
        res = engine.test_availability()
        assert res.is_ok()
        assert res.unwrap() == "cli"


def test_7z_availability_none() -> None:
    # 4. test_availability() fails if both are missing
    engine = SevenZEngine()
    with patch.dict("sys.modules", {"py7zr": None}), \
         patch("archunpack.config.Config.detect_7zip", return_value=None):
        res = engine.test_availability()
        assert res.is_fail()
        assert res.error_code == "ENGINE_UNAVAILABLE"


@patch("py7zr.SevenZipFile")
def test_7z_extract_library_success(mock_7z: MagicMock, tmp_path: Path) -> None:
    # 5. extract() library path success
    engine = SevenZEngine()
    archive = tmp_path / "test.7z"
    archive.touch()
    out_dir = tmp_path / "out"

    # Make test_availability return "library"
    with patch.object(engine, "test_availability", return_value=Result.ok("library")):
        res = engine.extract([archive], out_dir, "secret")
        assert res.is_ok()
        assert res.unwrap() == out_dir
        mock_7z.assert_called_once_with(archive, "r", password="secret")


@patch("py7zr.SevenZipFile")
def test_7z_extract_library_pwd_fail(mock_7z: MagicMock, tmp_path: Path) -> None:
    # 6. extract() password error raises PASSWORD_FAIL
    engine = SevenZEngine()
    archive = tmp_path / "test.7z"
    archive.touch()
    out_dir = tmp_path / "out"

    # Mock py7zr to raise password required or wrong password
    from py7zr.exceptions import PasswordRequired
    mock_7z.side_effect = PasswordRequired("Password required")

    with patch.object(engine, "test_availability", return_value=Result.ok("library")), \
         patch("archunpack.config.Config.detect_7zip", return_value=None):  # no CLI fallback
        res = engine.extract([archive], out_dir, "wrong")
        assert res.is_fail()
        assert res.error_code == "PASSWORD_FAIL"


@patch("py7zr.SevenZipFile")
@patch("subprocess.run")
def test_7z_extract_fallback_cli(
    mock_run: MagicMock, mock_7z: MagicMock, tmp_path: Path
) -> None:
    # 7. extract() library fails, fallbacks to CLI
    engine = SevenZEngine()
    archive = tmp_path / "test.7z"
    archive.touch()
    out_dir = tmp_path / "out"

    # Mock py7zr to fail
    from py7zr.exceptions import Bad7zFile
    mock_7z.side_effect = Bad7zFile("Corrupted header")  # type: ignore[no-untyped-call]

    # Mock subprocess run to return success
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = b"Everything is Ok"
    mock_res.stderr = b""
    mock_run.return_value = mock_res

    with patch.object(engine, "test_availability", return_value=Result.ok("library")), \
         patch("archunpack.config.Config.detect_7zip", return_value=Path("c:/bin/7z.exe")):
        res = engine.extract([archive], out_dir, "secret")
        assert res.is_ok()
        assert res.unwrap() == out_dir
        
        # Verify CLI was called
        mock_run.assert_called_once()
        cmd_arg = mock_run.call_args[0][0]
        assert "7z.exe" in cmd_arg[0]
        assert "-psecret" in cmd_arg
