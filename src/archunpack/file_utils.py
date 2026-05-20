import logging
import os
import re
import shutil
from pathlib import Path
from .config import Config
from .types import Result

# 魔数签名表（模块级常量）
MAGIC_SIGNATURES: dict[str, tuple[bytes, int]] = {
    "7z": (b"\x37\x7A\xBC\xAF\x27\x1C", 0),
    "zip": (b"\x50\x4B\x03\x04", 0),
    "rar5": (b"\x52\x61\x72\x21\x1A\x07\x01\x00", 0),
    "rar4": (b"\x52\x61\x72\x21\x1A\x07\x00", 0),
    "gz": (b"\x1F\x8B", 0),
    "bz2": (b"\x42\x5A\x68", 0),
    "xz": (b"\xFD\x37\x7A\x58\x5A\x00", 0),
    "tar": (b"\x75\x73\x74\x61\x72", 257),
}


def identify_type(file_path: Path) -> Result[str]:
    """
    读取文件头 512 字节，匹配魔数签名。
    匹配顺序: 7z > zip > rar5 > rar4 > gz > bz2 > xz > tar
    tar 特殊处理：如果已匹配 gz/bz2/xz，合并为 "tar.gz"/"tar.bz2"/"tar.xz"
    """
    try:
        with open(file_path, "rb") as f:
            header = f.read(512)
    except IOError as e:
        return Result.fail(f"IOError reading file header: {e}", "IO_ERROR")

    order = ["7z", "zip", "rar5", "rar4", "gz", "bz2", "xz", "tar"]
    matched: str | None = None
    for key in order:
        sig, offset = MAGIC_SIGNATURES[key]
        if len(header) >= offset + len(sig):
            if header[offset : offset + len(sig)] == sig:
                matched = key
                break

    if matched is None:
        return Result.fail("Unknown file signature", "UNKNOWN_SIGNATURE")

    if matched in ("gz", "bz2", "xz"):
        lower_name = file_path.name.lower()
        if ".tar." in lower_name or lower_name.endswith((".tgz", ".tbz2", ".txz")):
            matched = f"tar.{matched}"

    return Result.ok(matched)


def normalize_type(raw_type: str) -> str:
    """rar4/rar5 → rar, gz → tar.gz (如果上层已是 tar)"""
    if raw_type in ("rar4", "rar5"):
        return "rar"
    if raw_type == "gz":
        return "tar.gz"
    if raw_type == "bz2":
        return "tar.bz2"
    if raw_type == "xz":
        return "tar.xz"
    return raw_type


def is_skippable(file_path: Path, config: Config) -> bool:
    """扩展名在黑名单 或 文件名以 ._ 开头"""
    name = file_path.name
    for prefix in config.skip_prefixes:
        if name.startswith(prefix):
            return True

    ext = file_path.suffix.lower()
    if ext in config.skip_extensions:
        return True

    return False


def detect_encryption(archive_path: Path, archive_type: str) -> Result[bool]:
    """
    轻量检测是否加密：
    - 7z: py7zr.SevenZipFile(archive).needs_password()
    - zip: zipfile.ZipFile(archive).infolist()[0].flag_bits & 0x1
    - rar: rarfile.RarFile(archive).needs_password()
    - tar: 始终返回 False
    注意: tar.gz/bz2/xz 为 False
    """
    try:
        norm_type = normalize_type(archive_type)
        if norm_type == "7z":
            import py7zr

            try:
                with py7zr.SevenZipFile(archive_path, "r") as sz:
                    return Result.ok(sz.needs_password())
            except Exception as e:
                err_str = str(e).lower()
                if "password" in err_str or "encrypted" in err_str:
                    return Result.ok(True)
                if "passwordrequired" in e.__class__.__name__.lower() or "bad7zfile" in e.__class__.__name__.lower():
                    return Result.ok(True)
                return Result.fail(f"Failed to read 7z headers: {e}", "ENGINE_ERROR")

        elif norm_type == "zip":
            import zipfile

            try:
                with zipfile.ZipFile(archive_path, "r") as zf:
                    infolist = zf.infolist()
                    if not infolist:
                        return Result.ok(False)
                    is_enc = any(bool(info.flag_bits & 0x1) for info in infolist)
                    return Result.ok(is_enc)
            except Exception as e:
                if "password" in str(e).lower() or "encrypted" in str(e).lower():
                    return Result.ok(True)
                return Result.fail(f"Failed to read zip headers: {e}", "ENGINE_ERROR")

        elif norm_type == "rar":
            import rarfile

            try:
                with rarfile.RarFile(archive_path, "r") as rf:
                    return Result.ok(rf.needs_password())
            except Exception as e:
                if "password" in str(e).lower() or "encrypted" in str(e).lower() or "need password" in str(e).lower():
                    return Result.ok(True)
                return Result.fail(f"Failed to read rar headers: {e}", "ENGINE_ERROR")

        elif norm_type in ("tar", "tar.gz", "tar.bz2", "tar.xz"):
            return Result.ok(False)

        else:
            return Result.fail(f"Unsupported archive type for encryption detection: {archive_type}", "UNSUPPORTED_TYPE")

    except Exception as e:
        return Result.fail(f"Encryption detection failed: {e}", "UNKNOWN_ERROR")


def find_archive_files(root: Path, config: Config) -> list[Path]:
    """递归遍历 root，跳过 is_skippable 的文件，返回文件路径列表"""
    archive_files = []
    if not root.exists():
        return []
    if root.is_file():
        if not is_skippable(root, config):
            archive_files.append(root)
        return archive_files

    for dirpath, _, filenames in os.walk(root):
        for filename in filenames:
            file_path = Path(dirpath) / filename
            try:
                if not is_skippable(file_path, config):
                    archive_files.append(file_path)
            except Exception:
                pass
    return archive_files


def group_split_volumes(files: list[Path]) -> dict[str, list[Path]]:
    """
    分卷分组规则：
    - 正则: r'(.+)\\.(\\d{3})$' 或 r'(.+)\\.(z\\d{2})$'
    - 同名前缀且数字连续 → 分为一组
    - 组内按数字升序排序
    - 返回 {group_key: [Path, ...]}
    """
    groups: dict[str, list[tuple[int, Path]]] = {}
    non_split: list[Path] = []

    split_prefixes = set()
    for f in files:
        name = f.name
        m1 = re.match(r"^(.+)\.(\d{3})$", name, re.IGNORECASE)
        m2 = re.match(r"^(.+)\.(z\d{2})$", name, re.IGNORECASE)
        if m1:
            split_prefixes.add(str(f.parent / m1.group(1)))
        elif m2:
            split_prefixes.add(str(f.parent / m2.group(1)))

    for f in files:
        name = f.name
        m1 = re.match(r"^(.+)\.(\d{3})$", name, re.IGNORECASE)
        m2 = re.match(r"^(.+)\.(z\d{2})$", name, re.IGNORECASE)

        if m1:
            prefix = str(f.parent / m1.group(1))
            val = int(m1.group(2))
            groups.setdefault(prefix, []).append((val, f))
        elif m2:
            prefix = str(f.parent / m2.group(1))
            val = int(m2.group(2)[1:])
            groups.setdefault(prefix, []).append((val, f))
        else:
            ext = f.suffix.lower()
            if ext == ".zip":
                prefix_no_ext = str(f.parent / f.stem)
                if prefix_no_ext in split_prefixes:
                    groups.setdefault(prefix_no_ext, []).append((0, f))
                    continue
            non_split.append(f)

    result: dict[str, list[Path]] = {}
    for prefix, val_paths in groups.items():
        val_paths.sort(key=lambda x: x[0])
        sorted_paths = [path for _, path in val_paths]

        vals = [val for val, _ in val_paths]
        min_v = vals[0]
        max_v = vals[-1]
        expected_range = list(range(min_v, max_v + 1))
        if len(vals) != len(expected_range):
            missing = set(expected_range) - set(vals)
            logging.warning(
                f"Split volume gap detected for prefix {Path(prefix).name}: "
                f"Missing indices: {sorted(list(missing))}"
            )

        result[str(sorted_paths[0])] = sorted_paths

    for f in non_split:
        result[str(f)] = [f]

    return result


def ensure_output_path(source_path: Path, source_root: Path, output_root: Path) -> Path:
    """镜像结构: source_root/a/b/file.7z → output_root/a/b/file/"""
    abs_src_root = source_root.resolve()
    abs_src_path = source_path.resolve()
    abs_out_root = output_root.resolve()

    try:
        rel_path = abs_src_path.relative_to(abs_src_root)
    except ValueError:
        rel_path = Path(abs_src_path.name)

    name_lower = abs_src_path.name.lower()
    stem = abs_src_path.name

    m = re.search(r"\.(7z|zip|rar|tar)?\.?(\d{3}|z\d{2})$", name_lower)
    if m:
        stem = abs_src_path.name[:-len(m.group(0))]
    else:
        for ext in (
            ".tar.gz",
            ".tar.bz2",
            ".tar.xz",
            ".7z",
            ".zip",
            ".rar",
            ".tar",
            ".gz",
            ".bz2",
            ".xz",
        ):
            if name_lower.endswith(ext):
                stem = abs_src_path.name[:-len(ext)]
                break

    if not stem:
        stem = abs_src_path.stem

    rel_dir = rel_path.parent / stem
    return abs_out_root / rel_dir


def safe_delete(path: Path, allowed_root: Path) -> Result[bool]:
    """安全删除，确保路径在 allowed_root 范围内，防止误删"""
    try:
        abs_path = path.resolve()
        abs_allowed = allowed_root.resolve()

        if abs_allowed not in abs_path.parents and abs_path != abs_allowed:
            return Result.fail(
                f"Path {path} is outside allowed deletion root {allowed_root}",
                "OUT_OF_BOUNDS_DELETE",
            )

        if not abs_path.exists():
            return Result.ok(False)

        if abs_path.is_file():
            abs_path.unlink()
        elif abs_path.is_dir():
            shutil.rmtree(abs_path)

        return Result.ok(True)
    except Exception as e:
        return Result.fail(f"Failed to delete path {path}: {e}", "DELETE_ERROR")


def detect_archive_type_from_path(file_path: Path) -> str | None:
    """纯扩展名检测（用于魔数识别失败时的回退）"""
    name_lower = file_path.name.lower()
    if name_lower.endswith(".tar.gz") or name_lower.endswith(".tgz"):
        return "tar.gz"
    if name_lower.endswith(".tar.bz2") or name_lower.endswith(".tbz2"):
        return "tar.bz2"
    if name_lower.endswith(".tar.xz") or name_lower.endswith(".txz"):
        return "tar.xz"
    if name_lower.endswith(".7z") or re.search(r"\.7z\.\d{3}$", name_lower):
        return "7z"
    if name_lower.endswith(".zip") or re.search(r"\.(zip|z\d{2})$", name_lower):
        return "zip"
    if name_lower.endswith(".rar") or re.search(r"\.rar\.\d{3}$", name_lower):
        return "rar"
    if name_lower.endswith(".tar"):
        return "tar"
    return None
