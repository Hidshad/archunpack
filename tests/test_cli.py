from pathlib import Path
from unittest.mock import MagicMock, patch

from archunpack.cli import run_cli
from archunpack.types import Result, ScanSummary, ArchiveTask, RunSummary


@patch("archunpack.cli.parse_args")
@patch("archunpack.cli.Config.from_args")
@patch("archunpack.cli.AppLogger")
@patch("archunpack.cli.PasswordManager")
@patch("archunpack.cli.Scanner")
@patch("archunpack.cli.Extractor")
@patch("archunpack.cli.TaskQueue")
def test_run_cli_success(
    mock_queue_cls: MagicMock,
    mock_extractor_cls: MagicMock,
    mock_scanner_cls: MagicMock,
    mock_password_mgr_cls: MagicMock,
    mock_logger_cls: MagicMock,
    mock_config_from_args: MagicMock,
    mock_parse_args: MagicMock,
    tmp_path: Path,
) -> None:
    # 1. Setup mock arguments
    args = MagicMock()
    args.source = str(tmp_path / "src")
    args.output = str(tmp_path / "out")
    args.password_file = str(tmp_path / "passwords.txt")
    args.max_depth = 5
    args.no_delete = False
    args.overwrite_mode = "skip"
    args.threads = 2
    args.scan_only = False
    args.failed_csv = str(tmp_path / "failed.csv")
    mock_parse_args.return_value = args

    # Ensure source directory exists to pass check
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)

    # 2. Setup config mock
    mock_config = MagicMock()
    mock_config.password_file = Path(args.password_file)
    mock_config.max_parallel = 2
    mock_config_from_args.return_value = mock_config

    # 3. Setup logger mock
    mock_logger = MagicMock()
    mock_logger.setup.return_value = Result.ok(True)
    mock_logger.export_failed_tasks.return_value = Result.ok(Path(args.failed_csv))
    mock_run_summary = RunSummary(
        total_tasks=1, success_count=1, failed_count=0, error_count=0, skipped_count=0,
        total_duration_seconds=1.5, total_extracted_bytes=1000
    )
    mock_logger.get_run_summary.return_value = mock_run_summary
    mock_logger_cls.return_value = mock_logger

    # 4. Setup password manager mock
    mock_password_mgr = MagicMock()
    mock_password_mgr.__len__.return_value = 5
    mock_password_mgr.save_hot_passwords.return_value = Result.ok(Path(args.password_file + ".hot"))
    mock_password_mgr_cls.return_value = mock_password_mgr

    # 5. Setup scanner mock
    mock_scanner = MagicMock()
    task = ArchiveTask(file_paths=[Path("src/a.zip")], real_type="zip")
    scan_summary = ScanSummary(
        root_dir=Path(args.source), total_files=1, total_size_bytes=1000,
        type_distribution={"zip": 1}, tasks=[task]
    )
    mock_scanner.scan.return_value = Result.ok(scan_summary)
    mock_scanner_cls.return_value = mock_scanner

    # 6. Setup queue mock
    mock_queue = MagicMock()
    mock_queue_cls.return_value = mock_queue

    # 7. Run CLI
    ret_code = run_cli()

    # 8. Assertions
    assert ret_code == 0
    mock_logger.setup.assert_called_once()
    mock_scanner.scan.assert_called_once_with(Path(args.source))
    mock_queue.add_task.assert_called_once_with(task)
    mock_queue.start.assert_called_once()
    mock_queue.join.assert_called_once()
    mock_password_mgr.save_hot_passwords.assert_called_once()
    mock_logger.export_failed_tasks.assert_called_once_with(Path(args.failed_csv))
    mock_logger.close.assert_called_once()


@patch("archunpack.cli.parse_args")
@patch("archunpack.cli.Config.from_args")
@patch("archunpack.cli.AppLogger")
@patch("archunpack.cli.PasswordManager")
@patch("archunpack.cli.Scanner")
def test_run_cli_scan_only(
    mock_scanner_cls: MagicMock,
    mock_password_mgr_cls: MagicMock,
    mock_logger_cls: MagicMock,
    mock_config_from_args: MagicMock,
    mock_parse_args: MagicMock,
    tmp_path: Path,
) -> None:
    # 1. Setup mock arguments
    args = MagicMock()
    args.source = str(tmp_path / "src")
    args.output = str(tmp_path / "out")
    args.password_file = None
    args.max_depth = 5
    args.no_delete = False
    args.overwrite_mode = "skip"
    args.threads = 2
    args.scan_only = True
    args.failed_csv = None
    mock_parse_args.return_value = args

    (tmp_path / "src").mkdir(parents=True, exist_ok=True)

    # 2. Setup config mock
    mock_config = MagicMock()
    mock_config.password_file = None
    mock_config_from_args.return_value = mock_config

    # 3. Setup logger mock
    mock_logger = MagicMock()
    mock_logger.setup.return_value = Result.ok(True)
    mock_logger_cls.return_value = mock_logger

    # 4. Setup scanner mock
    mock_scanner = MagicMock()
    scan_summary = ScanSummary(
        root_dir=Path(args.source), total_files=1, total_size_bytes=1000,
        type_distribution={"zip": 1}, tasks=[]
    )
    mock_scanner.scan.return_value = Result.ok(scan_summary)
    mock_scanner_cls.return_value = mock_scanner

    # 5. Run CLI
    ret_code = run_cli()

    # 6. Assertions
    assert ret_code == 0
    mock_scanner.scan.assert_called_once_with(Path(args.source))
    # In scan_only mode, we should exit before initializing Extractor or TaskQueue
    mock_logger.close.assert_called_once()
