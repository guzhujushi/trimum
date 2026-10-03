"""E7 自研编码智能体 · 第 2 片 —— 验证闭环（``trimum_core.verifier``）。

这一片只做两件事：

1. **登记**：``detect_project_specs`` 纯文件探测「这个项目怎么验证」
   （pytest / cargo / go / npm），产出一组 ``VerificationSpec``（argv 列表，
   不走 shell）。
2. **判定**：调用方（后续接 ``ToolGateway``）把执行结果（``CommandOutcome``）
   喂进来，本模块归一成「红 / 绿 / unknown」+ 失败清单（文件 + 行号 + 消息）
   + 证据行。

**红线**：本模块绝不派生进程、不执行任何外部命令。真正的执行由调用方
通过 ``Executor`` 注入点传进来；``outcome_from_response`` 只是把网关响应
（鸭子类型）适配成 ``CommandOutcome``。

「没跑成」永远不算通过：被拒 / 超时 / 命令不存在 → ``verdict`` 是
``"unknown"``，**不是** ``"green"``。

只用标准库（dataclasses / pathlib / typing / re 级纯正则）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

__all__ = [
    "KIND_TEST",
    "KIND_BUILD",
    "KIND_LINT",
    "VERDICT_GREEN",
    "VERDICT_RED",
    "VERDICT_UNKNOWN",
    "CommandOutcome",
    "VerificationFailure",
    "VerificationResult",
    "VerificationSpec",
    "Executor",
    "detect_project_specs",
    "parse_pytest_failures",
    "parse_failures",
    "verdict_from_outcome",
    "run_verification",
    "outcome_from_response",
]

# 验证种类（本轮只探测 test；build / lint 先留常量与字段）。
KIND_TEST = "test"
KIND_BUILD = "build"
KIND_LINT = "lint"

# 判定三态。
VERDICT_GREEN = "green"
VERDICT_RED = "red"
VERDICT_UNKNOWN = "unknown"

#: 单条证据行的最大长度，超出截断。
_EVIDENCE_LINE_MAX = 400

#: pytest 短摘要区里一条失败的定位片段：``<file>:<数字>:``。
_PYTEST_LOC_RE = re.compile(r"^(\S+):(\d+):")


@dataclass(frozen=True)
class CommandOutcome:
    """执行者回给我们的结果。

    ``exit_code`` 为 ``None`` 表示进程根本没跑起来（命令不存在之类）。
    """

    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    denied: bool = False
    timed_out: bool = False


@dataclass(frozen=True)
class VerificationFailure:
    """一条失败项：文件 + 行号（可为空）+ 消息。"""

    file: str
    line: int | None
    message: str


@dataclass(frozen=True)
class VerificationResult:
    """一次验证的归一结果。"""

    kind: str
    command: str
    exit_code: int | None
    verdict: str
    failures: list[VerificationFailure]
    evidence_lines: list[str]
    reason: str = ""


@dataclass(frozen=True)
class VerificationSpec:
    """一条「怎么验证」的登记项。

    ``command`` 是 argv 列表（不走 shell）；``parser`` 指明输出解析器
    （``"pytest"`` | ``"generic"``）；``source`` 记录命中的探测规则。
    """

    kind: str
    command: list[str]
    timeout_seconds: float = 600.0
    parser: str = "generic"
    source: str = ""


#: 执行者注入点：``(spec, cwd) -> CommandOutcome``。
#: 本模块只定义这一行类型别名，不写任何默认实现、不 import 任何执行器。
Executor = Callable[[VerificationSpec, str], CommandOutcome]


def _has_test_layout(root: Path) -> bool:
    """``tests/`` 目录存在，或根下存在匹配 ``test_*.py`` 的文件。"""
    if (root / "tests").is_dir():
        return True
    for entry in root.iterdir():
        if entry.is_file() and entry.name.startswith("test_") and entry.name.endswith(".py"):
            return True
    return False


def _python_command(root: Path) -> list[str]:
    """优先用 ``<root>/.venv/bin/python``，否则退回 ``"python"``。"""
    venv_python = root / ".venv" / "bin" / "python"
    if venv_python.is_file():
        return [str(venv_python)]
    return ["python"]


def detect_project_specs(root: str | Path) -> list[VerificationSpec]:
    """纯文件探测项目验证方式，**不执行任何命令**。

    命中顺序：Python（pytest）→ Rust（cargo）→ Go → Node（npm）。
    多条命中就都返回（顺序即上面这个顺序）；一个都没有返回 ``[]``。
    本轮只登记 ``test``。
    """
    base = Path(root)
    specs: list[VerificationSpec] = []

    # 1) Python / pytest
    py_markers = ("pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini")
    hit = next((name for name in py_markers if (base / name).is_file()), None)
    if hit is not None and _has_test_layout(base):
        specs.append(
            VerificationSpec(
                kind=KIND_TEST,
                command=_python_command(base) + ["-m", "pytest", "-q"],
                parser="pytest",
                source=hit,
            )
        )

    # 2) Rust / cargo
    if (base / "Cargo.toml").is_file():
        specs.append(
            VerificationSpec(
                kind=KIND_TEST,
                command=["cargo", "test"],
                parser="generic",
                source="Cargo.toml",
            )
        )

    # 3) Go
    if (base / "go.mod").is_file():
        specs.append(
            VerificationSpec(
                kind=KIND_TEST,
                command=["go", "test", "./..."],
                parser="generic",
                source="go.mod",
            )
        )

    # 4) Node / npm
    if (base / "package.json").is_file():
        specs.append(
            VerificationSpec(
                kind=KIND_TEST,
                command=["npm", "test"],
                parser="generic",
                source="package.json",
            )
        )

    return specs


def _file_token_from_short_id(short_id: str) -> str:
    """从 ``::`` 之前的短标识取文件段，去掉可能的前缀 ``/``。"""
    return short_id.split("::")[0].lstrip("/")


def _loc_lines_by_file(output: str) -> dict[str, list[int]]:
    """按出现顺序收集每个文件的 ``<file>:<行号>:``，供按序配对。"""
    table: dict[str, list[int]] = {}
    for raw in output.splitlines():
        match = _PYTEST_LOC_RE.match(raw.rstrip())
        if match is not None:
            table.setdefault(match.group(1), []).append(int(match.group(2)))
    return table


def parse_pytest_failures(output: str) -> list[VerificationFailure]:
    """从 pytest 输出里抽失败项。

    - 以 ``FAILED `` / ``ERROR `` 开头的行（短摘要区）为准，按出现顺序。
    - ``file`` 取 ``::`` 之前那段（去掉前缀 ``/``）；``message`` 取 `` - ``
      之后的整段（没有 `` - `` 就取剩余整段；行尾无 `` - `` 后缀则空串）。
    - ``line`` 按**逐文件按序配对**：该文件在输出里第 k 个 ``<file>:<数字>:``
      配给该文件的第 k 条失败；不够就给 ``None``（宁可给 None，不给错的行号）。
      已知局限：同一条 traceback 里若出现两次同文件的 ``file:line``
      （递归 / 同文件内嵌套调用），配对会整体顺延一位。
    - 同一个测试的重复行只记一次。
    """
    table = _loc_lines_by_file(output)
    used: dict[str, int] = {}
    failures: list[VerificationFailure] = []
    seen: set[tuple[str, str, int | None, str]] = set()

    for raw in output.splitlines():
        line = raw.rstrip()
        if line.startswith("FAILED "):
            body = line[len("FAILED "):]
        elif line.startswith("ERROR "):
            body = line[len("ERROR "):]
        else:
            continue
        if " - " in body:
            short_id, message = body.split(" - ", 1)
        else:
            short_id, message = body, ""
        short_id = short_id.strip()
        file_token = _file_token_from_short_id(short_id)
        lines = table.get(file_token, [])
        index = used.get(file_token, 0)
        found_line = lines[index] if index < len(lines) else None
        used[file_token] = index + 1
        key = (short_id, file_token, found_line, message)
        if key in seen:
            continue
        seen.add(key)
        failures.append(
            VerificationFailure(file=file_token, line=found_line, message=message)
        )

    return failures


def parse_failures(parser: str, output: str) -> list[VerificationFailure]:
    """按解析器抽失败项；不认识的解析器诚实降级返回 ``[]``。"""
    if parser == "pytest":
        return parse_pytest_failures(output)
    return []


def verdict_from_outcome(outcome: CommandOutcome) -> tuple[str, str]:
    """由执行结果归一 ``(verdict, reason)``。

    被拒 / 超时 / 没跑起来 → ``unknown``（**不是 green**）；0 → green；
    其余 → red。verdict 正常时 reason 为空串。
    """
    if outcome.denied:
        return VERDICT_UNKNOWN, "被网关拒绝，未执行"
    if outcome.timed_out:
        return VERDICT_UNKNOWN, "执行超时，未得到结论"
    if outcome.exit_code is None:
        return VERDICT_UNKNOWN, "命令没有跑起来（可能不存在）"
    if outcome.exit_code == 0:
        return VERDICT_GREEN, ""
    return VERDICT_RED, ""


def _build_evidence(output: str, max_evidence_lines: int) -> list[str]:
    """拆行、去行尾空白、截断超长行、只保留最后 N 行；无输出 → ``[]``。"""
    # 保留所有行（含空行），去行尾空白后只取最后 N 行。
    lines = [ln.rstrip() for ln in output.splitlines()]
    truncated: list[str] = []
    for ln in lines:
        if len(ln) > _EVIDENCE_LINE_MAX:
            truncated.append(ln[:_EVIDENCE_LINE_MAX] + "…")
        else:
            truncated.append(ln)
    if not truncated:
        return []
    return truncated[-max_evidence_lines:]


def run_verification(
    spec: VerificationSpec,
    *,
    cwd: str | Path,
    executor: Executor,
    max_evidence_lines: int = 40,
) -> VerificationResult:
    """执行一条验证并归一结果。

    执行者抛异常也算「没跑成」→ ``unknown``，不让异常冒泡。
    """
    try:
        outcome = executor(spec, str(cwd))
    except Exception as exc:  # noqa: BLE001 —— 执行者异常统一归一为 unknown
        verdict, reason = VERDICT_UNKNOWN, f"执行者异常：{exc!r}"
        command = " ".join(spec.command)
        return VerificationResult(
            kind=spec.kind,
            command=command,
            exit_code=None,
            verdict=verdict,
            failures=[],
            evidence_lines=[],
            reason=reason,
        )

    verdict, reason = verdict_from_outcome(outcome)
    combined = outcome.stdout + outcome.stderr
    failures = parse_failures(spec.parser, combined)
    evidence = _build_evidence(combined, max_evidence_lines)
    return VerificationResult(
        kind=spec.kind,
        command=" ".join(spec.command),
        exit_code=outcome.exit_code,
        verdict=verdict,
        failures=failures,
        evidence_lines=evidence,
        reason=reason,
    )


def outcome_from_response(response: Any) -> CommandOutcome:
    """把 ``ToolGateway`` 的 ``ExecuteResponse``（鸭子类型）适配成 ``CommandOutcome``。

    不 import ``models`` 里的那个类，只按属性取。本模块自己不执行任何东西，
    这一行接口就是 slice 5 把网关响应喂进来的唯一入口。
    """
    status = getattr(response, "status", "")
    denied = status == "denied"
    stdout = getattr(response, "output", "") or ""
    stderr = getattr(response, "error", "") or ""
    exit_code = getattr(response, "exit_code", None)
    timed_out = bool(getattr(response, "timed_out", False))
    return CommandOutcome(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        denied=denied,
        timed_out=timed_out,
    )
