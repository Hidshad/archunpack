from pathlib import Path
from archunpack.config import Config
from archunpack.logger import AppLogger
from archunpack.types import ArchiveTask, TaskStatus


def test_logger_setup_and_write(tmp_path: Path) -> None:
    # 1 & 2. Setup and verify log writing
    log_dir = tmp_path / "logs"
    config = Config(log_dir=log_dir)
    logger = AppLogger(config)
    
    res = logger.setup()
    assert res.is_ok()
    assert logger.log_file.exists()

    logger.info("Test info message")
    logger.error("Test error message")
    logger.close()

    content = logger.log_file.read_text(encoding="utf-8")
    assert "Test info message" in content
    assert "Test error message" in content


def test_logger_sanitize() -> None:
    # 3. Password sanitization
    logger = AppLogger(Config())
    assert logger.sanitize("trying password secret123 now", "secret123") == "trying password *** now"
    assert logger.sanitize("no password used", None) == "no password used"


def test_logger_callbacks() -> None:
    # 7. Callbacks triggered
    logger = AppLogger(Config())
    logs = []

    def cb(level: str, msg: str) -> None:
        logs.append((level, msg))

    logger.add_callback(cb)
    logger.info("Hello Callback")
    
    assert len(logs) == 1
    assert logs[0] == ("INFO", "Hello Callback")


def test_logger_business_logs() -> None:
    # 6. Task done/fail formatting and statistics
    logger = AppLogger(Config())
    task = ArchiveTask(file_paths=[Path("test.zip")], total_size_bytes=100)
    
    logger.log_task_start(task)
    logger.log_task_done(task, 120)
    
    assert len(logger.success_tasks) == 1
    assert logger.success_tasks[0] is task

    task_fail = ArchiveTask(file_paths=[Path("fail.7z")], status=TaskStatus.FAILED)
    logger.log_task_fail(task_fail, "Wrong password")
    
    assert len(logger.failed_tasks) == 1
    assert logger.failed_tasks[0] is task_fail


def test_logger_export_load_failed_tasks(tmp_path: Path) -> None:
    # 4 & 5. CSV export and load roundtrip
    logger = AppLogger(Config())
    task = ArchiveTask(
        task_id="t1",
        file_paths=[Path("c:/arch.7z")],
        real_type="7z",
        status=TaskStatus.FAILED,
        status_message="All passwords failed",
    )
    
    logger.log_password_attempt(task, 0, False)
    logger.log_password_attempt(task, 1, False)
    logger.failed_tasks.append(task)

    csv_file = tmp_path / "failed.csv"
    res_export = logger.export_failed_tasks(csv_file)
    assert res_export.is_ok()
    assert csv_file.exists()

    # Reconstruct with a new logger
    logger2 = AppLogger(Config())
    res_load = logger2.load_failed_tasks(csv_file)
    assert res_load.is_ok()
    loaded_tasks = res_load.unwrap()
    
    assert len(loaded_tasks) == 1
    assert loaded_tasks[0].task_id == "t1"
    assert loaded_tasks[0].file_paths == [Path("c:/arch.7z")]
    assert loaded_tasks[0].real_type == "7z"
    assert loaded_tasks[0].status_message == "All passwords failed"
    assert logger2.attempt_counts["t1"] == 2


def test_logger_run_summary() -> None:
    logger = AppLogger(Config())
    task_done = ArchiveTask(file_paths=[Path("a.zip")], total_size_bytes=50)
    task_fail = ArchiveTask(file_paths=[Path("b.zip")], status=TaskStatus.FAILED)
    task_error = ArchiveTask(file_paths=[Path("c.zip")], status=TaskStatus.ERROR)

    logger.success_tasks.append(task_done)
    logger.failed_tasks.append(task_fail)
    logger.error_tasks.append(task_error)

    summary = logger.get_run_summary()
    assert summary.total_tasks == 3
    assert summary.success_count == 1
    assert summary.failed_count == 1
    assert summary.error_count == 1
    assert summary.total_extracted_bytes == 50
