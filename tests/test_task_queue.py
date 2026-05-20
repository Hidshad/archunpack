import time
import pytest
from unittest.mock import MagicMock
from archunpack.config import Config
from archunpack.task_queue import TaskQueue
from archunpack.types import ArchiveTask, Result, TaskStatus


@pytest.fixture
def config() -> Config:
    return Config(max_parallel=2)


def test_task_queue_init(config: Config) -> None:
    worker = MagicMock()
    queue = TaskQueue(config, worker)
    assert queue.config == config
    assert queue.worker_fn == worker
    assert not queue.is_running()


def test_task_queue_execution(config: Config) -> None:
    processed = []

    def mock_worker(task: ArchiveTask) -> Result[ArchiveTask]:
        processed.append(task)
        task.status = TaskStatus.DONE
        return Result.ok(task)

    queue = TaskQueue(config, mock_worker)

    task1 = ArchiveTask(real_type="zip")
    task2 = ArchiveTask(real_type="7z")

    start_called = []
    complete_called = []

    queue.on_task_start = lambda t: start_called.append(t)
    queue.on_task_complete = lambda t, r: complete_called.append((t, r))

    queue.add_task(task1)
    queue.add_task(task2)

    queue.start()
    finished = queue.join(timeout=2.0)
    assert finished

    assert len(processed) == 2
    assert task1 in processed
    assert task2 in processed
    assert len(start_called) == 2
    assert len(complete_called) == 2


def test_task_queue_nested_dispatch(config: Config) -> None:
    processed = []

    def mock_worker(task: ArchiveTask) -> Result[ArchiveTask]:
        processed.append(task)
        if task.real_type == "parent":
            child = ArchiveTask(real_type="child")
            task.inner_archives = [child]
        task.status = TaskStatus.DONE
        return Result.ok(task)

    queue = TaskQueue(config, mock_worker)
    
    parent_task = ArchiveTask(real_type="parent")
    queue.add_task(parent_task)

    queue.on_queue_complete = MagicMock()

    queue.start()
    finished = queue.join(timeout=2.0)
    assert finished

    assert len(processed) == 2
    assert processed[0].real_type == "parent"
    assert processed[1].real_type == "child"
    assert queue.on_queue_complete.call_count == 1


def test_task_queue_graceful_stop(config: Config) -> None:
    def mock_worker(task: ArchiveTask) -> Result[ArchiveTask]:
        time.sleep(0.1)
        task.status = TaskStatus.DONE
        return Result.ok(task)

    queue = TaskQueue(config, mock_worker)
    task1 = ArchiveTask(real_type="zip")
    queue.add_task(task1)

    queue.start()
    queue.stop()

    # Once stop() is called, adding new task should be ignored
    task2 = ArchiveTask(real_type="7z")
    queue.add_task(task2)

    finished = queue.join(timeout=2.0)
    assert finished

    assert task1.status == TaskStatus.DONE
    # task2 was ignored because stop was called before add_task
    assert task2.status == TaskStatus.PENDING


def test_task_queue_force_stop() -> None:
    config_single = Config(max_parallel=1)
    def mock_worker(task: ArchiveTask) -> Result[ArchiveTask]:
        time.sleep(0.2)
        task.status = TaskStatus.DONE
        return Result.ok(task)

    queue = TaskQueue(config_single, mock_worker)
    task1 = ArchiveTask(real_type="zip")
    task2 = ArchiveTask(real_type="7z")
    queue.add_task(task1)
    queue.add_task(task2)

    queue.start()
    time.sleep(0.05)  # Let worker start processing task1

    queue.force_stop()
    finished = queue.join(timeout=2.0)
    assert finished

    assert task1.status == TaskStatus.DONE  # Already picked up
    assert task2.status == TaskStatus.SKIPPED  # Cancelled!
    assert "force stop" in task2.status_message


def test_task_queue_worker_exception(config: Config) -> None:
    def mock_worker(task: ArchiveTask) -> Result[ArchiveTask]:
        raise ValueError("Simulated crash")

    queue = TaskQueue(config, mock_worker)
    task = ArchiveTask(real_type="zip")
    queue.add_task(task)

    queue.on_task_complete = MagicMock()

    queue.start()
    finished = queue.join(timeout=2.0)
    assert finished

    assert task.status == TaskStatus.ERROR
    assert "Simulated crash" in task.status_message
    assert queue.on_task_complete.call_count == 1
