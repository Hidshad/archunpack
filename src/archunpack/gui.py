import os
import queue
import threading
import time
from pathlib import Path
from typing import Any
import tkinter as tk
from tkinter import filedialog, ttk, scrolledtext

from .config import Config
from .logger import AppLogger
from .password_mgr import PasswordManager
from .scanner import Scanner
from .extractor import Extractor
from .task_queue import TaskQueue
from .types import ArchiveTask, Result


class ArchiveUnpackerGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("archunpack - 批量解压与密码尝试工具")
        self.root.geometry("900x700")
        self.root.minsize(800, 600)

        # 线程安全的消息队列
        self.log_msg_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.stat_update_queue: queue.Queue[dict[str, Any]] = queue.Queue()

        self.background_thread: threading.Thread | None = None
        self.task_queue: TaskQueue | None = None
        self.logger: AppLogger | None = None

        # 界面样式配置 (高级暗黑配色系统)
        self.setup_styles()
        # 构建 UI
        self.create_widgets()
        # 开启定时轮询更新界面
        self.poll_queues()

    def setup_styles(self) -> None:
        # 统一样式系统
        style = ttk.Style()
        style.theme_use("clam")

        # 配色定义
        self.bg_dark = "#1e1e1e"
        self.bg_card = "#2d2d2d"
        self.fg_white = "#e0e0e0"
        self.fg_grey = "#a0a0a0"
        self.accent_blue = "#0a5c91"
        self.accent_green = "#2e7d32"
        self.accent_red = "#b71c1c"

        # 配置背景色
        self.root.configure(bg=self.bg_dark)

        # 框架与文本样式自定义
        style.configure("TFrame", background=self.bg_dark)
        style.configure("Card.TFrame", background=self.bg_card, relief="flat")
        style.configure("TLabel", background=self.bg_dark, foreground=self.fg_white, font=("Segoe UI", 9))
        style.configure("Card.TLabel", background=self.bg_card, foreground=self.fg_white, font=("Segoe UI", 9))
        style.configure("Header.TLabel", background=self.bg_card, foreground=self.fg_white, font=("Segoe UI", 11, "bold"))
        style.configure("Title.TLabel", background=self.bg_dark, foreground=self.fg_white, font=("Segoe UI", 16, "bold"))

        # 输入框和按钮样式
        style.configure("TEntry", fieldbackground=self.bg_card, foreground=self.fg_white, bordercolor="#444444")
        style.configure("TButton", background="#3c3c3c", foreground=self.fg_white, bordercolor="#444444", padding=6, font=("Segoe UI", 9))
        style.map("TButton", background=[("active", "#4c4c4c")])

        # 特色按钮样式
        style.configure("Primary.TButton", background=self.accent_blue, foreground=self.fg_white, font=("Segoe UI", 9, "bold"))
        style.map("Primary.TButton", background=[("active", "#1274b0")])

        style.configure("Stop.TButton", background=self.accent_red, foreground=self.fg_white, font=("Segoe UI", 9, "bold"))
        style.map("Stop.TButton", background=[("active", "#d32f2f")])

        # 进度条样式
        style.configure("Horizontal.TProgressbar", thickness=15, troughcolor="#2d2d2d", background=self.accent_blue)

    def create_widgets(self) -> None:
        # 主布局容器
        main_container = ttk.Frame(self.root, style="TFrame")
        main_container.pack(fill="both", expand=True, padx=15, pady=15)

        # 1. 顶部标题和环境检测
        header_frame = ttk.Frame(main_container, style="TFrame")
        header_frame.pack(fill="x", pady=(0, 10))
        
        title_label = ttk.Label(header_frame, text="archunpack 批量解压大师", style="Title.TLabel")
        title_label.pack(side="left")

        # 环境检测 (7-Zip & WinRAR)
        env_frame = ttk.Frame(header_frame, style="TFrame")
        env_frame.pack(side="right")

        has_7z = Config.detect_7zip() is not None
        has_rar = Config.detect_winrar() is not None

        label_7z_color = "#4caf50" if has_7z else "#f44336"
        label_7z_text = "7-Zip: 已检测" if has_7z else "7-Zip: 未检测"
        lbl_7z = tk.Label(env_frame, text=label_7z_text, fg=label_7z_color, bg=self.bg_dark, font=("Segoe UI", 9, "bold"))
        lbl_7z.pack(side="left", padx=5)

        label_rar_color = "#4caf50" if has_rar else "#f44336"
        label_rar_text = "WinRAR: 已检测" if has_rar else "WinRAR: 未检测"
        lbl_rar = tk.Label(env_frame, text=label_rar_text, fg=label_rar_color, bg=self.bg_dark, font=("Segoe UI", 9, "bold"))
        lbl_rar.pack(side="left", padx=5)

        # 2. 参数输入区 (Card 布局)
        input_card = ttk.Frame(main_container, style="Card.TFrame")
        input_card.pack(fill="x", pady=5)
        input_card.columnconfigure(1, weight=1)

        # 源文件目录
        ttk.Label(input_card, text="源文件夹/文件:", style="Card.TLabel").grid(row=0, column=0, sticky="w", padx=10, pady=8)
        self.entry_source = ttk.Entry(input_card)
        self.entry_source.grid(row=0, column=1, sticky="ew", padx=5, pady=8)
        btn_source_dir = ttk.Button(input_card, text="选择目录", command=self.browse_source_dir)
        btn_source_dir.grid(row=0, column=2, padx=5, pady=8)
        btn_source_file = ttk.Button(input_card, text="选择文件", command=self.browse_source_file)
        btn_source_file.grid(row=0, column=3, padx=(0, 10), pady=8)

        # 输出目录
        ttk.Label(input_card, text="输出目标文件夹:", style="Card.TLabel").grid(row=1, column=0, sticky="w", padx=10, pady=8)
        self.entry_output = ttk.Entry(input_card)
        self.entry_output.grid(row=1, column=1, sticky="ew", padx=5, pady=8)
        btn_output = ttk.Button(input_card, text="浏览", command=self.browse_output)
        btn_output.grid(row=1, column=2, columnspan=2, sticky="ew", padx=(5, 10), pady=8)

        # 密码字典文件
        ttk.Label(input_card, text="密码表文件 (.txt):", style="Card.TLabel").grid(row=2, column=0, sticky="w", padx=10, pady=8)
        self.entry_pwd = ttk.Entry(input_card)
        self.entry_pwd.grid(row=2, column=1, sticky="ew", padx=5, pady=8)
        btn_pwd = ttk.Button(input_card, text="浏览", command=self.browse_pwd)
        btn_pwd.grid(row=2, column=2, columnspan=2, sticky="ew", padx=(5, 10), pady=8)

        # 3. 高级控制选项
        options_frame = ttk.Frame(main_container, style="Card.TFrame")
        options_frame.pack(fill="x", pady=10, padx=5)

        self.var_overwrite_mode = tk.StringVar(master=self.root, value="skip")
        
        # 删除中间归档文件
        self.var_delete_intermediate = tk.BooleanVar(master=self.root, value=True)
        chk_del_int = ttk.Checkbutton(
            options_frame,
            text="解压嵌套压缩包后，自动删除中间文件",
            variable=self.var_delete_intermediate
        )
        chk_del_int.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 5))

        self.var_delete_source = tk.BooleanVar(master=self.root, value=False)
        chk_del_src = ttk.Checkbutton(
            options_frame,
            text="解压成功后，自动删除最外层原始压缩包（慎用）",
            variable=self.var_delete_source
        )
        chk_del_src.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 5))

        # 覆盖模式
        ttk.Label(options_frame, text="同名目录处理:").grid(row=2, column=0, sticky="w", pady=(0, 5))
        self.combo_overwrite = ttk.Combobox(options_frame, textvariable=self.var_overwrite_mode, values=["skip", "overwrite", "rename"], state="readonly", width=10)
        self.combo_overwrite.grid(row=2, column=1, sticky="w", pady=(0, 5))

        # 最大嵌套深度
        ttk.Label(options_frame, text="最大嵌套层级:").grid(row=3, column=0, sticky="w", pady=(0, 5))
        self.spin_depth = tk.Spinbox(options_frame, from_=0, to=20, width=5, bg=self.bg_card, fg=self.fg_white, buttonbackground=self.bg_card, bd=0)
        self.spin_depth.delete(0, "end")
        self.spin_depth.insert(0, "5")
        self.spin_depth.grid(row=3, column=1, sticky="w", pady=(0, 5))

        # 并发线程数
        ttk.Label(options_frame, text="并行线程数(0=自动):").grid(row=4, column=0, sticky="w", pady=(0, 5))
        self.spin_threads = tk.Spinbox(options_frame, from_=0, to=64, width=5, bg=self.bg_card, fg=self.fg_white, buttonbackground=self.bg_card, bd=0)
        self.spin_threads.delete(0, "end")
        self.spin_threads.insert(0, "0")
        self.spin_threads.grid(row=4, column=1, sticky="w", pady=(0, 5))

        # 4. 操作按钮区
        buttons_frame = ttk.Frame(main_container, style="TFrame")
        buttons_frame.pack(fill="x", pady=5)

        self.btn_scan = ttk.Button(buttons_frame, text="🔍 仅扫描分析", command=self.start_scan)
        self.btn_scan.pack(side="left", padx=5, fill="x", expand=True)

        self.btn_extract = ttk.Button(buttons_frame, text="⚡ 开始批量解压", style="Primary.TButton", command=self.start_extraction)
        self.btn_extract.pack(side="left", padx=5, fill="x", expand=True)

        self.btn_stop = ttk.Button(buttons_frame, text="🛑 强制中止", style="Stop.TButton", command=self.stop_process, state="disabled")
        self.btn_stop.pack(side="left", padx=5, fill="x", expand=True)

        # 5. 进度和可视化控制台看板
        stat_card = ttk.Frame(main_container, style="Card.TFrame")
        stat_card.pack(fill="x", pady=10)
        
        # 进度百分比与标签
        self.lbl_status = ttk.Label(stat_card, text="系统就绪：请配置源文件夹以开始。", style="Header.TLabel")
        self.lbl_status.pack(anchor="w", padx=10, pady=5)

        self.progress_bar = ttk.Progressbar(stat_card, orient="horizontal", mode="determinate", style="Horizontal.TProgressbar")
        self.progress_bar.pack(fill="x", padx=10, pady=5)

        # 指标展示看板
        indicators_frame = ttk.Frame(stat_card, style="Card.TFrame")
        indicators_frame.pack(fill="x", padx=10, pady=5)

        self.lbl_stat_total = ttk.Label(indicators_frame, text="总任务数: 0", style="Card.TLabel")
        self.lbl_stat_total.pack(side="left", padx=10, expand=True)

        self.lbl_stat_success = ttk.Label(indicators_frame, text="成功: 0", style="Card.TLabel")
        self.lbl_stat_success.pack(side="left", padx=10, expand=True)

        self.lbl_stat_failed = ttk.Label(indicators_frame, text="失败: 0", style="Card.TLabel")
        self.lbl_stat_failed.pack(side="left", padx=10, expand=True)

        self.lbl_stat_skipped = ttk.Label(indicators_frame, text="跳过: 0", style="Card.TLabel")
        self.lbl_stat_skipped.pack(side="left", padx=10, expand=True)

        # 6. scrolling 日志显示区 (带日志色彩标记)
        log_frame = ttk.Frame(main_container, style="TFrame")
        log_frame.pack(fill="both", expand=True, pady=(5, 0))

        ttk.Label(log_frame, text="实时运行控制台日志:", style="TLabel").pack(anchor="w", pady=2)
        
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            wrap="word",
            bg="#121212",
            fg="#cccccc",
            insertbackground="#ffffff",
            selectbackground="#444444",
            font=("Consolas", 10),
            state="disabled",
        )
        self.log_text.pack(fill="both", expand=True)

        # 配置日志颜色标签
        self.log_text.tag_config("DEBUG", foreground="#808080")
        self.log_text.tag_config("INFO", foreground="#a5d6a7")
        self.log_text.tag_config("WARNING", foreground="#ffe082")
        self.log_text.tag_config("ERROR", foreground="#ef9a9a")

    # --- 文件选择器交互 ---
    def browse_source_dir(self) -> None:
        path = filedialog.askdirectory(title="选择源文件夹")
        if path:
            self.entry_source.delete(0, tk.END)
            self.entry_source.insert(0, os.path.normpath(path))

    def browse_source_file(self) -> None:
        path = filedialog.askopenfilename(
            title="选择压缩归档文件",
            filetypes=[("支持的压缩文件", "*.7z;*.zip;*.rar;*.tar;*.tar.gz;*.tar.bz2;*.tar.xz;*.tgz;*.tbz2;*.txz"), ("全部文件", "*.*")]
        )
        if path:
            self.entry_source.delete(0, tk.END)
            self.entry_source.insert(0, os.path.normpath(path))

    def browse_output(self) -> None:
        path = filedialog.askdirectory(title="选择输出文件夹")
        if path:
            self.entry_output.delete(0, tk.END)
            self.entry_output.insert(0, os.path.normpath(path))

    def browse_pwd(self) -> None:
        path = filedialog.askopenfilename(
            title="选择密码文件",
            filetypes=[("文本文件", "*.txt"), ("全部文件", "*.*")]
        )
        if path:
            self.entry_pwd.delete(0, tk.END)
            self.entry_pwd.insert(0, os.path.normpath(path))

    # --- 控制台日志与统计输出接口 (线程安全) ---
    def queue_log(self, level: str, message: str) -> None:
        self.log_msg_queue.put((level, message))

    def queue_stats(self, **kwargs: Any) -> None:
        self.stat_update_queue.put(kwargs)

    # --- 定时轮询器 ---
    def poll_queues(self) -> None:
        # 1. 刷新日志窗口
        while not self.log_msg_queue.empty():
            try:
                level, msg = self.log_msg_queue.get_nowait()
                self.append_log_line(level, msg)
            except queue.Empty:
                break

        # 2. 刷新统计看板
        while not self.stat_update_queue.empty():
            try:
                stats = self.stat_update_queue.get_nowait()
                if "status" in stats:
                    self.lbl_status.config(text=stats["status"])
                if "total" in stats:
                    self.lbl_stat_total.config(text=f"总任务数: {stats['total']}")
                if "success" in stats:
                    self.lbl_stat_success.config(text=f"成功: {stats['success']}")
                if "failed" in stats:
                    self.lbl_stat_failed.config(text=f"失败: {stats['failed']}")
                if "skipped" in stats:
                    self.lbl_stat_skipped.config(text=f"跳过: {stats['skipped']}")
                if "progress" in stats:
                    self.progress_bar["value"] = stats["progress"]
            except queue.Empty:
                break

        # 周期调用 (每 100ms 一次)
        self.root.after(100, self.poll_queues)

    def append_log_line(self, level: str, text: str) -> None:
        self.log_text.config(state="normal")
        # 插入时间戳和等级前缀
        ts = time.strftime("%H:%M:%S")
        prefix = f"[{ts}] [{level}] "
        self.log_text.insert(tk.END, prefix, level)
        # 插入日志主体并滚动到底部
        self.log_text.insert(tk.END, text + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")

    # --- 流程控制 ---
    def start_scan(self) -> None:
        src = self.entry_source.get().strip()
        if not src:
            self.append_log_line("ERROR", "请输入源归档文件或目录路径！")
            return

        self.set_ui_state("running")
        self.queue_stats(status="正在扫描分析中...")

        self.background_thread = threading.Thread(
            target=self.async_scan_flow,
            args=(src,),
            daemon=True,
        )
        self.background_thread.start()

    def start_extraction(self) -> None:
        src = self.entry_source.get().strip()
        out = self.entry_output.get().strip()
        pwd = self.entry_pwd.get().strip()

        if not src or not out:
            self.append_log_line("ERROR", "请输入完整的源文件路径与输出目录路径！")
            return

        self.set_ui_state("running")
        self.queue_stats(status="正在批量解压处理中...", progress=0)

        # 读取 spinbox/combo 选项
        try:
            threads = int(self.spin_threads.get())
        except ValueError:
            threads = 0

        try:
            depth = int(self.spin_depth.get())
        except ValueError:
            depth = 5

        overwrite = self.combo_overwrite.get()
        delete_inter = self.var_delete_intermediate.get()
        delete_src = self.var_delete_source.get()

        self.background_thread = threading.Thread(
            target=self.async_extraction_flow,
            args=(src, out, pwd, threads, depth, overwrite, delete_inter, delete_src),
            daemon=True,
        )
        self.background_thread.start()

    def stop_process(self) -> None:
        if self.task_queue:
            self.queue_log("WARNING", "正在接收中止指令，正在清理任务管道...")
            self.task_queue.force_stop()
            self.btn_stop.config(state="disabled")

    def set_ui_state(self, state: str) -> None:
        if state == "running":
            self.btn_scan.config(state="disabled")
            self.btn_extract.config(state="disabled")
            self.btn_stop.config(state="normal")
        else:
            self.btn_scan.config(state="normal")
            self.btn_extract.config(state="normal")
            self.btn_stop.config(state="disabled")

    # --- 异步工作线程流程 ---
    def async_scan_flow(self, src: str) -> None:
        try:
            config = Config(source_dir=Path(src))
            scanner = Scanner(config)
            
            self.queue_log("INFO", f"开始扫描 {src} ...")
            res = scanner.scan(Path(src))
            if res.is_ok():
                sum_obj = res.unwrap()
                self.queue_log("INFO", f"扫描成功！共发现 {len(sum_obj.tasks)} 个有效解压归档任务。")
                self.queue_log("INFO", f"总文件数: {sum_obj.total_files} | 归档总容量: {sum_obj.total_size_bytes} 字节。")
                self.queue_stats(
                    status="分析完成",
                    total=len(sum_obj.tasks),
                    success=0,
                    failed=0,
                    skipped=0,
                    progress=0,
                )
            else:
                self.queue_log("ERROR", f"扫描失败: {res.error}")
                self.queue_stats(status="扫描出错")
        except Exception as e:
            self.queue_log("ERROR", f"扫描过程中发生系统异常: {e}")
            self.queue_stats(status="扫描出错")
        finally:
            self.root.after(0, lambda: self.set_ui_state("idle"))

    def async_extraction_flow(
        self,
        src: str,
        out: str,
        pwd: str,
        threads: int,
        depth: int,
        overwrite: str,
        delete_inter: bool,
        delete_src: bool,
    ) -> None:
        try:
            # 1. 组装运行 Config
            config = Config(
                source_dir=Path(src),
                output_dir=Path(out),
                password_file=Path(pwd) if pwd else None,
                max_depth=depth,
                delete_intermediate=delete_inter,
                delete_source=delete_src,
                overwrite_mode=overwrite,
                max_parallel=threads,
            )

            # 2. 初始化 Logger，将日志定向到 GUI 实时控制台
            self.logger = AppLogger(config)
            
            # 自定义 logger 的回调以安全输出到 GUI
            def gui_log_cb(level: str, msg: str) -> None:
                # 过滤掉不需要明文展示的日志密码
                self.queue_log(level, msg)

            self.logger.add_callback(gui_log_cb)
            self.logger.setup()

            password_mgr = PasswordManager(config)
            self.queue_log("INFO", f"成功装载 {len(password_mgr)} 个字典密码。")

            # 3. 扫描任务
            self.queue_log("INFO", "启动预解压扫描...")
            scanner = Scanner(config)
            scan_res = scanner.scan(Path(src))
            if scan_res.is_fail():
                self.queue_log("ERROR", f"预扫描失败: {scan_res.error}")
                self.queue_stats(status="预扫描出错")
                return

            summary = scan_res.unwrap()
            self.queue_log("INFO", f"扫描完成：识别到 {len(summary.tasks)} 个基础压缩包。")
            if not summary.tasks:
                self.queue_log("WARNING", "没有找到可以被解压的有效文件。")
                self.queue_stats(status="无有效压缩包")
                return

            # 4. 创建 Extractor 与多线程 TaskQueue
            extractor = Extractor(config, password_mgr, self.logger)
            self.task_queue = TaskQueue(config, extractor.extract)
            extractor.is_cancelled = self.task_queue._force_stop_event.is_set

            # 统计计数器 (用于平滑更新百分比)
            stats_lock = threading.Lock()
            total_tasks_counter = len(summary.tasks)
            completed_counter = 0

            # 绑定 Queue 回调以计算百分比
            def on_task_complete(task: ArchiveTask, res: Result[ArchiveTask]) -> None:
                nonlocal completed_counter, total_tasks_counter
                with stats_lock:
                    completed_counter += 1
                    # 动态加上解压嵌套产生的子任务数
                    if res.is_ok() and task.inner_archives:
                        total_tasks_counter += len(task.inner_archives)

                    # 计算总进度百分比
                    pct = int((completed_counter / total_tasks_counter) * 100) if total_tasks_counter > 0 else 100
                    
                    # 获取实时运行统计
                    assert self.logger is not None
                    run_sum = self.logger.get_run_summary()
                    self.queue_stats(
                        total=total_tasks_counter,
                        success=run_sum.success_count,
                        failed=run_sum.failed_count + run_sum.error_count,
                        skipped=run_sum.skipped_count,
                        progress=pct,
                    )

            self.task_queue.on_task_complete = on_task_complete

            # 装载任务并运行
            for t in summary.tasks:
                self.task_queue.add_task(t)

            self.queue_stats(
                total=total_tasks_counter,
                success=0,
                failed=0,
                skipped=0,
                progress=0,
            )

            self.queue_log("INFO", "开启多线程并发引擎调度...")
            self.task_queue.start()

            # 等待所有任务以及衍生出的嵌套压缩包解压完成
            self.task_queue.join()

            # 保存热点密码
            if config.password_file and len(password_mgr) > 0:
                password_mgr.save_hot_passwords()

            run_sum = self.logger.get_run_summary()
            self.queue_log("INFO", "批量解压流程完美结束！")
            self.queue_log("INFO", f"运行结果：成功 {run_sum.success_count} | 失败 {run_sum.failed_count} | 出错 {run_sum.error_count} | 跳过 {run_sum.skipped_count}")
            self.queue_stats(status="批量解压成功完成！", progress=100)

        except Exception as e:
            self.queue_log("ERROR", f"解压引擎执行失败: {e}")
            self.queue_stats(status="解压出错")
        finally:
            if self.logger:
                self.logger.close()
            self.root.after(0, lambda: self.set_ui_state("idle"))


def main() -> None:
    root = tk.Tk()
    _app = ArchiveUnpackerGUI(root)
    
    # 窗口居中显示
    root.update_idletasks()
    width = root.winfo_width()
    height = root.winfo_height()
    x = (root.winfo_screenwidth() // 2) - (width // 2)
    y = (root.winfo_screenheight() // 2) - (height // 2)
    root.geometry(f"{width}x{height}+{x}+{y}")
    
    root.mainloop()


if __name__ == "__main__":
    main()
