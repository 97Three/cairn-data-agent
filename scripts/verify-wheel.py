from __future__ import annotations

import argparse
import json
import stat
import subprocess
import tarfile
from email import policy
from email.parser import BytesParser
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn
from zipfile import ZipFile, ZipInfo

import yaml

RESOURCE_SUFFIXES = {
    "contracts": {".json", ".md"},
    "examples": {".csv", ".md", ".xlsx"},
    "scenarios": {".md", ".yaml", ".yml"},
    "skills": {".json", ".md", ".py", ".yaml", ".yml"},
}
BUNDLED_PREFIX = PurePosixPath("cairn_data_agent/_bundled")
PACKAGE_SOURCE_PREFIX = PurePosixPath("src/cairn_data_agent")
FORBIDDEN_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "runtime-data",
}
FORBIDDEN_SUFFIXES = {
    ".db",
    ".jks",
    ".key",
    ".log",
    ".map",
    ".p12",
    ".pem",
    ".pfx",
    ".pyc",
    ".pyo",
    ".sqlite",
    ".sqlite3",
}
EXPECTED_SCENARIOS = {"learning-notes", "stock-research", "travel-budget"}
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_MEMBER_BYTES = 25 * 1024 * 1024


def fail(message: str) -> NoReturn:
    raise SystemExit(message)


def digest(content: bytes) -> str:
    return sha256(content).hexdigest()


def tracked_files(project_root: Path) -> dict[str, Path]:
    result = subprocess.run(
        ["git", "-C", str(project_root), "ls-files", "-z"],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        fail("无法读取 Git 跟踪文件；发行制品必须从 Git 工作树构建")

    tracked: dict[str, Path] = {}
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        try:
            relative = raw_path.decode("utf-8")
        except UnicodeDecodeError as error:
            fail(f"Git 路径不是 UTF-8：{error}")
        archive_path = PurePosixPath(relative)
        validate_archive_path(archive_path)
        source = project_root.joinpath(*archive_path.parts)
        if source.is_symlink():
            fail(f"发行文件不能是符号链接：{relative}")
        if not source.is_file():
            fail(f"Git 跟踪文件在工作树中不存在：{relative}")
        tracked[relative] = source
    if not tracked:
        fail("Git 跟踪文件清单为空")
    return tracked


def validate_archive_path(path: PurePosixPath) -> None:
    rendered = str(path)
    if "\\" in rendered:
        fail(f"制品路径不得包含反斜杠：{rendered}")
    if path.is_absolute() or not path.parts or ".." in path.parts:
        fail(f"制品包含不安全路径：{rendered}")
    folded_parts = {part.casefold() for part in path.parts}
    if FORBIDDEN_PARTS.intersection(folded_parts):
        fail(f"制品包含禁止目录：{rendered}")
    name = path.name.casefold()
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        fail(f"制品包含环境配置：{rendered}")
    if path.suffix.casefold() in FORBIDDEN_SUFFIXES:
        fail(f"制品包含禁止文件：{rendered}")


def ensure_unique_paths(paths: list[str], label: str) -> None:
    if len(paths) != len(set(paths)):
        fail(f"{label} 包含重复成员名")
    folded = [path.casefold() for path in paths]
    if len(folded) != len(set(folded)):
        fail(f"{label} 包含大小写冲突成员名")


def check_archive_sizes(sizes: list[tuple[str, int]], label: str) -> None:
    total = 0
    for name, size in sizes:
        if size < 0 or size > MAX_ARCHIVE_MEMBER_BYTES:
            fail(f"{label} 成员大小超过限制：{name}")
        total += size
    if total > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
        fail(f"{label} 解压后总大小超过限制")


def expected_wheel_files(project_root: Path) -> dict[str, Path]:
    tracked = tracked_files(project_root)
    expected: dict[str, Path] = {}
    for relative, source in tracked.items():
        path = PurePosixPath(relative)
        if path.is_relative_to(PACKAGE_SOURCE_PREFIX):
            package_relative = path.relative_to(PACKAGE_SOURCE_PREFIX)
            if source.suffix != ".py":
                fail(f"Python 包包含未允许的文件类型：{relative}")
            expected[str(PurePosixPath("cairn_data_agent") / package_relative)] = source
            continue

        top_level = path.parts[0]
        suffixes = RESOURCE_SUFFIXES.get(top_level)
        if suffixes is None:
            continue
        resource_root = project_root / top_level
        if resource_root.is_symlink():
            fail(f"资源目录不能是符号链接：{top_level}")
        if source.suffix.casefold() not in suffixes:
            fail(f"资源目录包含未允许的文件类型：{relative}")
        expected[str(BUNDLED_PREFIX / path)] = source

    for directory in RESOURCE_SUFFIXES:
        prefix = str(BUNDLED_PREFIX / directory) + "/"
        if not any(name.startswith(prefix) for name in expected):
            fail(f"资源目录为空：{directory}")
        for source in sorted((project_root / directory).rglob("*")):
            if source.is_symlink():
                fail(f"资源目录不能包含符号链接：{source.relative_to(project_root)}")
            if source.is_dir() or "__pycache__" in source.parts:
                continue
            relative = source.relative_to(project_root).as_posix()
            if source.suffix.casefold() in {".pyc", ".pyo"}:
                continue
            if relative not in tracked:
                fail(f"资源文件必须先加入 Git 再构建制品：{relative}")
    return expected


def validate_metadata(content: bytes, label: str) -> None:
    metadata = BytesParser(policy=policy.default).parsebytes(content)
    if metadata.get_all("License-Expression", []) != ["MIT"]:
        fail(f"{label} 的 License-Expression 不是 MIT")
    license_files = metadata.get_all("License-File", [])
    if license_files != ["LICENSE"]:
        fail(f"{label} 必须且只能声明 License-File: LICENSE")


def is_zip_symlink(info: ZipInfo) -> bool:
    return stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK


def verify_wheel(wheel_path: Path, project_root: Path) -> None:
    expected_sources = expected_wheel_files(project_root)
    license_content = (project_root / "LICENSE").read_bytes()
    with ZipFile(wheel_path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        ensure_unique_paths(names, "wheel")
        check_archive_sizes([(info.filename, info.file_size) for info in infos], "wheel")
        for info in infos:
            validate_archive_path(PurePosixPath(info.filename))
            file_type = stat.S_IFMT(info.external_attr >> 16)
            if info.is_dir() or is_zip_symlink(info) or file_type not in {0, stat.S_IFREG}:
                fail(f"wheel 包含非普通文件：{info.filename}")
            if info.flag_bits & 0x1:
                fail(f"wheel 包含加密成员：{info.filename}")

        metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            fail("wheel 必须且只能包含一个 dist-info/METADATA")
        dist_info = PurePosixPath(metadata_names[0]).parent
        generated = {
            str(dist_info / "METADATA"),
            str(dist_info / "WHEEL"),
            str(dist_info / "entry_points.txt"),
            str(dist_info / "licenses/LICENSE"),
            str(dist_info / "RECORD"),
        }
        expected_names = set(expected_sources) | generated
        missing = sorted(expected_names - set(names))
        unexpected = sorted(set(names) - expected_names)
        if missing or unexpected:
            fail(f"wheel 全量清单不一致；missing={missing}, unexpected={unexpected}")

        for info in infos:
            archive.read(info)
        for name, source in expected_sources.items():
            if digest(archive.read(name)) != digest(source.read_bytes()):
                fail(f"wheel 文件内容与工作树不一致：{name}")
        license_name = str(dist_info / "licenses/LICENSE")
        if archive.read(license_name) != license_content:
            fail("wheel LICENSE 与仓库根 LICENSE 不一致")
        validate_metadata(archive.read(str(dist_info / "METADATA")), "wheel METADATA")

    resource_count = sum(name.startswith(str(BUNDLED_PREFIX) + "/") for name in expected_sources)
    print(f"wheel full manifest verified: {len(expected_names)} files, {resource_count} resources")


def verify_sdist(sdist_path: Path, project_root: Path) -> None:
    tracked = tracked_files(project_root)
    with tarfile.open(sdist_path, mode="r:gz") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        ensure_unique_paths(names, "sdist")
        check_archive_sizes([(member.name, member.size) for member in members], "sdist")
        for member in members:
            path = PurePosixPath(member.name)
            validate_archive_path(path)
            if member.issym() or member.islnk():
                fail(f"sdist 包含链接：{member.name}")
            if not member.isfile():
                fail(f"sdist 包含非普通文件：{member.name}")

        roots = {PurePosixPath(name).parts[0] for name in names}
        if len(roots) != 1:
            fail("sdist 必须且只能包含一个顶层目录")
        root = next(iter(roots))
        expected_names = {f"{root}/{relative}" for relative in tracked} | {f"{root}/PKG-INFO"}
        missing = sorted(expected_names - set(names))
        unexpected = sorted(set(names) - expected_names)
        if missing or unexpected:
            fail(f"sdist 全量清单不一致；missing={missing}, unexpected={unexpected}")

        by_name = {member.name: member for member in members}
        for relative, source in tracked.items():
            member = archive.extractfile(by_name[f"{root}/{relative}"])
            if member is None or digest(member.read()) != digest(source.read_bytes()):
                fail(f"sdist 文件内容与工作树不一致：{relative}")
        license_member = archive.extractfile(by_name[f"{root}/LICENSE"])
        metadata_member = archive.extractfile(by_name[f"{root}/PKG-INFO"])
        if (
            license_member is None
            or license_member.read() != (project_root / "LICENSE").read_bytes()
        ):
            fail("sdist LICENSE 与仓库根 LICENSE 不一致")
        if metadata_member is None:
            fail("sdist 缺少 PKG-INFO")
        validate_metadata(metadata_member.read(), "sdist PKG-INFO")

    print(f"sdist full manifest verified: {len(expected_names)} files")


def load_demo(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"无法解析 wheel Demo 输出：{error}")
    if not isinstance(payload, dict):
        fail("wheel Demo 输出必须是 JSON object")
    return payload


def expected_demo_cases(project_root: Path) -> dict[tuple[str, str], dict[str, Any]]:
    expected: dict[tuple[str, str], dict[str, Any]] = {}
    for eval_path in sorted((project_root / "scenarios").glob("*/evals.yaml")):
        try:
            payload = yaml.safe_load(eval_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as error:
            fail(f"无法读取源码 eval pack：{eval_path}: {error}")
        if not isinstance(payload, dict) or payload.get("version") != "cairn.scenario-evals/v1":
            fail(f"源码 eval pack 版本错误：{eval_path}")
        cases = payload.get("cases")
        if not isinstance(cases, list) or not cases:
            fail(f"源码 eval pack 没有 case：{eval_path}")
        for case in cases:
            if not isinstance(case, dict) or not isinstance(case.get("id"), str):
                fail(f"源码 eval case 格式错误：{eval_path}")
            expectation = case.get("expect")
            if not isinstance(expectation, dict):
                fail(f"源码 eval expect 格式错误：{eval_path}")
            key = (eval_path.parent.name, case["id"])
            if key in expected:
                fail(f"源码 eval case 重复：{key[0]}/{key[1]}")
            expected[key] = expectation
    source_scenarios = {scenario for scenario, _ in expected}
    missing_scenarios = sorted(EXPECTED_SCENARIOS - source_scenarios)
    if missing_scenarios:
        fail(f"源码 eval 缺少基线 Scenario：{missing_scenarios}")
    return expected


def verify_demo(path: Path, project_root: Path) -> None:
    payload = load_demo(path)
    if payload.get("version") != "cairn.demo-result/v1" or payload.get("mode") != "offline":
        fail("wheel Demo 输出版本或模式错误")
    raw_runs = payload.get("runs")
    if not isinstance(raw_runs, list):
        fail("wheel Demo runs 必须是数组")
    runs: dict[tuple[str, str], dict[str, Any]] = {}
    for raw_run in raw_runs:
        if (
            not isinstance(raw_run, dict)
            or not isinstance(raw_run.get("scenario"), str)
            or not isinstance(raw_run.get("case"), str)
        ):
            fail("wheel Demo run 格式错误")
        key = (raw_run["scenario"], raw_run["case"])
        if key in runs:
            fail(f"wheel Demo case 重复：{key[0]}/{key[1]}")
        runs[key] = raw_run

    expected = expected_demo_cases(project_root)
    missing = sorted(set(expected) - set(runs))
    unexpected = sorted(set(runs) - set(expected))
    if missing or unexpected:
        fail(f"wheel Demo case 清单不一致；missing={missing}, unexpected={unexpected}")
    for key, expectation in expected.items():
        run = runs[key]
        decision = expectation.get("decision")
        expected_status = "needs_input" if decision == "clarification" else "succeeded"
        if run.get("status") != expected_status:
            fail(f"wheel Demo case 状态错误：{key[0]}/{key[1]}")
        artifact_count = run.get("artifactCount")
        if not isinstance(artifact_count, int) or artifact_count < 0:
            fail(f"wheel Demo case Artifact 数量错误：{key[0]}/{key[1]}")
        if decision == "plan" and artifact_count == 0:
            fail(f"wheel Demo plan case 没有 Artifact：{key[0]}/{key[1]}")
        if decision == "clarification" and artifact_count != 0:
            fail(f"wheel Demo clarification case 不应有 Artifact：{key[0]}/{key[1]}")
        expected_kind = expectation.get("finalArtifactKind")
        if run.get("finalArtifactKind") != expected_kind:
            fail(f"wheel Demo 最终 Artifact 类型错误：{key[0]}/{key[1]}")
        if expectation.get("evidenceRequired") and "[artifact:" not in str(run.get("answer") or ""):
            fail(f"wheel Demo case 没有证据引用：{key[0]}/{key[1]}")

    print(
        f"wheel demo verified: {len(runs)} cases across {len({key[0] for key in runs})} scenarios"
    )


def verify_installed(project_root: Path) -> None:
    import cairn_data_agent
    from cairn_data_agent.config import Settings
    from cairn_data_agent.registry import ScenarioRegistry, SkillRegistry
    from cairn_data_agent.resources import built_in_resources_root

    package_root = Path(cairn_data_agent.__file__).resolve().parent
    expected_root = (package_root / "_bundled").resolve()
    resource_root = built_in_resources_root().resolve()
    settings = Settings()
    if resource_root != expected_root:
        fail("安装版未优先使用 wheel 内置资源根")
    if settings.scenarios_root.resolve() != expected_root / "scenarios":
        fail("安装版 Settings.scenarios_root 默认值错误")
    if settings.skills_root.resolve() != expected_root / "skills":
        fail("安装版 Settings.skills_root 默认值错误")

    source_scenarios = {
        item.manifest.metadata.name
        for item in ScenarioRegistry(project_root / "scenarios", project_root / "skills").list()
    }
    installed_scenarios = {
        item.manifest.metadata.name
        for item in ScenarioRegistry(settings.scenarios_root, settings.skills_root).list()
    }
    if installed_scenarios != source_scenarios or not EXPECTED_SCENARIOS.issubset(
        installed_scenarios
    ):
        fail("安装版 Scenario 清单与源码不一致")
    source_skills = {
        f"{item.metadata.name}@{item.metadata.version}"
        for item in SkillRegistry(project_root / "skills").manifests()
    }
    installed_skills = {
        f"{item.metadata.name}@{item.metadata.version}"
        for item in SkillRegistry(settings.skills_root).manifests()
    }
    if installed_skills != source_skills or not installed_skills:
        fail("安装版 Skill 清单与源码不一致")

    print(
        f"installed defaults verified: {len(installed_scenarios)} scenarios, "
        f"{len(installed_skills)} skills"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    wheel_parser = subparsers.add_parser("wheel")
    wheel_parser.add_argument("wheel", type=Path)
    wheel_parser.add_argument("project_root", type=Path)
    sdist_parser = subparsers.add_parser("sdist")
    sdist_parser.add_argument("sdist", type=Path)
    sdist_parser.add_argument("project_root", type=Path)
    demo_parser = subparsers.add_parser("demo")
    demo_parser.add_argument("result", type=Path)
    demo_parser.add_argument("project_root", type=Path)
    installed_parser = subparsers.add_parser("installed")
    installed_parser.add_argument("project_root", type=Path)
    args = parser.parse_args()

    if args.command == "wheel":
        verify_wheel(args.wheel, args.project_root)
    elif args.command == "sdist":
        verify_sdist(args.sdist, args.project_root)
    elif args.command == "demo":
        verify_demo(args.result, args.project_root)
    else:
        verify_installed(args.project_root)


if __name__ == "__main__":
    main()
