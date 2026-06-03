from __future__ import annotations

import importlib.util
import json
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import jsonschema

from .registry import RegistryError, SkillRegistry, _safe_child


class SkillExecutionError(ValueError):
    pass


SkillFunction = Callable[[dict[str, Any]], dict[str, Any]]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SkillExecutionError(f"无法读取 Skill schema：{path.name}") from error
    if not isinstance(value, dict):
        raise SkillExecutionError("Skill schema 必须是 JSON object")
    return value


class TrustedSkillRunner:
    """Runs explicitly trusted local pure functions; this is deliberately not a sandbox."""

    def __init__(self, registry: SkillRegistry):
        self._registry = registry

    def execute(self, identity: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            bundle = self._registry.get_bundle(identity)
        except RegistryError as error:
            raise SkillExecutionError(str(error)) from error
        manifest = bundle.manifest
        if manifest.mode != "executable" or manifest.effect != "read":
            raise SkillExecutionError("教学执行器只运行显式注册的只读 executable Skill")
        if manifest.permissions.network:
            raise SkillExecutionError("教学执行器不运行联网 Skill")
        if not manifest.entrypoint:
            raise SkillExecutionError("Skill 缺少 entrypoint")

        input_schema = _load_json(_safe_child(bundle.root, manifest.input_schema))
        output_schema = _load_json(_safe_child(bundle.root, manifest.output_schema))
        try:
            jsonschema.validate(payload, input_schema)
        except jsonschema.ValidationError as error:
            raise SkillExecutionError(f"Skill 输入不符合 schema：{error.message}") from error

        function = self._load_function(bundle.root, manifest.entrypoint, identity)
        try:
            output = function(payload)
        except Exception as error:
            raise SkillExecutionError(f"Skill 执行失败：{error}") from error
        if not isinstance(output, dict):
            raise SkillExecutionError("Skill 输出必须是 JSON object")
        try:
            jsonschema.validate(output, output_schema)
            encoded = json.dumps(
                output, ensure_ascii=False, sort_keys=True, allow_nan=False
            ).encode("utf-8")
        except (jsonschema.ValidationError, TypeError, ValueError) as error:
            raise SkillExecutionError(f"Skill 输出无效：{error}") from error
        if len(encoded) > manifest.max_output_bytes:
            raise SkillExecutionError("Skill 输出超过 manifest 限额")
        return output

    @staticmethod
    def _load_function(root: Path, entrypoint: str, identity: str) -> SkillFunction:
        relative, separator, function_name = entrypoint.partition(":")
        if separator != ":" or not function_name:
            raise SkillExecutionError("Skill entrypoint 必须使用 path.py:function 格式")
        module_path = _safe_child(root, relative)
        if module_path.suffix != ".py" or not module_path.is_file():
            raise SkillExecutionError("Skill entrypoint 必须指向包内 Python 文件")
        module_name = "_cairn_skill_" + sha256(identity.encode()).hexdigest()[:16]
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            raise SkillExecutionError("无法加载 Skill entrypoint")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        function = getattr(module, function_name, None)
        if not callable(function):
            raise SkillExecutionError("Skill entrypoint function 不存在")
        return cast(SkillFunction, function)
