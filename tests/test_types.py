import time
import pytest
from archunpack.types import (
    TaskStatus,
    Result,
    ArchiveTask,
    PasswordInfo,
    ScanSummary,
    RunSummary,
)


def test_result_ok() -> None:
    res = Result.ok(42)
    assert res.is_ok() is True
    assert res.is_fail() is False
    assert res.unwrap() == 42


def test_result_fail() -> None:
    res: Result[int] = Result.fail("Something went wrong", "IO_ERROR")
    assert res.is_ok() is False
    assert res.is_fail() is True
    assert res.error == "Something went wrong"
    assert res.error_code == "IO_ERROR"
    assert res.data is None
    with pytest.raises(RuntimeError, match="Something went wrong"):
        res.unwrap()


def test_result_unwrap_or() -> None:
    res_ok = Result.ok(42)
    assert res_ok.unwrap_or(100) == 42

    res_fail: Result[int] = Result.fail("err")
    assert res_fail.unwrap_or(100) == 100


def test_archive_task_defaults() -> None:
    task = ArchiveTask()
    assert len(task.task_id) == 32  # uuid4 hex is 32 chars
    assert task.status == TaskStatus.PENDING
    assert task.created_at > 0.0
    assert task.created_at <= time.time()
    assert task.finished_at is None
    assert task.inner_archives == []
    assert task.file_paths == []


def test_task_status_enum() -> None:
    assert TaskStatus.PENDING.value == "pending"
    assert TaskStatus.DONE.value == "done"
    assert TaskStatus.FAILED.value == "failed"


def test_summaries_defaults() -> None:
    scan = ScanSummary()
    assert scan.total_files == 0
    assert scan.type_distribution == {}
    assert scan.tasks == []

    run = RunSummary()
    assert run.total_tasks == 0
    assert run.success_count == 0
    assert run.failed_tasks == []


def test_password_info_defaults() -> None:
    pw = PasswordInfo(text="secret")
    assert pw.text == "secret"
    assert pw.hit_count == 0
    assert pw.last_hit_at == 0.0
