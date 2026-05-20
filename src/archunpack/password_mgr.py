import datetime
import threading
from pathlib import Path
from typing import Iterator
from .config import Config
from .types import Result, PasswordInfo


class PasswordManager:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.passwords: dict[str, PasswordInfo] = {}
        self.lock = threading.Lock()

        # If password file is configured, load it automatically
        if config.password_file and config.password_file.exists():
            self.load_from_file(config.password_file)
            
            # Also try to load hot passwords if they exist
            hot_file = config.password_file.parent / f"{config.password_file.name}.hot"
            if hot_file.exists():
                self.load_hot_passwords(hot_file)

    def load_from_file(self, file_path: Path) -> Result[int]:
        """从明文 txt 加载密码，每行一个，跳过空行和 # 注释行。返回：成功加载的密码数量"""
        try:
            if not file_path.exists():
                return Result.fail(f"Password file {file_path} does not exist", "FILE_NOT_FOUND")

            count = 0
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    stripped = line.strip("\r\n")
                    if not stripped.strip() or stripped.startswith("#"):
                        continue
                    self.add_password(stripped)
                    count += 1
            return Result.ok(count)
        except Exception as e:
            return Result.fail(f"Failed to load passwords: {e}", "IO_ERROR")

    def add_password(self, text: str) -> None:
        """运行时动态添加密码（如用户输入）"""
        with self.lock:
            if text not in self.passwords:
                self.passwords[text] = PasswordInfo(text=text)

    def record_hit(self, password: str) -> None:
        """记录密码命中：递增 hit_count，更新时间戳"""
        with self.lock:
            import time
            if password not in self.passwords:
                self.passwords[password] = PasswordInfo(text=password)
            info = self.passwords[password]
            info.hit_count += 1
            info.last_hit_at = time.time()

    def get_ordered_passwords(self) -> list[str]:
        """
        按热点排序返回密码文本：
        排序键 = (last_hit_at desc, hit_count desc)
        从未命中的排在最后
        """
        with self.lock:
            # Sort function: hit passwords (last_hit_at > 0.0) first,
            # then sorted by last_hit_at desc, then hit_count desc.
            # Stable sort ensures insertion order is kept for unhit passwords.
            items = list(self.passwords.values())
            items.sort(
                key=lambda x: (0 if x.last_hit_at > 0.0 else 1, -x.last_hit_at, -x.hit_count)
            )
            return [x.text for x in items]

    def save_hot_passwords(self) -> Result[Path]:
        """
        持久化热点信息到 {password_file}.hot
        格式: ISO时间戳\t密码（每行）
        未命中的密码也保存（时间戳=epoch）
        """
        try:
            if not self.config.password_file:
                return Result.fail("Password file not configured in config", "NO_FILE_CONFIG")

            hot_file = self.config.password_file.parent / f"{self.config.password_file.name}.hot"
            
            with self.lock:
                # Sort passwords first so they are written in order
                items = list(self.passwords.values())
                items.sort(
                    key=lambda x: (0 if x.last_hit_at > 0.0 else 1, -x.last_hit_at, -x.hit_count)
                )

                with open(hot_file, "w", encoding="utf-8") as f:
                    for item in items:
                        if item.last_hit_at > 0.0:
                            dt = datetime.datetime.fromtimestamp(
                                item.last_hit_at, datetime.timezone.utc
                            )
                            iso_str = dt.isoformat().replace("+00:00", "Z")
                        else:
                            iso_str = "1970-01-01T00:00:00Z"
                        f.write(f"{iso_str}\t{item.text}\n")

            return Result.ok(hot_file)
        except Exception as e:
            return Result.fail(f"Failed to save hot passwords: {e}", "IO_ERROR")

    def load_hot_passwords(self, hot_file: Path) -> Result[int]:
        """加载热点文件，恢复排序"""
        try:
            if not hot_file.exists():
                return Result.fail(f"Hot passwords file {hot_file} does not exist", "FILE_NOT_FOUND")

            count = 0
            with open(hot_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip("\n")
                    if not line:
                        continue
                    parts = line.split("\t", 1)
                    if len(parts) == 2:
                        iso_ts, text = parts
                        
                        if iso_ts == "1970-01-01T00:00:00Z" or iso_ts.startswith("1970-01-01T00:00:00"):
                            last_hit_at = 0.0
                            hit_count = 0
                        else:
                            try:
                                # handle Z suffix
                                clean_ts = iso_ts.replace("Z", "+00:00")
                                dt = datetime.datetime.fromisoformat(clean_ts)
                                last_hit_at = dt.timestamp()
                                hit_count = 1
                            except ValueError:
                                last_hit_at = 0.0
                                hit_count = 0
                        
                        with self.lock:
                            if text in self.passwords:
                                # Update if loaded file has better hit info
                                info = self.passwords[text]
                                if last_hit_at > 0.0:
                                    info.last_hit_at = max(info.last_hit_at, last_hit_at)
                                    info.hit_count = max(info.hit_count, hit_count)
                            else:
                                self.passwords[text] = PasswordInfo(
                                    text=text, hit_count=hit_count, last_hit_at=last_hit_at
                                )
                        count += 1

            return Result.ok(count)
        except Exception as e:
            return Result.fail(f"Failed to load hot passwords: {e}", "IO_ERROR")

    def __len__(self) -> int:
        with self.lock:
            return len(self.passwords)

    def __iter__(self) -> Iterator[str]:
        # Iterates over password texts in hotness order
        return iter(self.get_ordered_passwords())
