from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_REQUIRED_RESOURCE_DIRECTORIES = ("examples", "scenarios", "skills")


def _is_resource_root(candidate: Path) -> bool:
    return all((candidate / name).is_dir() for name in _REQUIRED_RESOURCE_DIRECTORIES)


@lru_cache
def built_in_resources_root() -> Path:
    """Resolve built-in assets in an installed wheel or a source checkout."""
    package_root = Path(__file__).resolve().parent
    installed_root = package_root / "_bundled"
    if _is_resource_root(installed_root):
        return installed_root

    checkout_root = package_root.parents[1]
    if _is_resource_root(checkout_root):
        return checkout_root

    raise RuntimeError("内置 Scenario、Skill 或示例资源不完整；请重新安装发布包")
