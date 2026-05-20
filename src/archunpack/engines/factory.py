import importlib
from typing import Type
from ..types import Result
from .base import BaseEngine

ENGINE_REGISTRY: dict[str, Type[BaseEngine]] = {}


def register_engine(format_name: str, engine_cls: Type[BaseEngine]) -> None:
    """注册引擎到 ENGINE_REGISTRY"""
    ENGINE_REGISTRY[format_name] = engine_cls


def create_engine(archive_type: str) -> Result[BaseEngine]:
    """根据类型字符串创建引擎实例，并调用 test_availability()"""
    _import_all_engines()

    if archive_type not in ENGINE_REGISTRY:
        return Result.fail(
            f"No engine registered for format: {archive_type}", "ENGINE_UNAVAILABLE"
        )

    try:
        engine_cls = ENGINE_REGISTRY[archive_type]
        engine = engine_cls()
        avail_res = engine.test_availability()
        if avail_res.is_fail():
            return Result.fail(
                f"Engine for {archive_type} is not available: {avail_res.error}",
                "ENGINE_UNAVAILABLE",
            )
        return Result.ok(engine)
    except Exception as e:
        return Result.fail(
            f"Failed to initialize engine for {archive_type}: {e}", "ENGINE_UNAVAILABLE"
        )


def check_all_available() -> dict[str, str]:
    """遍历注册表，返回 {format: "library"|"cli"|"unavailable"}"""
    _import_all_engines()
    results: dict[str, str] = {}
    for fmt, engine_cls in ENGINE_REGISTRY.items():
        try:
            engine = engine_cls()
            res = engine.test_availability()
            if res.is_ok():
                results[fmt] = res.unwrap()
            else:
                results[fmt] = "unavailable"
        except Exception:
            results[fmt] = "unavailable"
    return results


def _import_all_engines() -> None:
    for name in ("_7z", "_zip", "_rar", "_tar"):
        try:
            importlib.import_module(f"archunpack.engines.{name}")
        except ImportError:
            pass
