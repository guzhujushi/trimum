"""workflow 目录（Warp 式）格式与导入 —— E4，缺口 #6。

别人写好的一份 YAML 命令清单，``trm workflow import`` 就能收进 ``~/.trimum/workflows/``。
本模块只做三件事：

1. **解析**（:func:`parse_catalog`）：把一份目录 YAML 归一化成 :class:`CatalogWorkflow`；
2. **定级**（``ecosystem.assess_risk``）：按命令里的动词定级。文件里声明的 ``risk``
   只能把级别**调高**、调不低 —— 声明 medium 而命令里有 ``rm`` 时，以命令为准并给出理由；
3. **编译**（:meth:`CatalogWorkflow.to_workflow_dict`）：``command`` / ``steps[].run``
   编译成 ``WorkflowDefV2`` 的 ``steps[].execute[]``（``agent_type: shell``，
   ``instruction`` 是命令原文），生态元数据落在 ``config.ecosystem``。

三条红线（与另两个导入器一致）：

* **只读文本、只写文本**：绝不 import、绝不执行导入物 —— 导入一条 ``rm -rf`` 不会发生任何事；
* **``--dry-run`` 不落盘**，逐条给出校验结果；
* **不覆盖已有**：目标已存在时拒绝，除非显式 ``--force``（且写入前先全量检查，不做半截导入）。

与工具导入唯一的差别是 ``enabled``：工具 manifest 默认 ``enabled: false``（要显式 ``trm tool
enable``），而 workflow 是**惰性文本** —— 躺在目录里不执行任何东西，要 ``trm workflow run``
才会有动作。因此 workflow 条目直接 ``enabled: true``，否则导入完 ``trm workflow list`` 看不到它。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .ecosystem import (
    DEFAULT_RISK,
    RISK_LEVELS,
    RISK_ORDER,
    TRUST_LEVELS,
    EcosystemEntry,
    ImportRefused,
    assess_risk,
    max_risk,
    validate_entry,
)

#: 一个目录里被当作"工作流定义"的文件名（``load_from_dir`` 认的布局）。
CATALOG_FILENAMES: tuple[str, ...] = ("workflow.yaml", "workflow.yml")

#: 松散模式下认的后缀：目录里直接放 ``*.yaml`` 也能导入。
CATALOG_SUFFIXES: tuple[str, ...] = (".yaml", ".yml")

#: 目录 YAML 里认得的字段。多出来的字段只提醒，不报错（别人的格式会演进）。
KNOWN_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "name",
        "description",
        "tags",
        "risk",
        "requires",
        "command",
        "steps",
        "author",
        "source_url",
        "version",
        "timeout",
        "trust",
    }
)

#: 编译出的工作流用的 agent 类型与默认步超时。
SHELL_AGENT = "shell"
DEFAULT_STEP_TIMEOUT = 120.0

#: 触发事件：目录里的命令是"人叫它跑才跑"，不是常驻事件监听。
DEFAULT_TRIGGER_EVENT = "workflow.request"

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_FLAG_RE = re.compile(r"(?<![\w-])(--?[A-Za-z][A-Za-z0-9-]*)(?![\w-])")
_BINARY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

#: 命令首词的"包装器"：跳过它们才能看到真正要装的那个程序（``sudo docker ps`` → ``docker``）。
_WRAPPERS: frozenset[str] = frozenset(
    {"sudo", "doas", "env", "nohup", "time", "nice", "ionice", "stdbuf", "command", "exec"}
)

#: shell 内建/语法词：它们不是外部依赖，不该进 ``requires``。
_SHELL_BUILTINS: frozenset[str] = frozenset(
    {
        "cd", "echo", "export", "set", "unset", "source", ".", "true", "false", "exit",
        "return", "local", "read", "printf", "eval", "test", "trap", "umask", "wait",
        "if", "for", "while", "then", "do", "done", "case", "esac", "fi", "alias",
    }
)


class CatalogError(ValueError):
    """一份目录 YAML 不能用（语法、缺字段、非法值）时抛出。"""


def workflows_root(root: Path | str | None = None) -> Path:
    """Return the workflow root (``<TRIMUM_HOME>/workflows`` by default)."""
    if root is not None:
        return Path(root).expanduser()
    from .paths import trimum_path

    return trimum_path("workflows")


def _slug(value: str) -> str:
    """One filename-ish token, lowercased (``Docker 清理`` → ``docker``)."""
    return re.sub(r"[^a-z0-9._-]+", "-", (value or "").strip().lower()).strip("-._")


def _string_list(value: Any, field_name: str) -> list[str]:
    """Accept a comma string or a list; anything else is a hard error."""
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple)):
        items: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise CatalogError(f"`{field_name}` 只能是字符串列表")
            if item.strip():
                items.append(item.strip())
        return items
    raise CatalogError(f"`{field_name}` 只能是字符串或字符串列表")


def command_binary(command: str) -> str:
    """Guess the external program a one-line command needs, or ``""``.

    ``sudo docker ps`` → ``docker``；``cd /tmp && make`` → ``""``（首词是 shell 内建，
    后面的东西不值得猜 —— ``requires`` 宁可少写，也不要写错）。
    """
    for token in (command or "").strip().split():
        if token in _WRAPPERS:
            continue
        if _ASSIGN_RE.match(token):
            continue
        if token.startswith("-") or token in _SHELL_BUILTINS:
            return ""
        return token if _BINARY_RE.match(token) else ""
    return ""


def _collect_commands(data: dict[str, Any], warnings: list[str]) -> list[str]:
    """Pull the command list out of ``command`` / ``steps`` (in that order)."""
    commands: list[str] = []

    if data.get("command") is not None:
        raw = data["command"]
        if isinstance(raw, str):
            if raw.strip():
                commands.append(raw.strip())
            else:
                warnings.append("`command` 是空串，已忽略")
        elif isinstance(raw, (list, tuple)):
            for index, item in enumerate(raw):
                if not isinstance(item, str):
                    raise CatalogError("`command` 列表里只能放字符串")
                if item.strip():
                    commands.append(item.strip())
                else:
                    warnings.append(f"`command[{index}]` 是空串，已忽略")
        else:
            raise CatalogError("`command` 只能是字符串或字符串列表")

    raw_steps = data.get("steps")
    if raw_steps is not None:
        if not isinstance(raw_steps, (list, tuple)):
            raise CatalogError("`steps` 只能是列表")
        for index, item in enumerate(raw_steps):
            if isinstance(item, str):
                text = item
            elif isinstance(item, dict):
                text = item.get("run") or item.get("command") or ""
                extra = sorted(set(item) - {"run", "command", "timeout"})
                if extra:
                    warnings.append(f"`steps[{index}]` 的字段 {extra} 已忽略")
                if not str(text).strip():
                    raise CatalogError(f"`steps[{index}]` 既没有 `run` 也没有 `command`")
            else:
                raise CatalogError(f"`steps[{index}]` 只能是字符串或 {{run: ...}}")
            if str(text).strip():
                commands.append(str(text).strip())
            else:
                warnings.append(f"`steps[{index}]` 是空命令，已忽略")

    if data.get("command") is not None and raw_steps is not None:
        warnings.append("同时给了 `command` 与 `steps`，按顺序合并")

    return commands


@dataclass
class CatalogWorkflow:
    """One parsed catalog entry, ready to compile and import."""

    id: str
    name: str
    description: str = ""
    commands: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    risk: str = DEFAULT_RISK
    risk_reasons: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    author: str = ""
    source_url: str = ""
    trust: str = "third-party"
    version: str = ""
    timeout: float = DEFAULT_STEP_TIMEOUT
    source_path: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_entry(self) -> EcosystemEntry:
        """The same shape every other imported thing has (``kind=workflow``)."""
        return EcosystemEntry(
            name=self.id,
            kind="workflow",
            description=self.description or self.name,
            trust=self.trust,
            risk=self.risk,
            requires=list(self.requires),
            source_url=self.source_url,
            author=self.author,
            origin=self.source_path,
            enabled=True,
            tags=list(self.tags),
            risk_reasons=list(self.risk_reasons),
            details={"steps": len(self.commands), "version": self.version},
        )

    def to_workflow_dict(self) -> dict[str, Any]:
        """Compile to the ``WorkflowDefV2`` YAML layout.

        ``command`` / ``steps[].run`` 原文进 ``instruction``（``agent_type: shell``），
        生态元数据进 ``config.ecosystem`` —— 工作流本身不认识 ``trust`` / ``risk``，
        但看文件的人（和 ``trm workflow list``）应该看得到。
        """
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "steps": [
                {
                    "trigger": {"event_type": DEFAULT_TRIGGER_EVENT},
                    "execute": [
                        {
                            "agent_type": SHELL_AGENT,
                            "instruction": command,
                            "timeout_seconds": self.timeout,
                        }
                        for command in self.commands
                    ],
                }
            ],
            "config": {"ecosystem": self.to_entry().to_dict()},
        }

    def build_workflow(self):
        """Validate through ``WorkflowDefV2`` (imported lazily: heavy module)."""
        from .workflow_engine import WorkflowDefV2

        return WorkflowDefV2(**self.to_workflow_dict())

    def to_yaml(self) -> str:
        """The exact bytes that land on disk."""
        return dump_workflow(self.to_workflow_dict())

    def summary(self) -> str:
        """One line for humans."""
        return (
            f"{self.id} risk={self.risk} steps={len(self.commands)} "
            f"requires={','.join(self.requires) or '-'}"
        )


def dump_workflow(data: dict[str, Any]) -> str:
    """Serialize a compiled workflow (UTF-8, no key reordering, readable)."""
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)


def parse_catalog(
    data: Any,
    *,
    source_path: str = "",
    fallback_id: str = "",
    trust: str = "third-party",
) -> CatalogWorkflow:
    """Turn one loaded YAML document into a :class:`CatalogWorkflow`.

    Raises :class:`CatalogError` for anything that cannot be imported as-is.
    Softer issues (unknown fields, a declared risk below what the commands
    warrant) come back as ``warnings``.
    """
    where = source_path or "catalog"
    if not isinstance(data, dict):
        raise CatalogError(f"{where}: 顶层必须是 mapping，读到 {type(data).__name__}")

    catalog = CatalogWorkflow(id="", name="", source_path=source_path, trust=trust)
    warnings = catalog.warnings

    unknown = sorted(set(data) - KNOWN_FIELDS)
    if unknown:
        warnings.append("未知字段（已忽略）：" + ", ".join(unknown))

    raw_id = str(data.get("id") or "").strip()
    raw_name = str(data.get("name") or "").strip()
    if not raw_name and not raw_id:
        raise CatalogError(f"{where}: 需要 `name` 或 `id`")
    if not raw_name:
        warnings.append(f"未声明 `name`，用 `{raw_id}` 顶上")
    catalog.name = raw_name or raw_id

    id_source = raw_id or fallback_id or catalog.name
    catalog.id = _slug(id_source)
    if not _ID_RE.match(catalog.id):
        raise CatalogError(f"{where}: 推不出合法 id（来源 `{id_source}`）")
    if not raw_id:
        warnings.append(f"未声明 `id`，用 `{catalog.id}`")
    elif _slug(raw_id) != raw_id:
        raise CatalogError(f"{where}: id `{raw_id}` 只能是小写字母/数字/._-")

    declared_trust = str(data.get("trust") or "").strip().lower()
    if declared_trust:
        if declared_trust not in TRUST_LEVELS:
            raise CatalogError(
                f"{where}: 非法 trust `{declared_trust}`（可选 {', '.join(TRUST_LEVELS)}）"
            )
        catalog.trust = declared_trust

    catalog.description = str(data.get("description") or "").strip()
    catalog.author = str(data.get("author") or "").strip()
    catalog.source_url = str(data.get("source_url") or "").strip()
    catalog.version = str(data.get("version") or "").strip()
    catalog.tags = _string_list(data.get("tags"), "tags")

    if data.get("timeout") is not None:
        try:
            catalog.timeout = float(data["timeout"])
        except (TypeError, ValueError) as exc:
            raise CatalogError(f"{where}: `timeout` 必须是数字") from exc
        if catalog.timeout <= 0:
            raise CatalogError(f"{where}: `timeout` 必须大于 0")

    catalog.commands = _collect_commands(data, warnings)
    if not catalog.commands:
        raise CatalogError(f"{where}: 既没有 `command` 也没有可用的 `steps[].run`")

    declared_risk = str(data.get("risk") or "").strip().lower()
    if declared_risk and declared_risk not in RISK_ORDER:
        raise CatalogError(
            f"{where}: 非法 risk `{declared_risk}`（可选 {', '.join(RISK_LEVELS)}）"
        )

    flags = [flag for command in catalog.commands for flag in _FLAG_RE.findall(command)]
    detected, reasons = assess_risk(*catalog.commands, flags=flags)
    catalog.risk = max_risk(declared_risk, detected)
    catalog.risk_reasons = list(reasons)
    if declared_risk and RISK_ORDER[detected] > RISK_ORDER[declared_risk]:
        warnings.append(
            f"声明的 risk `{declared_risk}` 低于命令探测结果 `{detected}`，按 `{detected}` 处理"
        )

    requires = _string_list(data.get("requires"), "requires")
    inferred: list[str] = []
    for command in catalog.commands:
        binary = command_binary(command)
        if binary and binary not in requires:
            requires.append(binary)
            inferred.append(binary)
    if inferred:
        warnings.append("`requires` 自动补上（从命令首词推断）：" + ", ".join(inferred))
    catalog.requires = requires

    return catalog


def discover_catalogs(source: Path | str) -> list[Path]:
    """Find the catalog files under *source* (a file, or a directory).

    Order: ``workflow.yaml`` in the directory itself → ``<child>/workflow.yaml``
    （``load_from_dir`` 认的布局）→ 目录里散放的 ``*.yaml``。
    """
    path = Path(source).expanduser()
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise CatalogError(f"no such file or directory: {path}")

    found: list[Path] = []

    def add(candidate: Path) -> None:
        if candidate.is_file() and candidate not in found:
            found.append(candidate)

    for name in CATALOG_FILENAMES:
        add(path / name)
    for child in sorted(path.iterdir()):
        if child.is_dir():
            for name in CATALOG_FILENAMES:
                add(child / name)
    if not found:
        for candidate in sorted(path.iterdir()):
            if candidate.is_file() and candidate.suffix.lower() in CATALOG_SUFFIXES:
                add(candidate)
    return found


def load_catalog(path: Path | str, *, trust: str = "third-party") -> CatalogWorkflow:
    """Read one catalog file and parse it (never executes anything)."""
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CatalogError(f"cannot read {file_path}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise CatalogError(f"{file_path}: YAML 解析失败：{exc}") from exc

    fallback = file_path.parent.name if file_path.name in CATALOG_FILENAMES else file_path.stem
    return parse_catalog(
        data,
        source_path=str(file_path),
        fallback_id=fallback,
        trust=trust,
    )


def plan_import(
    source: Path | str,
    *,
    root: Path | str | None = None,
    trust: str = "third-party",
) -> dict[str, Any]:
    """Describe what importing *source* would do (used by ``--dry-run``).

    每个文件单独收集 ``problems`` —— 一份坏文件不该挡住其它好文件；坏的那份在写入时跳过。
    """
    paths = discover_catalogs(source)
    target_root = workflows_root(root)
    items: list[dict[str, Any]] = []
    problems: dict[str, list[str]] = {}
    seen_ids: dict[str, str] = {}

    for path in paths:
        item: dict[str, Any] = {"path": str(path), "problems": [], "warnings": []}
        try:
            catalog = load_catalog(path, trust=trust)
        except CatalogError as exc:
            item["problems"] = [str(exc)]
            problems[str(path)] = item["problems"]
            items.append(item)
            continue

        entry = catalog.to_entry()
        item["id"] = catalog.id
        item["entry"] = entry.to_dict()
        item["workflow"] = catalog.to_workflow_dict()
        item["target_dir"] = str(target_root / catalog.id)
        item["file"] = str(target_root / catalog.id / "workflow.yaml")
        item["warnings"] = list(catalog.warnings)
        item["exists"] = Path(item["file"]).exists()

        item["problems"] = list(validate_entry(entry))
        if catalog.id in seen_ids:
            item["problems"].append(f"id `{catalog.id}` 与 {seen_ids[catalog.id]} 重复")
        else:
            seen_ids[catalog.id] = str(path)
        try:
            catalog.build_workflow()
        except Exception as exc:  # pydantic 校验失败 → 这份文件不能进目录
            item["problems"].append(f"编译到 WorkflowDefV2 失败：{exc}")

        if item["problems"]:
            problems[catalog.id] = list(item["problems"])
        items.append(item)

    return {
        "source": str(source),
        "root": str(target_root),
        "files": [str(path) for path in paths],
        "workflows": items,
        "importable": sum(1 for item in items if not item["problems"]),
        "problems": problems,
    }


def write_workflows(
    plan: dict[str, Any],
    *,
    dry_run: bool = False,
    force: bool = False,
) -> list[str]:
    """Write the compiled workflows from *plan*; returns the files written.

    先全量检查再写：目标已存在（且没有 ``--force``）时抛 :class:`ImportRefused`，
    不做"写了一半才发现冲突"的导入。
    """
    usable = [item for item in plan.get("workflows", []) if not item.get("problems")]
    if not usable:
        raise ImportRefused("没有可导入的 workflow（逐条校验都没过）")

    if not force:
        clashes = [item["file"] for item in usable if Path(item["file"]).exists()]
        if clashes:
            raise ImportRefused(
                "目标已存在：" + ", ".join(clashes) + "（确认要覆盖就加 --force）"
            )
    if dry_run:
        return []

    written: list[str] = []
    for item in usable:
        target = Path(item["file"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(dump_workflow(item["workflow"]), encoding="utf-8", newline="\n")
        written.append(str(target))
    return written


__all__ = [
    "CATALOG_FILENAMES",
    "CATALOG_SUFFIXES",
    "DEFAULT_STEP_TIMEOUT",
    "DEFAULT_TRIGGER_EVENT",
    "KNOWN_FIELDS",
    "SHELL_AGENT",
    "CatalogError",
    "CatalogWorkflow",
    "command_binary",
    "discover_catalogs",
    "dump_workflow",
    "load_catalog",
    "parse_catalog",
    "plan_import",
    "workflows_root",
    "write_workflows",
]
