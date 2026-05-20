import queue
import threading
from typing import Callable
from .config import Config
from .types import ArchiveTask, Result, TaskStatus


class TaskQueue:
    def __init__(
        self,
        config: Config,
        worker_fn: Callable[[ArchiveTask], Result[ArchiveTask]],
    ) -> None:
        self.config = config
        self.worker_fn = worker_fn

        self._queue: queue.Queue[ArchiveTask] = queue.Queue()
        self._workers: list[threading.Thread] = []
        self._active_count = 0
        self._running = False

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._force_stop_event = threading.Event()
        self._all_done_event = threading.Event()
        self._all_done_event.set()

        # Callbacks
        self.on_task_start: Callable[[ArchiveTask], None] | None = None
        self.on_task_complete: Callable[[ArchiveTask, Result[ArchiveTask]], None] | None = None
        self.on_queue_complete: Callable[[], None] | None = None

        # 收集所有处理过的任务，便于汇报
        self.processed_tasks: list[ArchiveTask] = []

    def add_task(self, task: ArchiveTask) -> None:
        """往队列添加任务，增加 active_count"""
        with self._lock:
            if self._stop_event.is_set() or self._force_stop_event.is_set():
                return
            self._active_count += 1
            self._all_done_event.clear()
            self._queue.put(task)

    def start(self) -> None:
        """启动工作线程"""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._stop_event.clear()
            self._force_stop_event.clear()
            
            if self._active_count > 0:
                self._all_done_event.clear()
            else:
                self._all_done_event.set()

            num_threads = self.config.max_parallel
            if num_threads <= 0:
                import os
                num_threads = min(os.cpu_count() or 4, 4)

            self._workers = []
            for i in range(num_threads):
                t = threading.Thread(
                    target=self._worker,
                    name=f"archunpack-worker-{i}",
                    daemon=True,
                )
                t.start()
                self._workers.append(t)

    def stop(self) -> None:
        """优雅停止：不再允许添加新任务，等待当前任务和子任务全部完成后退出"""
        self._stop_event.set()

    def force_stop(self) -> None:
        """强制停止：清空队列中未处理的任务，并尝试中断工作线程"""
        self._force_stop_event.set()
        self._stop_event.set()

        # 清空队列中所有未处理的任务，并修正 active_count
        while not self._queue.empty():
            try:
                task = self._queue.get_nowait()
                task.status = TaskStatus.SKIPPED
                task.status_message = "Cancelled by force stop"
                self.processed_tasks.append(task)
                self._queue.task_done()
                self._decrement_active()
            except queue.Empty:
                break

    def join(self, timeout: float | None = None) -> bool:
        """等待所有任务完成"""
        return self._all_done_event.wait(timeout=timeout)

    def is_running(self) -> bool:
        return self._running

    def _decrement_active(self) -> None:
        with self._lock:
            if self._active_count > 0:
                self._active_count -= 1
            if self._active_count == 0:
                self._all_done_event.set()
                self._running = False
                if self.on_queue_complete:
                    try:
                        self.on_queue_complete()
                    except Exception:
                        pass

    def _worker(self) -> None:
        while True:
            if self._force_stop_event.is_set():
                break

            # 优雅停机判定：当设置了 stop 且 队列已空 且 活跃计数为 0 时退出
            if self._stop_event.is_set() and self._queue.empty():
                with self._lock:
                    if self._active_count == 0:
                        break

            try:
                task = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if self._force_stop_event.is_set():
                task.status = TaskStatus.SKIPPED
                task.status_message = "Cancelled by force stop"
                self.processed_tasks.append(task)
                self._queue.task_done()
                self._decrement_active()
                continue

            # 处理任务
            try:
                self.processed_tasks.append(task)
                if self.on_task_start:
                    try:
                        self.on_task_start(task)
                    except Exception:
                        pass

                res = self.worker_fn(task)

                # 如果成功并且产生子任务，则将子任务入队
                if res.is_ok() and task.inner_archives:
                    for child in task.inner_archives:
                        self.add_task(child)

                if self.on_task_complete:
                    try:
                        self.on_task_complete(task, res)
                    except Exception:
                        pass

            except Exception as e:
                # 异常保护：防止 worker_fn 抛出严重崩溃导致工作线程死掉
                task.status = TaskStatus.ERROR
                task.status_message = f"Unexpected queue thread error: {e}"
                if self.on_task_complete:
                    try:
                        self.on_task_complete(task, Result.fail(str(e), "UNKNOWN_ERROR"))
                    except Exception:
                        pass
            finally:
                self._queue.task_done()
                self._decrement_active()
