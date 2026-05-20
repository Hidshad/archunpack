from pathlib import Path
import pytest
from archunpack.engines.base import BaseEngine
from archunpack.engines.factory import (
    register_engine,
    create_engine,
    check_all_available,
    ENGINE_REGISTRY,
)
from archunpack.types import Result


def test_base_engine_abc() -> None:
    # 1. BaseEngine cannot be directly instantiated
    with pytest.raises(TypeError):
        BaseEngine()  # type: ignore


def test_subclass_missing_methods() -> None:
    # 2. Subclass missing abstract methods raises TypeError
    with pytest.raises(TypeError):
        class BadEngine(BaseEngine):
            pass
        BadEngine()  # type: ignore[abstract]


def test_register_and_create_engine() -> None:
    # 3. Register and create engine happy path
    class DummyEngine(BaseEngine):
        def extract(
            self,
            archive_paths: list[Path],
            output_dir: Path,
            password: str | None,
            overwrite_mode: str = "skip",
        ) -> Result[Path]:
            return Result.ok(output_dir)

        def test_availability(self) -> Result[str]:
            return Result.ok("library")

        @staticmethod
        def supported_format() -> str:
            return "dummy"

    register_engine("dummy", DummyEngine)
    assert ENGINE_REGISTRY["dummy"] is DummyEngine

    res = create_engine("dummy")
    assert res.is_ok()
    engine = res.unwrap()
    assert isinstance(engine, DummyEngine)

    # 4. Unknown format raises fail
    res_unknown = create_engine("nonexistent")
    assert res_unknown.is_fail()
    assert res_unknown.error_code == "ENGINE_UNAVAILABLE"


def test_check_all_available() -> None:
    # 5. Check all available returns correct registration state
    class AvailableEngine(BaseEngine):
        def extract(
            self,
            archive_paths: list[Path],
            output_dir: Path,
            password: str | None,
            overwrite_mode: str = "skip",
        ) -> Result[Path]:
            return Result.ok(output_dir)

        def test_availability(self) -> Result[str]:
            return Result.ok("library")

        @staticmethod
        def supported_format() -> str:
            return "avail"

    class UnavailableEngine(BaseEngine):
        def extract(
            self,
            archive_paths: list[Path],
            output_dir: Path,
            password: str | None,
            overwrite_mode: str = "skip",
        ) -> Result[Path]:
            return Result.ok(output_dir)

        def test_availability(self) -> Result[str]:
            return Result.fail("Missing dll", "ENGINE_UNAVAILABLE")

        @staticmethod
        def supported_format() -> str:
            return "unavail"

    register_engine("avail", AvailableEngine)
    register_engine("unavail", UnavailableEngine)

    avail_map = check_all_available()
    assert avail_map["avail"] == "library"
    assert avail_map["unavail"] == "unavailable"
