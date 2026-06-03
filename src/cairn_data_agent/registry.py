from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema
import yaml
from pydantic import TypeAdapter

from .contracts import ScenarioExample, ScenarioManifest, SkillManifest


class RegistryError(ValueError):
    pass


@dataclass(frozen=True)
class ScenarioBundle:
    manifest: ScenarioManifest
    examples: tuple[ScenarioExample, ...]
    knowledge: tuple[tuple[str, str], ...]
    root: Path


@dataclass(frozen=True)
class SkillBundle:
    manifest: SkillManifest
    root: Path


def _safe_child(root: Path, relative: str) -> Path:
    relative_path = Path(relative)
    if relative_path.is_absolute():
        raise RegistryError(f"扩展包路径不能是绝对路径：{relative}")
    if ".." in relative_path.parts:
        raise RegistryError(f"路径越过扩展包边界（包含上级目录）：{relative}")
    unresolved = root / relative_path
    cursor = unresolved
    while cursor != root:
        if cursor.is_symlink():
            raise RegistryError(f"扩展包路径不能包含符号链接：{relative}")
        cursor = cursor.parent
    candidate = unresolved.resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise RegistryError(f"路径越过扩展包边界：{relative}")
    return candidate


def _yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise RegistryError(f"无法读取 {path.name}: {error}") from error


class ScenarioRegistry:
    """Discovers extension packs without importing business code into the core."""

    def __init__(self, root: Path, skills_root: Path | None = None):
        self._root = root
        self._skills_root = skills_root

    def list(self) -> list[ScenarioBundle]:
        if not self._root.exists():
            return []
        bundles: list[ScenarioBundle] = []
        names: set[str] = set()
        available_skills = (
            {
                f"{item.metadata.name}@{item.metadata.version}"
                for item in SkillRegistry(self._skills_root).manifests()
            }
            if self._skills_root is not None
            else None
        )
        for manifest_path in sorted(self._root.glob("*/scenario.yaml")):
            bundle = self._load(manifest_path)
            name = bundle.manifest.metadata.name
            if name in names:
                raise RegistryError(f"Scenario 重名：{name}")
            names.add(name)
            if available_skills is not None:
                missing = sorted(set(bundle.manifest.skills) - available_skills)
                if missing:
                    raise RegistryError(f"Scenario {name} 引用了未注册 Skill：{', '.join(missing)}")
            bundles.append(bundle)
        return bundles

    def get(self, name: str) -> ScenarioBundle:
        for bundle in self.list():
            if bundle.manifest.metadata.name == name:
                return bundle
        raise RegistryError(f"Scenario 不存在：{name}")

    def _load(self, manifest_path: Path) -> ScenarioBundle:
        root = manifest_path.parent
        try:
            manifest = ScenarioManifest.model_validate(_yaml(manifest_path))
            examples_path = _safe_child(root, manifest.examples)
            raw_examples = _yaml(examples_path)
            examples = tuple(TypeAdapter(list[ScenarioExample]).validate_python(raw_examples))
            if len(examples) > 50:
                raise RegistryError("单个 Scenario 最多声明 50 个离线示例")
            evaluations_path = _safe_child(root, manifest.evaluations)
            if not evaluations_path.is_file():
                raise RegistryError(f"Scenario 评测文件不存在：{manifest.evaluations}")
            knowledge = tuple(
                (relative, _safe_child(root, relative).read_text(encoding="utf-8"))
                for relative in manifest.knowledge
            )
        except Exception as error:
            if isinstance(error, RegistryError):
                raise
            raise RegistryError(f"Scenario {root.name} 无效：{error}") from error
        if root.name != manifest.metadata.name:
            raise RegistryError("Scenario 目录名必须与 metadata.name 一致")
        return ScenarioBundle(manifest=manifest, examples=examples, knowledge=knowledge, root=root)


class SkillRegistry:
    def __init__(self, root: Path):
        self._root = root

    def manifests(self) -> list[SkillManifest]:
        return [bundle.manifest for bundle in self.bundles()]

    def bundles(self) -> list[SkillBundle]:
        bundles: list[SkillBundle] = []
        if not self._root.exists():
            return bundles
        for path in sorted(self._root.glob("*/skill.yaml")):
            manifest = SkillManifest.model_validate(_yaml(path))
            if path.parent.name != manifest.metadata.name:
                raise RegistryError("Skill 目录名必须与 metadata.name 一致")
            if manifest.effect == "write":
                raise RegistryError(f"教学版拒绝加载 write Skill：{manifest.metadata.name}")
            if manifest.permissions.network:
                raise RegistryError(f"教学版拒绝加载联网 Skill：{manifest.metadata.name}")
            for relative in (manifest.input_schema, manifest.output_schema):
                schema_path = _safe_child(path.parent, relative)
                try:
                    schema = (
                        _yaml(schema_path)
                        if schema_path.suffix in {".yaml", ".yml"}
                        else json.loads(schema_path.read_text(encoding="utf-8"))
                    )
                    jsonschema.Draft202012Validator.check_schema(schema)
                except Exception as error:
                    raise RegistryError(
                        f"Skill {manifest.metadata.name} schema 无效：{relative}: {error}"
                    ) from error
            bundles.append(SkillBundle(manifest=manifest, root=path.parent))
        return bundles

    def resolve(self, identities: list[str]) -> list[SkillManifest]:
        available = {
            f"{manifest.metadata.name}@{manifest.metadata.version}": manifest
            for manifest in self.manifests()
        }
        missing = sorted(set(identities) - set(available))
        if missing:
            raise RegistryError(f"未注册 Skill：{', '.join(missing)}")
        return [available[identity] for identity in identities]

    def get_bundle(self, identity: str) -> SkillBundle:
        for bundle in self.bundles():
            current = f"{bundle.manifest.metadata.name}@{bundle.manifest.metadata.version}"
            if current == identity:
                return bundle
        raise RegistryError(f"Skill 不存在：{identity}")
