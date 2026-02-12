import importlib.util
import sys
from pathlib import Path
from types import ModuleType


LEGACY_MODULE_NAME = "eco_basket._legacy_app"


def _resolve_legacy_bytecode() -> Path:
    cache_dir = Path(__file__).resolve().parents[1] / "__pycache__"
    candidates = sorted(
        cache_dir.glob("app.cpython-*.pyc"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(
            "Could not find compiled legacy app bytecode. "
            "Expected something like __pycache__/app.cpython-*.pyc."
        )
    return candidates[0]


def load_legacy_module() -> ModuleType:
    existing = sys.modules.get(LEGACY_MODULE_NAME)
    if existing is not None:
        return existing

    pyc_path = _resolve_legacy_bytecode()
    spec = importlib.util.spec_from_file_location(LEGACY_MODULE_NAME, pyc_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load legacy module spec from {pyc_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[LEGACY_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module
