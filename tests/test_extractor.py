from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from archunpack.config import Config
from archunpack.extractor import Extractor
from archunpack.types import ArchiveTask, Result, TaskStatus
from archunpack.password_mgr import PasswordManager
from archunpack.logger import AppLogger


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        source_dir=tmp_path / "src",
        output_dir=tmp_path / "out",
        password_file=tmp_path / "passwords.txt",
        max_depth=3,
        delete_intermediate=True,
        overwrite_mode="skip",
    )


@pytest.fixture
def mock_logger() -> MagicMock:
    logger = MagicMock(spec=AppLogger)
    logger.skipped_tasks = []
    return logger


@pytest.fixture
def mock_password_mgr() -> MagicMock:
    mgr = MagicMock(spec=PasswordManager)
    mgr.get_ordered_passwords.return_value = ["pass1", "pass2", "correct"]
    return mgr


def test_extractor_init(config: Config, mock_password_mgr: MagicMock, mock_logger: MagicMock) -> None:
    extractor = Extractor(config, mock_password_mgr, mock_logger)
    assert extractor.config == config
    assert extractor.password_mgr == mock_password_mgr
    assert extractor.logger == mock_logger


def test_extractor_missing_paths(
    config: Config, mock_password_mgr: MagicMock, mock_logger: MagicMock
) -> None:
    extractor = Extractor(config, mock_password_mgr, mock_logger)
    task = ArchiveTask(file_paths=[], real_type="zip")

    res = extractor.extract(task)
    assert res.is_fail()
    assert task.status == TaskStatus.ERROR
    mock_logger.log_task_fail.assert_called_once()


def test_extractor_file_not_found(
    config: Config, mock_password_mgr: MagicMock, mock_logger: MagicMock, tmp_path: Path
) -> None:
    extractor = Extractor(config, mock_password_mgr, mock_logger)
    task = ArchiveTask(file_paths=[tmp_path / "nonexistent.zip"], real_type="zip")

    res = extractor.extract(task)
    assert res.is_fail()
    assert task.status == TaskStatus.ERROR
    mock_logger.log_task_fail.assert_called_once()


@patch("archunpack.extractor.create_engine")
def test_extractor_unencrypted_success(
    mock_create_engine: MagicMock,
    config: Config,
    mock_password_mgr: MagicMock,
    mock_logger: MagicMock,
    tmp_path: Path,
) -> None:
    # Prepare files
    archive = tmp_path / "src" / "test.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.touch()

    task = ArchiveTask(file_paths=[archive], real_type="zip", is_encrypted=False)

    assert config.output_dir is not None
    mock_engine = MagicMock()
    mock_engine.extract.side_effect = lambda p, o, pw, m: (o.mkdir(parents=True, exist_ok=True), Result.ok(o))[1]
    mock_create_engine.return_value = Result.ok(mock_engine)

    extractor = Extractor(config, mock_password_mgr, mock_logger)
    
    with patch("archunpack.extractor.Scanner") as mock_scanner_cls:
        mock_scanner = MagicMock()
        mock_scanner.scan.return_value = Result.ok(MagicMock(tasks=[]))
        mock_scanner_cls.return_value = mock_scanner

        res = extractor.extract(task)
        assert res.is_ok()
        assert task.status == TaskStatus.DONE
        assert config.output_dir is not None
        assert task.output_path == config.output_dir / "test"
        
        mock_engine.extract.assert_called_once_with(
            [archive], config.output_dir / "test_tmp", None, config.overwrite_mode
        )
        mock_logger.log_task_done.assert_called_once()


@patch("archunpack.extractor.create_engine")
def test_extractor_unencrypted_fail(
    mock_create_engine: MagicMock,
    config: Config,
    mock_password_mgr: MagicMock,
    mock_logger: MagicMock,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "src" / "test.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.touch()

    task = ArchiveTask(file_paths=[archive], real_type="zip", is_encrypted=False)

    mock_engine = MagicMock()
    mock_engine.extract.return_value = Result.fail("Engine extraction failed", "EXTRACT_ERROR")
    mock_create_engine.return_value = Result.ok(mock_engine)

    extractor = Extractor(config, mock_password_mgr, mock_logger)
    res = extractor.extract(task)
    
    assert res.is_fail()
    assert task.status == TaskStatus.FAILED
    assert task.status_message == "Engine extraction failed"
    mock_logger.log_task_fail.assert_called_once_with(task, "Engine extraction failed")


@patch("archunpack.extractor.create_engine")
@patch("archunpack.extractor.detect_encryption")
def test_extractor_encrypted_password_loop_success(
    mock_detect_encryption: MagicMock,
    mock_create_engine: MagicMock,
    config: Config,
    mock_password_mgr: MagicMock,
    mock_logger: MagicMock,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "src" / "test.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.touch()

    # is_encrypted is None so we auto-detect
    task = ArchiveTask(file_paths=[archive], real_type="zip", is_encrypted=None)
    mock_detect_encryption.return_value = Result.ok(True)

    mock_engine = MagicMock()
    # pass1 fails, pass2 fails, correct succeeds
    def extract_side_effect(
        paths: list[Path], out_dir: Path, pwd: str | None, mode: str
    ) -> Result[Path]:
        if pwd == "correct":
            out_dir.mkdir(parents=True, exist_ok=True)
            return Result.ok(out_dir)
        return Result.fail("Bad password", "PASSWORD_FAIL")
    mock_engine.extract.side_effect = extract_side_effect
    mock_create_engine.return_value = Result.ok(mock_engine)

    extractor = Extractor(config, mock_password_mgr, mock_logger)
    
    with patch("archunpack.extractor.Scanner") as mock_scanner_cls:
        mock_scanner = MagicMock()
        mock_scanner.scan.return_value = Result.ok(MagicMock(tasks=[]))
        mock_scanner_cls.return_value = mock_scanner

        res = extractor.extract(task)
        
        assert res.is_ok()
        assert task.status == TaskStatus.DONE
        assert task.password == "correct"
        mock_password_mgr.record_hit.assert_called_once_with("correct")
        
        # Called attempts: 2 failed, 1 success
        assert mock_logger.log_password_attempt.call_count == 3
        mock_logger.log_password_attempt.assert_any_call(task, 1, success=False)
        mock_logger.log_password_attempt.assert_any_call(task, 2, success=False)
        mock_logger.log_password_attempt.assert_any_call(task, 3, success=True)


@patch("archunpack.extractor.create_engine")
def test_extractor_encrypted_password_loop_fail(
    mock_create_engine: MagicMock,
    config: Config,
    mock_password_mgr: MagicMock,
    mock_logger: MagicMock,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "src" / "test.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.touch()

    task = ArchiveTask(file_paths=[archive], real_type="zip", is_encrypted=True)

    mock_engine = MagicMock()
    mock_engine.extract.return_value = Result.fail("Bad password", "PASSWORD_FAIL")
    mock_create_engine.return_value = Result.ok(mock_engine)

    extractor = Extractor(config, mock_password_mgr, mock_logger)
    res = extractor.extract(task)
    
    assert res.is_fail()
    assert task.status == TaskStatus.FAILED
    assert task.status_message == "Bad password"
    assert mock_logger.log_password_attempt.call_count == 3  # Tried all three passwords
    mock_logger.log_task_fail.assert_called_once_with(task, "Bad password")


@patch("archunpack.extractor.create_engine")
def test_extractor_overwrite_skip(
    mock_create_engine: MagicMock,
    config: Config,
    mock_password_mgr: MagicMock,
    mock_logger: MagicMock,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "src" / "test.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.touch()

    task = ArchiveTask(file_paths=[archive], real_type="zip", is_encrypted=False)

    # Make output directory exists and is not empty
    assert config.output_dir is not None
    out_dir = config.output_dir / "test"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "existing.txt").touch()

    config.overwrite_mode = "skip"

    extractor = Extractor(config, mock_password_mgr, mock_logger)
    res = extractor.extract(task)
    
    assert res.is_ok()
    assert task.status == TaskStatus.SKIPPED
    assert len(mock_logger.skipped_tasks) == 1
    mock_create_engine.assert_not_called()


@patch("archunpack.extractor.create_engine")
def test_extractor_overwrite_overwrite(
    mock_create_engine: MagicMock,
    config: Config,
    mock_password_mgr: MagicMock,
    mock_logger: MagicMock,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "src" / "test.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.touch()

    task = ArchiveTask(file_paths=[archive], real_type="zip", is_encrypted=False)

    # Make output directory exists and is not empty
    assert config.output_dir is not None
    out_dir = config.output_dir / "test"
    out_dir.mkdir(parents=True, exist_ok=True)
    existing_file = out_dir / "existing.txt"
    existing_file.touch()

    config.overwrite_mode = "overwrite"

    mock_engine = MagicMock()
    mock_engine.extract.side_effect = lambda p, o, pw, m: (o.mkdir(parents=True, exist_ok=True), Result.ok(o))[1]
    mock_create_engine.return_value = Result.ok(mock_engine)

    extractor = Extractor(config, mock_password_mgr, mock_logger)
    
    with patch("archunpack.extractor.Scanner") as mock_scanner_cls:
        mock_scanner = MagicMock()
        mock_scanner.scan.return_value = Result.ok(MagicMock(tasks=[]))
        mock_scanner_cls.return_value = mock_scanner

        res = extractor.extract(task)
        assert res.is_ok()
        assert not existing_file.exists()  # Deleted!
        assert task.status == TaskStatus.DONE


@patch("archunpack.extractor.create_engine")
def test_extractor_overwrite_rename(
    mock_create_engine: MagicMock,
    config: Config,
    mock_password_mgr: MagicMock,
    mock_logger: MagicMock,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "src" / "test.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.touch()

    task = ArchiveTask(file_paths=[archive], real_type="zip", is_encrypted=False)

    # Make output directory exists and is not empty
    assert config.output_dir is not None
    out_dir = config.output_dir / "test"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "existing.txt").touch()

    config.overwrite_mode = "rename"

    mock_engine = MagicMock()
    mock_engine.extract.side_effect = lambda p, o, pw, m: (o.mkdir(parents=True, exist_ok=True), Result.ok(o))[1]
    mock_create_engine.return_value = Result.ok(mock_engine)

    extractor = Extractor(config, mock_password_mgr, mock_logger)
    
    with patch("archunpack.extractor.Scanner") as mock_scanner_cls:
        mock_scanner = MagicMock()
        mock_scanner.scan.return_value = Result.ok(MagicMock(tasks=[]))
        mock_scanner_cls.return_value = mock_scanner

        res = extractor.extract(task)
        assert res.is_ok()
        assert config.output_dir is not None
        assert task.output_path == config.output_dir / "test_1"  # Renamed!
        assert task.status == TaskStatus.DONE


@patch("archunpack.extractor.create_engine")
def test_extractor_nested_archives(
    mock_create_engine: MagicMock,
    config: Config,
    mock_password_mgr: MagicMock,
    mock_logger: MagicMock,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "src" / "test.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.touch()

    task = ArchiveTask(file_paths=[archive], real_type="zip", is_encrypted=False, depth=0)

    assert config.output_dir is not None
    mock_engine = MagicMock()
    mock_engine.extract.side_effect = lambda p, o, pw, m: (o.mkdir(parents=True, exist_ok=True), Result.ok(o))[1]
    mock_create_engine.return_value = Result.ok(mock_engine)

    extractor = Extractor(config, mock_password_mgr, mock_logger)

    with patch("archunpack.extractor.Scanner") as mock_scanner_cls:
        mock_scanner = MagicMock()
        assert config.output_dir is not None
        nested_task = ArchiveTask(file_paths=[config.output_dir / "test" / "inner.7z"], real_type="7z")
        mock_scanner.scan.return_value = Result.ok(MagicMock(tasks=[nested_task]))
        mock_scanner_cls.return_value = mock_scanner

        res = extractor.extract(task)
        assert res.is_ok()
        assert len(task.inner_archives) == 1
        assert task.inner_archives[0] == nested_task
        assert nested_task.depth == 1
        assert nested_task.parent_task_id == task.task_id
        mock_logger.log_nested_found.assert_called_once_with(task, 1)


@patch("archunpack.extractor.create_engine")
def test_extractor_intermediate_cleanup(
    mock_create_engine: MagicMock,
    config: Config,
    mock_password_mgr: MagicMock,
    mock_logger: MagicMock,
    tmp_path: Path,
) -> None:
    # Archive is inside the output dir because depth > 0
    archive = tmp_path / "out" / "parent" / "nested.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.touch()

    task = ArchiveTask(file_paths=[archive], real_type="zip", is_encrypted=False, depth=1)

    mock_engine = MagicMock()
    assert config.output_dir is not None
    mock_engine.extract.side_effect = lambda p, o, pw, m: (o.mkdir(parents=True, exist_ok=True), Result.ok(o))[1]
    mock_create_engine.return_value = Result.ok(mock_engine)

    extractor = Extractor(config, mock_password_mgr, mock_logger)

    with patch("archunpack.extractor.Scanner") as mock_scanner_cls:
        mock_scanner = MagicMock()
        mock_scanner.scan.return_value = Result.ok(MagicMock(tasks=[]))
        mock_scanner_cls.return_value = mock_scanner

        res = extractor.extract(task)
        assert res.is_ok()
        # Source file should be deleted since delete_intermediate=True and depth > 0
        assert not archive.exists()
