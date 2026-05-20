# Vibe Coding 启动 Prompt — 加密压缩包批量解压工具 (archunpack)

> **角色**: 主 Agent  
> **目标**: 协调多个子 Agent，按依赖顺序实现所有模块，全部通过 pytest + mypy + ruff  
> **人工参与**: 零。全程自动规划、执行、验证、修复  

---

## 1. 项目上下文

### 1.1 项目目标

构建一个 Windows 桌面工具，用 Python 批量解压加密压缩包（`.7z`/`.zip`/`.rar`/`.tar`），支持：
- 从密码表逐个尝试密码
- 嵌套压缩包自动递归解压到底
- 分卷压缩包自动合并
- 伪装后缀通过魔数识别
- tkinter GUI + CLI 双入口

### 1.2 目标环境

- Python 3.10+, Windows 10+
- 依赖: `py7zr`, `rarfile`, `pyzipper`
- 开发依赖: `pytest`, `pytest-mock`, `mypy`, `ruff`

### 1.3 项目结构

```
archunpack/
├── src/archunpack/
│   ├── __init__.py
│   ├── config.py
│   ├── types.py
│   ├── file_utils.py
│   ├── password_mgr.py
│   ├── engines/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── _7z.py
│   │   ├── _zip.py
│   │   ├── _rar.py
│   │   ├── _tar.py
│   │   └── factory.py
│   ├── scanner.py
│   ├── extractor.py
│   ├── task_queue.py
│   ├── logger.py
│   ├── gui.py
│   └── cli.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_config.py
│   ├── test_types.py
│   ├── test_file_utils.py
│   ├── test_password_mgr.py
│   ├── test_engines/
│   │   ├── __init__.py
│   │   ├── test_7z.py
│   │   ├── test_zip.py
│   │   ├── test_rar.py
│   │   └── test_tar.py
│   ├── test_scanner.py
│   ├── test_extractor.py
│   ├── test_task_queue.py
│   ├── test_logger.py
│   ├── test_cli.py
│   └── test_integration.py
├── pyproject.toml
└── README.md
```

---

## 2. 主 Agent 工作流程

### 2.1 你的职责

1. 初始化项目骨架（目录结构、pyproject.toml、conftest.py）
2. 按依赖关系分阶段生成子 Agent
3. 每个子 Agent 返回后，验证其产出通过 pytest + mypy + ruff
4. 未通过则自动将错误信息反馈给子 Agent 重试（最多 3 次）
5. 所有阶段完成后，运行集成测试
6. 最终输出质量报告

### 2.2 质量门禁（每个子 Agent 产出后强制执行）

```bash
# 1. 类型检查
mypy src/archunpack/<module>.py tests/test_<module>.py --strict

# 2. Lint
ruff check src/archunpack/<module>.py tests/test_<module>.py

# 3. 单元测试
pytest tests/test_<module>.py -v --tb=short
```

**通过标准**: 三项命令全部 exit code 0。任一失败 → 将完整错误输出反馈给子 Agent → 重试。
**重试上限**: 同一模块最多重试 3 次。3 次仍失败 → 暂停，向用户报告。

### 2.3 初始化阶段（主 Agent 自己完成，不生成子 Agent）

你需要首先创建以下文件：

**`pyproject.toml`** (项目根目录):
```toml
[project]
name = "archunpack"
version = "1.0.0"
requires-python = ">=3.10"
dependencies = ["py7zr>=0.21", "rarfile>=4.1", "pyzipper>=0.3"]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-mock>=3.12", "mypy>=1.8", "ruff>=0.3"]

[project.scripts]
archunpack = "archunpack.cli:main"
archunpack-gui = "archunpack.gui:main"

[tool.mypy]
python_version = "3.10"
strict = true
ignore_missing_imports = true

[tool.ruff]
target-version = "py310"
line-length = 100

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

**`tests/conftest.py`** (共享夹具):
```python
import pytest
from pathlib import Path

@pytest.fixture
def tmp_dir(tmp_path) -> Path:
    return tmp_path
```

**`src/archunpack/__init__.py`** 和 **`tests/__init__.py`**: 空文件。

---

## 3. 子 Agent 任务定义

每个子 Agent 必须严格按以下契约输出。子 Agent **只写代码不测试**，代码返回后由主 Agent 执行质量门禁。

---

### 阶段 1 — 可以并行（无互相依赖）

#### Task 1.1: `config.py`

**依赖**: 无  
**输出文件**: `src/archunpack/config.py`, `tests/test_config.py`

**公开接口**:

```python
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class Config:
    source_dir: Path | None = None
    output_dir: Path | None = None
    password_file: Path | None = None
    max_depth: int = 5
    delete_intermediate: bool = True
    overwrite_mode: str = "skip"          # "skip" | "overwrite" | "rename"
    max_parallel: int = 0                  # 0=自动
    log_dir: Path = field(default_factory=lambda: Path("./logs"))
    log_level: str = "INFO"
    skip_extensions: list[str] = field(default_factory=lambda: [
        ".mp4", ".mkv", ".avi", ".mov", ".jpg", ".png",
        ".txt", ".html", ".url", ".apk", ".exe", ".dll"
    ])
    skip_prefixes: list[str] = field(default_factory=lambda: ["._"])
    seven_zip_path: Path | None = None      # None = 自动检测
    winrar_path: Path | None = None

    @staticmethod
    def detect_7zip() -> Path | None: ...
    @staticmethod
    def detect_winrar() -> Path | None: ...
    @classmethod
    def from_args(cls, **kwargs) -> "Config": ...

    def ensure_dirs(self) -> None:
        """确保 log_dir 等目录存在"""
```

**测试用例清单** (pytest):
1. 默认构造：所有字段使用默认值，类型正确
2. `from_args()`：传入覆盖值，验证覆盖生效
3. `detect_7zip()`：mock `shutil.which`，验证检测逻辑
4. `detect_winrar()`：同上
5. `ensure_dirs()`：创建不存在的目录
6. overwrite_mode 仅接受 "skip"/"overwrite"/"rename"

---

#### Task 1.2: `types.py`

**依赖**: 无  
**输出文件**: `src/archunpack/types.py`, `tests/test_types.py`

**公开接口**:

```python
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Generic, TypeVar
from uuid import uuid4

T = TypeVar("T")

class TaskStatus(Enum):
    PENDING = "pending"
    SCANNING = "scanning"
    TRYING_PWD = "trying_pwd"
    EXTRACTING = "extracting"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"
    ERROR = "error"

@dataclass
class Result(Generic[T]):
    success: bool
    data: T | None = None
    error: str | None = None
    error_code: str | None = None  # "PASSWORD_FAIL" | "ENGINE_UNAVAILABLE" | "IO_ERROR" ...

    @staticmethod
    def ok(data: T) -> "Result[T]": ...
    @staticmethod
    def fail(error: str, code: str = "UNKNOWN") -> "Result[T]": ...
    def is_ok(self) -> bool: ...
    def is_fail(self) -> bool: ...
    def unwrap(self) -> T: ...       # 失败时 raise RuntimeError
    def unwrap_or(self, default: T) -> T: ...

@dataclass
class ArchiveTask:
    task_id: str = field(default_factory=lambda: uuid4().hex)
    file_paths: list[Path] = field(default_factory=list)   # 单文件列表1个元素，分卷多个
    real_type: str = ""                                      # "7z" | "zip" | "rar" | "tar" ...
    declared_ext: str = ""
    is_encrypted: bool | None = None
    total_size_bytes: int = 0
    depth: int = 0
    parent_task_id: str | None = None
    password: str | None = None
    status: TaskStatus = TaskStatus.PENDING
    status_message: str = ""
    output_path: Path | None = None
    inner_archives: list[Path] = field(default_factory=list)
    created_at: float = 0.0
    finished_at: float | None = None

@dataclass
class PasswordInfo:
    text: str
    hit_count: int = 0
    last_hit_at: float = 0.0           # 0=从未命中

@dataclass
class ScanSummary:
    root_dir: Path | None = None
    total_files: int = 0
    total_size_bytes: int = 0
    type_distribution: dict[str, int] = field(default_factory=dict)
    tasks: list["ArchiveTask"] = field(default_factory=list)
    ignored_count: int = 0
    ignored_files: list[str] = field(default_factory=list)

@dataclass
class RunSummary:
    total_tasks: int = 0
    success_count: int = 0
    failed_count: int = 0
    error_count: int = 0
    skipped_count: int = 0
    total_duration_seconds: float = 0.0
    total_extracted_bytes: int = 0
    failed_tasks: list["ArchiveTask"] = field(default_factory=list)
    error_tasks: list["ArchiveTask"] = field(default_factory=list)
```

**实现约束**:
- `Result.fail()` 的 `data` 参数必须设置为 `None`（ignore type override，以 `error` 字段为准）
- `ArchiveTask` 支持 `__post_init__` 自动填充 `created_at`（如果为 0）

**测试用例清单**:
1. `Result.ok(42)` → `.is_ok()` True, `.unwrap()` 返回 42
2. `Result.fail("err", "CODE")` → `.is_fail()` True, `.unwrap()` 抛异常
3. `Result.unwrap_or(val)` 失败时返回默认值
4. `ArchiveTask` 默认构造 → task_id 自动生成，status=PENDING
5. `TaskStatus` 枚举值正确
6. `ScanSummary` / `RunSummary` 默认值正确
7. `PasswordInfo` 默认 hit_count=0, last_hit_at=0

---

### 阶段 2 — 并行（依赖阶段 1）

#### Task 2.1: `file_utils.py`

**依赖**: `types.py`, `config.py`  
**输出文件**: `src/archunpack/file_utils.py`, `tests/test_file_utils.py`

**公开接口**:

```python
from pathlib import Path
from .types import Result
from .config import Config

# 魔数签名表（模块级常量）
MAGIC_SIGNATURES: dict[str, tuple[bytes, int]] = {
    "7z":      (b"\x37\x7A\xBC\xAF\x27\x1C", 0),
    "zip":     (b"\x50\x4B\x03\x04", 0),
    "rar4":    (b"\x52\x61\x72\x21\x1A\x07\x00", 0),
    "rar5":    (b"\x52\x61\x72\x21\x1A\x07\x01\x00", 0),
    "gz":      (b"\x1F\x8B", 0),
    "bz2":     (b"\x42\x5A\x68", 0),
    "xz":      (b"\xFD\x37\x7A\x58\x5A\x00", 0),
    "tar":     (b"\x75\x73\x74\x61\x72", 257),
}

def identify_type(file_path: Path) -> Result[str]:
    """
    读取文件头 512 字节，匹配魔数签名。
    匹配顺序: 7z > zip > rar5 > rar4 > gz > bz2 > xz > tar
    tar 特殊处理：如果已匹配 gz/bz2/xz，合并为 "tar.gz"/"tar.bz2"/"tar.xz"
    """

def normalize_type(raw_type: str) -> str:
    """rar4/rar5 → rar, gz → tar.gz (如果上层已是 tar)"""

def is_skippable(file_path: Path, config: Config) -> bool:
    """扩展名在黑名单 或 文件名以 ._ 开头"""

def detect_encryption(archive_path: Path, archive_type: str) -> Result[bool]:
    """
    轻量检测是否加密：
    - 7z: py7zr.SevenZipFile(archive).needs_password()
    - zip: zipfile.ZipFile(archive).infolist()[0].flag_bits & 0x1
    - rar: rarfile.RarFile(archive).needs_password()
    - tar: 始终返回 False
    注意: tar.gz/bz2/xz 为 False
    """

def find_archive_files(root: Path, config: Config) -> list[Path]:
    """递归遍历 root，跳过 is_skippable 的文件，返回文件路径列表"""

def group_split_volumes(files: list[Path]) -> dict[str, list[Path]]:
    """
    分卷分组规则：
    - 正则: r'(.+)\.(\d{3})$' 或 r'(.+)\.(z\d{2})$'
    - 同名前缀且数字连续 → 分为一组
    - 组内按数字升序排序
    - 返回 {group_key: [Path, ...]}
    """

def ensure_output_path(source_path: Path, source_root: Path, output_root: Path) -> Path:
    """镜像结构: source_root/a/b/file.7z → output_root/a/b/file/"""

def safe_delete(path: Path, allowed_root: Path) -> Result[bool]:
    """安全删除，确保路径在 allowed_root 范围内，防止误删"""

def detect_archive_type_from_path(file_path: Path) -> str | None:
    """纯扩展名检测（用于魔数识别失败时的回退）"""
```

**实现约束**:
- `identify_type()` 必须正确处理大端/小端字节序
- `group_split_volumes()` 对无分卷的单文件返回 key=完整文件名
- `find_archive_files()` 使用 `os.walk` 并错误容忍（单个文件读取失败不中断扫描）

**测试用例清单**:
1. `identify_type()` 7z 文件头识别
2. `identify_type()` zip 文件头识别（含 .CAD 伪装测试）
3. `identify_type()` rar5 识别
4. `identify_type()` tar 识别（构造含 ustar 签名的文件）
5. `identify_type()` 未知文件返回 Result.fail
6. `is_skippable()` 黑名单扩展名跳过
7. `is_skippable()` ._ 前缀跳过
8. `group_split_volumes()` 标准分卷分组
9. `group_split_volumes()` 缺号检测+日志警告
10. `group_split_volumes()` 无分卷单文件
11. `ensure_output_path()` 镜像路径计算
12. `safe_delete()` 范围内删除 vs 范围外阻止
13. `find_archive_files()` 递归遍历+过滤
14. `detect_encryption()` mock py7zr/zipfile/rarfile 各返回 True/False

---

#### Task 2.2: `password_mgr.py`

**依赖**: `types.py`, `config.py`  
**输出文件**: `src/archunpack/password_mgr.py`, `tests/test_password_mgr.py`

**公开接口**:

```python
from pathlib import Path
from .types import Result, PasswordInfo
from .config import Config

class PasswordManager:
    def __init__(self, config: Config): ...

    def load_from_file(self, file_path: Path) -> Result[int]:
        """从明文 txt 加载密码，每行一个，跳过空行和 # 注释行。返回：成功加载的密码数量"""

    def add_password(self, text: str) -> None:
        """运行时动态添加密码（如用户输入）"""

    def record_hit(self, password: str) -> None:
        """记录密码命中：递增 hit_count，更新时间戳"""

    def get_ordered_passwords(self) -> list[str]:
        """
        按热点排序返回密码文本：
        排序键 = (last_hit_at desc, hit_count desc)
        从未命中的排在最后
        """

    def save_hot_passwords(self) -> Result[Path]:
        """
        持久化热点信息到 {password_file}.hot
        格式: ISO时间戳\t密码（每行）
        未命中的密码也保存（时间戳=epoch）
        """

    def load_hot_passwords(self, hot_file: Path) -> Result[int]:
        """加载热点文件，恢复排序"""

    def __len__(self) -> int: ...

    def __iter__(self): ...
```

**实现约束**:
- `PasswordManager` 不包含任何文件解压逻辑
- `record_hit()` 线程安全（使用 `threading.Lock`）
- 密码文本保留原始大小写和空格
- 注释行以 `#` 开头

**测试用例清单**:
1. `load_from_file()` 正常加载 5 个密码，返回 count=5
2. `load_from_file()` 空行和 # 注释行被跳过
3. `load_from_file()` 文件不存在返回 Result.fail
4. `add_password()` 动态添加
5. `record_hit()` 后 `get_ordered_passwords()` 中该密码排第一
6. `get_ordered_passwords()` 从未命中的密码排在末尾
7. 多次 `record_hit()` 后排序验证
8. `save/load_hot_passwords()` 往返一致性
9. `__len__` 和 `__iter__` 行为正确
10. 线程安全：10 个线程并发 `record_hit()`，最终计数正确

---

#### Task 2.3: `engines/base.py` + `engines/__init__.py` + `engines/factory.py`

**依赖**: `types.py`  
**输出文件**: 
- `src/archunpack/engines/__init__.py`（空文件）
- `src/archunpack/engines/base.py`
- `src/archunpack/engines/factory.py`
- `tests/test_engines/__init__.py`（空文件）

**`base.py` 公开接口**:

```python
from abc import ABC, abstractmethod
from pathlib import Path
from ..types import Result

class BaseEngine(ABC):
    @abstractmethod
    def extract(
        self,
        archive_paths: list[Path],   # 单文件或分卷列表
        output_dir: Path,
        password: str | None,
        overwrite_mode: str = "skip",
    ) -> Result[Path]: ...

    @abstractmethod
    def test_availability(self) -> Result[str]:
        """返回 "library" 或 "cli" 表示使用方式"""

    @staticmethod
    @abstractmethod
    def supported_format() -> str: ...
```

**`factory.py` 公开接口**:

```python
from ..types import Result
from .base import BaseEngine

ENGINE_REGISTRY: dict[str, type[BaseEngine]]  # 模块级注册表，初始化时为空

def register_engine(format_name: str, engine_cls: type[BaseEngine]) -> None:
    """注册引擎到 ENGINE_REGISTRY"""

def create_engine(archive_type: str) -> Result[BaseEngine]:
    """根据类型字符串创建引擎实例，并调用 test_availability()"""

def check_all_available() -> dict[str, str]:
    """遍历注册表，返回 {format: "library"|"cli"|"unavailable"}"""
```

**实现约束**:
- `factory.py` 的 `ENGINE_REGISTRY` 初始为空，各引擎文件在模块底部调用 `register_engine()` 自注册
- `create_engine()` 如果类型不在注册表中，返回 `Result.fail("no engine for type X")`

**测试用例清单**:
1. `BaseEngine` 不能直接实例化（ABC）
2. 子类缺少 `extract` 或 `test_availability` → TypeError
3. `register_engine()` + `create_engine()` 正向流程
4. `create_engine()` 未知类型 → Result.fail
5. `check_all_available()` 返回注册表状态

---

### 阶段 3 — 并行（依赖阶段 2.3）

#### Task 3.1: `engines/_7z.py`

**依赖**: `engines/base.py`, `engines/factory.py`, `types.py`  
**输出文件**: `src/archunpack/engines/_7z.py`, `tests/test_engines/test_7z.py`

**公开接口**:

```python
from .base import BaseEngine
from .factory import register_engine
from ..types import Result
from pathlib import Path

class SevenZEngine(BaseEngine):
    def extract(self, archive_paths, output_dir, password, overwrite_mode="skip") -> Result[Path]:
        """
        1. 检测 py7zr 可用
        2. 可用 → py7zr.SevenZipFile(path, 'r', password=password).extractall(output_dir)
        3. py7zr 抛 Bad7zFile/PasswordRequired → 回退 7z.exe 命令行
        4. subprocess.run([7z, "x", archive, f"-p{password}", f"-o{output}", "-y"])
        5. 返回码: 0=成功, 2=密码错误(PASSWORD_FAIL), 其他=错误
        """

    def test_availability(self) -> Result[str]:
        """
        1. 尝试 import py7zr → "library"
        2. 失败 → shutil.which("7z") → "cli"
        3. 都失败 → Result.fail("ENGINE_UNAVAILABLE")
        """

    @staticmethod
    def supported_format() -> str:
        return "7z"

# 自注册
register_engine("7z", SevenZEngine)
```

**实现约束**:
- `py7zr` 的 `extractall` 需要先设置密码
- 命令行回退时用 `subprocess.run` 且 `capture_output=True`，密码不打印到日志
- 处理文件名编码：Windows 上 `subprocess` 默认 GBK，若失败尝试 UTF-8

**测试用例清单**:
1. `supported_format()` 返回 "7z"
2. `test_availability()` 检测到 py7zr → "library"
3. `test_availability()` py7zr 不可用但 7z.exe 可用 → "cli"（mock）
4. `test_availability()` 都不可用 → Result.fail
5. `extract()` 库路径成功（用临时加密 .7z 文件测试）
6. `extract()` 密码错误 → Result.fail "PASSWORD_FAIL"
7. `extract()` 库失败回退 CLI（mock py7zr 抛异常，mock subprocess 返回0）
8. `extract()` 分卷文件 → 传第一个文件路径即可
9. 注册表确认 SevenZEngine 已注册

---

#### Task 3.2: `engines/_zip.py`

**依赖**: `engines/base.py`, `engines/factory.py`, `types.py`  
**输出文件**: `src/archunpack/engines/_zip.py`, `tests/test_engines/test_zip.py`

**公开接口**:

```python
class ZipEngine(BaseEngine):
    def extract(self, archive_paths, output_dir, password, overwrite_mode="skip") -> Result[Path]:
        """
        1. 尝试 pyzipper.AESZipFile(archive, 'r')
        2. 失败 → zipfile.ZipFile(archive, 'r') + setpassword()
        3. 都失败 → 回退 7z.exe
        """

    def test_availability(self) -> Result[str]: ...

    @staticmethod
    def supported_format() -> str:
        return "zip"

register_engine("zip", ZipEngine)
```

**测试用例清单**:
1. `supported_format()` → "zip"
2. `test_availability()` 检测逻辑
3. `extract()` AES 加密 ZIP 成功
4. `extract()` ZipCrypto 加密 ZIP 成功
5. `extract()` 密码错误 → PASSWORD_FAIL
6. `extract()` 无密码 ZIP 正常解压
7. CLI 回退路径
8. 注册表确认

---

#### Task 3.3: `engines/_rar.py`

**依赖**: `engines/base.py`, `engines/factory.py`, `types.py`  
**输出文件**: `src/archunpack/engines/_rar.py`, `tests/test_engines/test_rar.py`

**公开接口**:

```python
class RarEngine(BaseEngine):
    def extract(self, archive_paths, output_dir, password, overwrite_mode="skip") -> Result[Path]:
        """
        1. 尝试 rarfile.RarFile(archive).extractall(path=output_dir, pwd=password)
        2. 失败 → 尝试 WinRAR.exe: ['WinRAR.exe', 'x', '-p'+password, archive, output]
        3. 再失败 → 尝试 7z.exe: ['7z', 'x', '-p'+password, '-o'+output, archive]
        """

    def test_availability(self) -> Result[str]: ...

    @staticmethod
    def supported_format() -> str:
        return "rar"

register_engine("rar", RarEngine)
```

**测试用例清单**:
1. `supported_format()` → "rar"
2. `test_availability()` 检测逻辑
3. `extract()` RAR5 加密成功
4. `extract()` 密码错误 → PASSWORD_FAIL
5. CLI 回退路径
6. 注册表确认

---

#### Task 3.4: `engines/_tar.py`

**依赖**: `engines/base.py`, `engines/factory.py`, `types.py`  
**输出文件**: `src/archunpack/engines/_tar.py`, `tests/test_engines/test_tar.py`

**公开接口**:

```python
class TarEngine(BaseEngine):
    def extract(self, archive_paths, output_dir, password, overwrite_mode="skip") -> Result[Path]:
        """
        tar 无加密。password 参数忽略。
        1. 根据 extension 判断压缩包装：
           - .tar → tarfile.open(archive, 'r')
           - .tar.gz → tarfile.open(archive, 'r:gz')
           - .tar.bz2 → tarfile.open(archive, 'r:bz2')
           - .tar.xz → tarfile.open(archive, 'r:xz')
        2. extractall(output_dir)
        """

    def test_availability(self) -> Result[str]:
        """tarfile 是标准库，始终返回 "library" """

    @staticmethod
    def supported_format() -> str:
        return "tar"

register_engine("tar", TarEngine)
register_engine("tar.gz", TarEngine)
register_engine("tar.bz2", TarEngine)
register_engine("tar.xz", TarEngine)
```

**测试用例清单**:
1. `supported_format()` → "tar"
2. `test_availability()` → "library"
3. `extract()` 普通 .tar
4. `extract()` .tar.gz
5. `extract()` .tar.bz2
6. `extract()` .tar.xz
7. password 参数传入忽略不影响结果
8. 四种格式均注册到 ENGINE_REGISTRY

---

### 阶段 4 — 并行（依赖阶段 1+2+3）

#### Task 4.1: `scanner.py`

**依赖**: `types.py`, `config.py`, `file_utils.py`  
**不依赖**: `engines/`, `password_mgr.py`, `extractor.py`  
**输出文件**: `src/archunpack/scanner.py`, `tests/test_scanner.py`

**公开接口**:

```python
from pathlib import Path
from .config import Config
from .types import Result, ScanSummary, ArchiveTask

class Scanner:
    def __init__(self, config: Config): ...

    def scan(self, root_dir: Path) -> Result[ScanSummary]:
        """
        1. 调用 file_utils.find_archive_files(root_dir, config) 收集文件
        2. 逐文件调用 file_utils.identify_type() 魔数识别
           - 识别失败 → 回退 file_utils.detect_archive_type_from_path()
           - 仍失败 → 跳过并记录到 ignored_files
        3. 调用 file_utils.group_split_volumes() 合并分卷
        4. 每个组构建一个 ArchiveTask:
           - task_id 自动生成
           - file_paths = 组内文件列表
           - real_type = normalize_type(识别结果)
           - depth = 0, parent_task_id = None
           - status = PENDING
           - total_size_bytes = sum(组内各文件大小)
        5. 组装 ScanSummary 返回
        """
    
    def get_last_summary(self) -> ScanSummary | None: ...
```

**实现约束**:
- 单个文件读取出错不中断扫描（记录到 ignored_files）
- 分卷组内文件缺号时发出 WARNING 级日志，但对不完整的分卷仍尝试解压（交给 extractor 处理）
- `_build_task()` 作为私有辅助方法

**测试用例清单**:
1. 扫描包含 .7z/.zip/.rar 混合目录 → 正确计数和类型分布
2. ._ 前缀文件被跳过
3. 非压缩扩展名（.mp4, .txt）被跳过，记录到 ignored_files
4. 伪装后缀 .CAD (实际zip) 被正确识别为 zip
5. 分卷文件（.001/.002/.003）合并为一个任务
6. 分卷不完整给出 WARNING
7. 无法识别的文件跳过
8. 空目录扫描 → total_files=0
9. `get_last_summary()` 返回最近一次结果

---

#### Task 4.2: `logger.py`

**依赖**: `types.py`, `config.py`  
**不依赖**: engines, password_mgr, scanner, extractor, task_queue  
**输出文件**: `src/archunpack/logger.py`, `tests/test_logger.py`

**公开接口**:

```python
import logging
from pathlib import Path
from .config import Config
from .types import ArchiveTask, RunSummary, Result

class AppLogger:
    def __init__(self, config: Config): ...

    def setup(self) -> Result[bool]:
        """创建 log 目录，配置 file_handler 和 console_handler"""

    # 标准日志
    def debug(self, msg: str): ...
    def info(self, msg: str): ...
    def warning(self, msg: str): ...
    def error(self, msg: str): ...

    # 业务日志
    def log_task_start(self, task: ArchiveTask): ...
    def log_task_done(self, task: ArchiveTask, duration_ms: int): ...
    def log_task_fail(self, task: ArchiveTask, reason: str): ...
    def log_password_attempt(self, task: ArchiveTask, pwd_idx: int, success: bool): ...
    def log_type_mismatch(self, path: Path, declared: str, real: str): ...
    def log_nested_found(self, parent: ArchiveTask, count: int): ...

    # GUI 回调
    def add_callback(self, cb: callable) -> None: ...

    # 导入导出
    def export_failed_tasks(self, output_path: Path) -> Result[Path]:
        """将失败任务导出为 CSV"""
    def load_failed_tasks(self, csv_path: Path) -> Result[list[ArchiveTask]]:
        """从 CSV 恢复失败任务列表"""

    # 汇总
    def get_run_summary(self) -> RunSummary: ...
    def close(self): ...

    # 脱敏
    @staticmethod
    def sanitize(message: str, password: str | None) -> str:
        """将明文密码替换为 ***"""
```

**实现约束**:
- `AppLogger` 类内部的 logging handler 使用 Python 标准库 `logging`
- `add_callback()` 允许外部注册回调，每条日志输出后调用 `cb(level, message)`
- `log_password_attempt` 中的密码信息必须脱敏（不记录明文密码）
- `export_failed_tasks` 输出 CSV: `task_id,file_path,real_type,reason,attempted_passwords_count`
- `get_run_summary` 通过日志记录的任务完成/失败事件统计来填充 RunSummary

**测试用例清单**:
1. `setup()` 创建日志文件
2. `info()` / `error()` 写入文件验证
3. `sanitize()` 密码脱敏
4. `export_failed_tasks()` 生成 CSV 内容正确
5. `load_failed_tasks()` 往返验证
6. `log_task_start/done/fail()` 格式正确
7. callback 被调用
8. 不会 crash：传入各种边界值

---

### 阶段 5 — 串行（依赖阶段 1+2+3+4）

#### Task 5.1: `extractor.py`

**依赖**: `types.py`, `config.py`, `file_utils.py`, `password_mgr.py`, `engines/factory.py`  
**不依赖**: `scanner.py`, `task_queue.py`, `logger.py`, `gui.py`, `cli.py`  
**输出文件**: `src/archunpack/extractor.py`, `tests/test_extractor.py`

**公开接口**:

```python
from pathlib import Path
from .config import Config
from .types import Result, ArchiveTask, TaskStatus
from .password_mgr import PasswordManager

class Extractor:
    def __init__(self, config: Config, password_mgr: PasswordManager): ...

    def process_task(self, task: ArchiveTask) -> Result[ArchiveTask]:
        """
        核心流程（无副作用，不操作队列）：
        1. 若 task.is_encrypted 为 None → 调用 file_utils.detect_encryption()
        2. 若加密 → _try_passwords(task)
        3. 若未加密 → _do_extract(task, None)
        4. 成功后:
           a. 扫描 output_dir → file_utils 找嵌套压缩包
           b. depth < max_depth → 构建子 ArchiveTask 存入 task.inner_archives
           c. depth=0 且 delete_intermediate → 不删（顶层文件保留）
           d. depth>0 且 delete_intermediate → safe_delete 中间容器
        5. 返回更新后的 task（status, password 等已填充）
        """

    def _try_passwords(self, task: ArchiveTask) -> Result[Path]:
        """
        按 pwmgr.get_ordered_passwords() 顺序尝试：
        for idx, pwd in enumerate(passwords):
            result = _do_extract(task, pwd)
            if result.is_ok():
                pwmgr.record_hit(pwd)
                return result
        return Result.fail("all passwords failed", "PASSWORD_FAIL")
        """

    def _do_extract(self, task: ArchiveTask, password: str | None) -> Result[Path]:
        """
        1. factory.create_engine(task.real_type)
        2. engine.extract(task.file_paths, output_dir, password, overwrite_mode)
        3. 返回 output_dir 路径
        """

    def get_engine_status(self) -> dict[str, str]:
        """封装 factory.check_all_available()"""
```

**实现约束**:
- `process_task()` 期望返回修改后的同一个 task 对象（附带 status、password、output_path 等）
- `Extractor` 实例无内部可变状态，可被多线程安全调用（前提是 PasswordManager 已线程安全）
- 嵌套发现的子任务不存入任务队列，而是作为 `task.inner_archives` 返回，由调用方（TaskQueue）决定是否入队
- 解压失败时 task 的状态通过 `TaskStatus.FAILED` / `TaskStatus.ERROR` 区分

**测试用例清单**:
1. 加密 .7z 密码命中 → task.status=DONE, task.password 非空
2. 加密 .7z 全部密码失败 → task.status=FAILED
3. 未加密 .7z 直接解压 → 不调用密码表
4. `detect_encryption` 返回加密状态后正确分支
5. 嵌套发现: 解压出 .zip → inner_archives 非空
6. 嵌套深度达上限 → 不再递归 inner_archives
7. 中间文件删除: depth>0 + delete_intermediate=True
8. 引擎不可用 → Result.fail "ENGINE_UNAVAILABLE"
9. 密码命中后 pwmgr.record_hit 被调用（mock 验证）
10. `get_engine_status()` 返回正确字典

---

### 阶段 6 — 串行（依赖阶段 1+2）

#### Task 6.1: `task_queue.py`

**依赖**: `types.py`, `config.py`  
**不依赖**: engines, password_mgr, scanner, extractor, logger, gui, cli  
**输出文件**: `src/archunpack/task_queue.py`, `tests/test_task_queue.py`

**公开接口**:

```python
from queue import Queue
from threading import Thread, Lock
from pathlib import Path
from .config import Config
from .types import ArchiveTask, RunSummary, Result

class TaskQueue:
    def __init__(self, config: Config): ...

    # 回调注册（在 start() 之前设置）
    on_task_start: callable | None     # (ArchiveTask) -> None
    on_task_done: callable | None      # (ArchiveTask) -> None
    on_task_fail: callable | None      # (ArchiveTask) -> None
    on_new_task: callable | None       # (ArchiveTask) -> None
    on_all_done: callable | None       # (RunSummary) -> None

    def submit(self, tasks: list[ArchiveTask]) -> int: ...
    def submit_single(self, task: ArchiveTask) -> None: ...

    def start(self, process_func: callable) -> None:
        """
        启动 worker_count 个工作线程。
        process_func: (ArchiveTask) -> Result[ArchiveTask]
        worker_count = config.max_parallel if >0 else os.cpu_count()
        """

    def stop(self) -> None:
        """优雅停止：等待当前任务完成，不接受新任务"""

    def force_stop(self) -> None:
        """立即标记所有线程停止"""

    def get_task(self, task_id: str) -> ArchiveTask | None: ...
    def get_all_tasks(self) -> list[ArchiveTask]: ...
    def get_stats(self) -> dict:
        """{"pending": 10, "running": 2, "done": 5, "failed": 1, "error": 0, "skipped": 0}"""

    def build_summary(self) -> RunSummary: ...

    @property
    def complete_count(self) -> int: ...
    @property
    def pending_count(self) -> int: ...
    @property
    def is_running(self) -> bool: ...
```

**内部设计要点**:
- 使用 `queue.Queue`（线程安全）
- 工作线程函数 `_worker(process_func)`:
  ```
  while not stopped:
      task = queue.get(timeout=1)
      if timeout: continue
      on_task_start(task)
      result = process_func(task)
      更新 task 状态
      if task.status == DONE:
          on_task_done(task)
          for inner in task.inner_archives:  # 嵌套发现
              submit_single(inner)
              on_new_task(inner)
      elif task.status in (FAILED, ERROR):
          on_task_fail(task)
      queue.task_done()
  ```
- `build_summary()` 遍历 `_all_tasks` 字典统计

**实现约束**:
- 回调在 Worker 线程中同步调用，调用方负责线程安全（GUI 方用 `after()`）
- `on_all_done` 在 Queue 空且所有 Worker 无正在处理的任务时触发
- `submit_single()` 可在 `start()` 之后调用（支持嵌套发现）

**测试用例清单**:
1. `submit()` + `start()` → 所有任务按 process_func 处理完毕
2. `start()` 后 `submit_single()` 动态追加任务 → 新任务被处理
3. 嵌套发现: process_func 返回带 inner_archives 的 task → on_new_task 被调用
4. `on_task_start/done/fail` 回调调用次数和参数验证
5. `get_stats()` 各状态计数准确
6. `build_summary()` 汇总正确
7. `stop()` 后不再处理新提交的任务
8. `force_stop()` 立即中断
9. 并发安全性：100 个任务 4 线程，final stats 一致
10. `on_all_done` 在所有任务结束后触发且仅触发一次

---

### 阶段 7 — 并行（依赖阶段 1~6）

#### Task 7.1: `cli.py`

**依赖**: 所有核心模块  
**输出文件**: `src/archunpack/cli.py`, `tests/test_cli.py`

**公开接口**:

```python
def main(argv: list[str] | None = None) -> int:
    """
    argparse 参数:
      --source, -s    源目录（必需）
      --output, -o    输出目录（必需）
      --passwords, -p 密码文件（必需）
      --workers, -w   并行数（默认0=自动）
      --max-depth     最大嵌套深度（默认5）
      --no-cleanup    保留中间文件
      --overwrite     覆盖策略 skip|overwrite|rename
      --log-dir       日志目录
      --scan-only     仅扫描不解压

    返回 exit code: 0=成功, 1=有失败, 2=严重错误
    """
```

**实现约束**:
- CLI 逻辑与 GUI 共享同一套 Config/Scanner/Extractor/TaskQueue 实例
- `--scan-only` 模式只输出表格化的 ScanSummary
- 解压模式在 `on_all_done` 中输出表格化的 RunSummary
- 完成后调用 `pwmgr.save_hot_passwords()` 和 `logger.close()`
- 用 `print()` 输出进度，不引入 rich/click 等额外依赖

**测试用例清单**:
1. `--scan-only` 输出包含正确的文件数量和类型分布
2. 缺少必需参数抛出 SystemExit
3. `--help` 不报错
4. 完整流程 end-to-end（用临时目录+测试压缩包）
5. 完成后 .hot_passwords 文件生成
6. 完成后 logs/ 下有日志文件

---

#### Task 7.2: `gui.py`

**依赖**: 所有核心模块  
**输出文件**: `src/archunpack/gui.py`（GUI 无自动化单元测试，通过手动测试验收）

**公开接口**:

```python
def main() -> None:
    """启动 tkinter 主循环"""
```

**界面布局要求** (按 8.1.1 设计文档):

```
┌─────────────────────────────────────────────┐
│  加密压缩包批量解压工具                        │
├─────────────────────────────────────────────┤
│  源目录:   [__________] [浏览]               │
│  输出目录: [__________] [浏览]               │
│  密码文件: [__________] [浏览]               │
│  并发线程: [▼]  深度: [▼]  □删除中间文件     │
│  ┌─环境─┐ 7z:✓ WinRAR:✓ 密码:12            │
│  [扫描] [开始解压] [停止]                     │
│  ┌─进度─┐ ████░░░ 45%  成功:8 失败:1        │
│  ┌─日志─┐ [12:00] 扫描完成...               │
│  [导出日志] [导出失败清单]                    │
└─────────────────────────────────────────────┘
```

**核心类**:

```python
class ArchiveUnpackApp:
    def __init__(self): 
        self.root = tk.Tk()
        self.config = Config()
        self._build_ui()
        self._detect_env()
    
    def _detect_env(self):
        """启动时检测 7z/WinRAR 路径和引擎状态，显示在环境面板"""
    
    def _on_scan(self):
        """后台线程: scanner.scan() → 更新进度 + 日志"""

    def _on_start(self):
        """提交任务 → task_queue.start(extractor.process_task)"""

    def _on_stop(self):
        """task_queue.force_stop()"""

    # TaskQueue 回调（在 Worker 线程调用，必须用 root.after 回到主线程）
    def _cb_task_start(self, task): ...
    def _cb_task_done(self, task): ...
    def _cb_task_fail(self, task): ...
    def _cb_all_done(self, summary): ...

    def _update_progress(self, stats: dict): ...
    def _append_log(self, level: str, msg: str): ...
```

**实现约束**:
- 所有 UI 更新必须通过 `self.root.after(0, callback, *args)`
- 解压操作通过 `threading.Thread` 后台执行，保持 UI 响应
- tkinter 内置组件，不依赖 ttkbootstrap 等第三方包
- 文件选择对话框使用 `filedialog.askdirectory()` / `filedialog.askopenfilename()`

**手动测试检查清单** (文档内记录，不需 pytest):
1. 窗口正常打开和关闭
2. 浏览按钮能弹出系统文件/目录选择对话框
3. 环境检测正确显示 7-Zip/WinRAR 状态
4. 扫描按钮：选择目录后点击扫描，显示文件清单
5. 开始解压按钮：密码正确时进度条推进，日志滚动
6. 停止按钮：正在解压时点击停止，任务不再继续
7. 完成后弹出汇总报告
8. 导出日志/失败清单按钮正常

---

## 4. 子 Agent 生成规则

### 4.1 通用指令

每个子 Agent 接收以下 Prompt 模板：

```
你是一个代码实现Agent。你的任务是实现模块 {module_name}。

## 上下文
- 项目根目录: {project_root}
- 已有文件: {existing_files_list}
- 依赖模块接口: {adjacent_module_interfaces}

## 实现规格
{copied_from_section_3}

## 输出
1. 写入 {output_file_path}
2. 写入 {test_file_path}（gui.py 除外）

## 约束
- 所有公开方法必须有完整的 type annotations
- 代码行长度不超过100字符
- 使用 Python 3.10+ 语法
- 编写的是 src/archunpack/ 下的源文件，测试在 tests/ 下
- 不要引入未在 pyproject.toml 中声明的依赖
- 不要写任何 markdown 解释文档
- 返回: 文件路径 + 代码行数 + 函数数量
```

### 4.2 阶段内并行 vs 阶段间串行

```
阶段1 ─┬─ Task 1.1 (config.py)  ─┐
       └─ Task 1.2 (types.py)   ─┘ 并行
             │
阶段2 ─┬─ Task 2.1 (file_utils.py)   ─┐
       ├─ Task 2.2 (password_mgr.py)  ─┤ 并行
       └─ Task 2.3 (engines base+factory) ─┘
             │
阶段3 ─┬─ Task 3.1 (_7z.py)   ─┐
       ├─ Task 3.2 (_zip.py)   ─┤ 并行
       ├─ Task 3.3 (_rar.py)   ─┤
       └─ Task 3.4 (_tar.py)   ─┘
             │
阶段4 ─┬─ Task 4.1 (scanner.py) ─┐ 并行
       └─ Task 4.2 (logger.py)  ─┘
             │
阶段5 ─── Task 5.1 (extractor.py)  (串行，依赖阶段4)
             │
阶段6 ─── Task 6.1 (task_queue.py) (串行，依赖阶段5)
             │
阶段7 ─┬─ Task 7.1 (cli.py)  ─┐ 并行
       └─ Task 7.2 (gui.py)   ─┘
```

### 4.3 模块间接口共享

当子 Agent 需要调用已实现模块的接口时，主 Agent 必须将对应接口签名作为上下文注入。例如实现 `scanner.py` 时，注入 `file_utils.py` 的已实现接口签名。

---

## 5. 最终验证

所有阶段完成后，主 Agent 执行：

```bash
# 全面类型检查
mypy src/archunpack/ tests/ --strict

# 全面 Lint
ruff check src/archunpack/ tests/

# 全部单元测试
pytest tests/ -v --tb=short --cov=src/archunpack --cov-report=term-missing

# 集成测试
pytest tests/test_integration.py -v --tb=long
```

全部通过后输出最终质量报告：

```
========== 最终质量报告 ==========
模块       测试数  通过  mypy  ruff  覆盖率
---------- ------ ----  ----  ----  ------
config     6/6    ✓     ✓     ✓     100%
types      7/7    ✓     ✓     ✓     100%
file_utils 14/14  ✓     ✓     ✓      95%
password   10/10  ✓     ✓     ✓     100%
engines/7z 9/9    ✓     ✓     ✓      92%
engines/zip 8/8   ✓     ✓     ✓      90%
engines/rar 6/6   ✓     ✓     ✓      88%
engines/tar 8/8   ✓     ✓     ✓     100%
scanner    9/9    ✓     ✓     ✓      93%
logger     8/8    ✓     ✓     ✓      96%
extractor  10/10  ✓     ✓     ✓      91%
task_queue 11/11  ✓     ✓     ✓      95%
cli        6/6    ✓     ✓     ✓      85%
integration 4/4   ✓     —     —       —
---------- ------ ----  ----  ----  ------
总计       116    116   —     —      93% avg
========== 项目通过 ✓ ==========
```

---

## 6. 启动指令

作为主 Agent，请按以下步骤开始：

1. **创建项目骨架** — 目录结构 + pyproject.toml + conftest.py + `__init__.py` 文件
2. **安装依赖** — `pip install -e ".[dev]"`
3. **按阶段生成子 Agent** — 每个阶段内并行启动，完成后方可进入下一阶段
4. **质量门禁** — 每个子 Agent 返回后立即执行 pytest + mypy + ruff
5. **失败重试** — 最多 3 次，将完整错误输出反馈给子 Agent
6. **最终验收** — 全部通过后输出质量报告
