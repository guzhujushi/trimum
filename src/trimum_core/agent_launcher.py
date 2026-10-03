"""子 Agent 进程启动器 —— AgentManager 与 AgentRuntime 共用。

Phase 3 收尾 P1：``AgentManager.spawn`` / ``AgentRuntime.start_agent`` 之前都是
stub（只登记 AgentInfo，不真正起进程），cgroup 也就没有真实 PID 可绑。

脚本布局（Linux）::

    ~/.local/share/trimum/agents/<agent_type>/main.py

Windows 开发机回退到 ``~/.trimum/agents/<agent_type>/main.py``。

脚本契约：
- ``argv[1]`` = agent_id
- 环境变量：``TRIMUM_AGENT_ID`` / ``TRIMUM_AGENT_TYPE`` / ``TRIMUM_SOCKET_PATH``
- 收到 SIGTERM（Windows: terminate）后应尽快退出

子进程输出不走 PIPE，而是追加写入 ``<agents_root>/../agent-logs/<agent_id>.log``：
PIPE 在没人读的情况下写满 64KB 就会把 Agent 卡死，短命的 CLI 进程退出时
还会抛 asyncio "Event loop is closed"。落文件既不阻塞又留下可回看的输出，
启动失败时从本次写入区间取尾部作为 stderr 摘要。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence

from . import sandbox_exec, seccomp_exec
from .logger import get_logger

log = get_logger("trimum_core.agent_launcher")

# 启动后等一小会儿，用来发现"脚本立刻崩了"的情况
STARTUP_GRACE_SECONDS = 0.15


def _data_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(xdg) / "trimum"


def agent_log_dir(base: Optional[str | Path] = None) -> Path:
    """Agent 输出目录（与脚本根同级，随 ``agents_root`` 一起搬迁）。"""
    return agents_root(base).parent / "agent-logs"


def agents_root(base: Optional[str | Path] = None) -> Path:
    """Agent 脚本根目录。"""
    if base is not None:
        return Path(base)
    if os.name == "nt":
        # 开发机回退：~/.trimum/agents
        windows_root = Path.home() / ".trimum" / "agents"
        if windows_root.exists():
            return windows_root
    return _data_dir() / "agents"


def resolve_agent_script(
    agent_type: str,
    base: Optional[str | Path] = None,
) -> Optional[Path]:
    """返回 ``<root>/<agent_type>/main.py``，不存在则返回 None。"""
    script = agents_root(base) / agent_type / "main.py"
    return script.resolve() if script.is_file() else None


def build_agent_env(
    agent_id: str,
    agent_type: str,
    socket_path: Optional[str] = None,
    extra: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """构造子 Agent 的环境变量（继承父进程 + trimum 约定变量）。"""
    env = dict(os.environ)
    env["TRIMUM_AGENT_ID"] = agent_id
    env["TRIMUM_AGENT_TYPE"] = agent_type
    if socket_path:
        env["TRIMUM_SOCKET_PATH"] = socket_path
    for key, value in (extra or {}).items():
        env[str(key)] = str(value)
    return env


@dataclass
class LaunchResult:
    """启动结果。``process is None`` 表示没有找到脚本（仅登记）。"""

    process: Optional[asyncio.subprocess.Process] = None
    pid: Optional[int] = None
    error: Optional[str] = None
    script: Optional[Path] = None
    log_path: Optional[Path] = None
    # 内核层（Layer K）沙箱的实际状态（见 sandbox_exec.SandboxPlan.state）
    sandbox: Optional[str] = None
    # seccomp 档位的实际状态（S3；见 seccomp_exec.SeccompPlan.state）
    seccomp: Optional[str] = None
    # 本次施加的沙箱档案（run_agent 复用它来发 systemctl kill；S2 派生点收口）
    plan: Optional[Any] = None


async def launch_agent(
    agent_id: str,
    agent_type: str,
    *,
    script: Optional[Path] = None,
    base: Optional[str | Path] = None,
    socket_path: Optional[str] = None,
    extra_env: Optional[dict[str, str]] = None,
    startup_grace: float = STARTUP_GRACE_SECONDS,
    extra_write: Iterable[str] = (),
    argv_for: Optional[Callable[[Any], Sequence[str]]] = None,
) -> LaunchResult:
    """真正把子 Agent 拉起来（``sandbox_exec.spawn_exec``，S2 后唯一入口）。

    没找到脚本 → 返回空结果，由调用方决定"只登记"还是报错。
    进程秒退 → 返回 ``error``（含 stderr 摘要），调用方标记 FAILED。
    沙箱：子 Agent 拿的是「脚本目录当工作区」的档案；施加失败**不启动**（fail-closed），
    错误里带 ``[SANDBOX]`` 语义的 ``sandbox denied``，同时记 ``sandbox`` 状态。
    ``argv_for`` 非空时，用本轮的 ``SandboxPlan`` 现拼 argv（cgroup 档要在 argv 里
    包一层单元内的 Layer K 施加，见 ``_sandbox_wrapper_argv``）；默认仍是
    ``[解释器, 脚本, agent_id]``。
    """
    script = script or resolve_agent_script(agent_type, base)
    if script is None:
        return LaunchResult(script=None)

    # 必须绝对化：下面会把子进程 cwd 设为脚本目录，相对路径会解析错位
    script = Path(script).resolve()

    try:
        log_path = _prepare_log_file(agent_id, base)
    except OSError as e:
        log.warning("agent_launcher.log_open_failed", agent_id=agent_id, error=str(e))
        return LaunchResult(error=f"failed to open agent log: {e}", script=script)

    # 本次启动前的写入量：秒退时只读这一次的输出
    log_offset = log_path.stat().st_size if log_path.exists() else 0

    plan = sandbox_exec.plan_for(cwd=str(script.parent), extra_write=list(extra_write))
    # argv：默认 [解释器, 脚本, agent_id]；cgroup 档由 run_agent 用 argv_for 现拼（要拿到 plan）
    argv = list(argv_for(plan)) if argv_for is not None else [sys.executable, str(script), agent_id]
    try:
        with open(log_path, "ab") as sink:
            try:
                process = await sandbox_exec.spawn_exec(
                    plan,
                    *argv,
                    cwd=str(script.parent),
                    env=build_agent_env(agent_id, agent_type, socket_path, extra_env),
                    stdout=sink,
                    stderr=sink,
                )
            except sandbox_exec.SandboxError as exc:
                log.error(
                    "agent_launcher.sandbox_denied",
                    agent_type=agent_type,
                    error=str(exc),
                    sandbox=plan.state, seccomp=plan.seccomp_state,
                )
                return LaunchResult(
                    error=f"sandbox denied: {exc}",
                    script=script,
                    log_path=log_path,
                    sandbox=plan.state, seccomp=plan.seccomp_state,
                    plan=plan,
                )
    except Exception as e:
        log.warning("agent_launcher.spawn_failed", agent_type=agent_type, error=str(e))
        return LaunchResult(
            error=f"failed to spawn agent: {e}", script=script, log_path=log_path
        )

    if startup_grace > 0:
        await asyncio.sleep(startup_grace)

    if process.returncode is not None:
        detail = _read_log_tail(log_path, log_offset)
        log.warning(
            "agent_launcher.exited_early",
            agent_type=agent_type,
            returncode=process.returncode,
        )
        return LaunchResult(
            process=process,
            pid=process.pid,
            error=f"agent exited immediately (code={process.returncode}){detail}",
            script=script,
            log_path=log_path,
            sandbox=plan.state, seccomp=plan.seccomp_state,
        )

    log.info(
        "agent_launcher.started",
        agent_id=agent_id,
        agent_type=agent_type,
        pid=process.pid,
        script=str(script),
        log_path=str(log_path),
        sandbox=plan.state, seccomp=plan.seccomp_state,
    )
    return LaunchResult(
        process=process,
        pid=process.pid,
        script=script,
        log_path=log_path,
        sandbox=plan.state, seccomp=plan.seccomp_state,
        plan=plan,
    )


def _prepare_log_file(agent_id: str, base: Optional[str | Path]) -> Path:
    """确保日志目录存在，返回该 Agent 的日志文件（追加写）。"""
    log_dir = agent_log_dir(base)
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"{agent_id}.log"


def _read_log_tail(path: Path, offset: int = 0, limit: int = 400) -> str:
    """读取本次启动写入的日志尾部（子进程秒退时的诊断摘要）。"""
    try:
        with open(path, "rb") as fh:
            fh.seek(offset)
            data = fh.read()
    except OSError:
        return ""
    text = data.decode("utf-8", errors="replace").strip()
    if not text:
        return ""
    return f": {text[-limit:]}"


async def terminate_process(
    process: Optional[asyncio.subprocess.Process],
    timeout: float = 5.0,
) -> None:
    """优雅终止子 Agent 进程（超时则强杀）。"""
    if process is None or process.returncode is not None:
        return
    try:
        process.terminate()
        await asyncio.wait_for(process.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
    except ProcessLookupError:
        pass


def usage_path_for(agent_id: str, base: Optional[str | Path] = None) -> Path:
    """子 Agent 用量回传文件路径（与 ``<agent_id>.log`` 同目录，便于一起回看）。

    子 Agent 通过环境变量 ``TRIMUM_AGENT_USAGE_PATH`` 拿到这个绝对路径。
    """
    return agent_log_dir(base) / f"{agent_id}.usage.json"


@dataclass
class AgentRun:
    """一次子 Agent 运行的看管结果（启动 + 资源上限 + 用量回传 + 终止）。"""

    launch: Optional[LaunchResult] = None
    returncode: Optional[int] = None
    timed_out: bool = False
    terminated: bool = False
    steps_used: Optional[int] = None
    tokens_used: Optional[int] = None
    usage_reported: bool = False
    usage_path: Optional[Path] = None
    limits_state: str = ""
    unit: Optional[str] = None
    error: str = ""
    budget_exhausted: bool = False


async def _kill_unit(plan: Any, unit: str, signal_name: str) -> None:
    """终止流程的默认杀手：走 ``sandbox_exec`` 派生 ``systemctl --user kill``。

    ``plan`` 为空（理论上不该发生）⇒ 记一条 ERROR，由调用方回落到
    ``process.terminate()`` / ``process.kill()``。
    """
    if plan is None:
        log.error("agent_launcher.kill_no_plan", unit=unit, signal=signal_name)
        return
    await sandbox_exec.spawn_exec(
        plan, "systemctl", "--user", "kill",
        f"--signal={signal_name}", "--kill-whom=all", unit,
    )


async def _read_usage(path: Path) -> tuple[Optional[int], Optional[int], bool]:
    """读用量文件；只认「JSON 对象且 steps/tokens 都是非负 int」，否则一律不回填。

    返回 ``(steps, tokens, ok)``。任何坏文件 / 缺字段 / 类型不对都不抛异常（只记 warning）。
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        log.warning("agent_launcher.usage_read_failed", error=str(e))
        return None, None, False
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as e:
        log.warning("agent_launcher.usage_bad_json", error=str(e))
        return None, None, False
    if not isinstance(data, dict):
        log.warning("agent_launcher.usage_not_object")
        return None, None, False
    steps = data.get("steps")
    tokens = data.get("tokens")
    ok_steps = isinstance(steps, int) and not isinstance(steps, bool) and steps >= 0
    ok_tokens = isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0
    if not (ok_steps and ok_tokens):
        log.warning("agent_launcher.usage_bad_fields")
        return None, None, False
    return steps, tokens, True


def _budget_ceilings(budget: Any) -> tuple[Optional[int], Optional[int]]:
    """鸭子类型读预算：对象取 .steps/.tokens，Mapping 取 ["steps"]/["tokens"]。

    读不出/非法（None、bool、<=0）一律当成「这一维不设上限」⇒ 返回 None。
    """
    def _read(dim: str) -> Optional[int]:
        if budget is None:
            return None
        try:
            value = getattr(budget, dim) if not isinstance(budget, dict) else budget.get(dim)
        except Exception:  # noqa: BLE001 —— 鸭子类型读失败 = 该维不设上限
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return None
        return value

    return _read("steps"), _read("tokens")


def _over_budget(steps: Optional[int], tokens: Optional[int],
                 max_steps: Optional[int], max_tokens: Optional[int]) -> bool:
    """超预算判据（与 delegation.delegate 同一口径：严格大于才算超）。

    读不到（None）的那一维不判超（delegate 的口径：没自报就当没超）。
    """
    if max_steps is not None and steps is not None and steps > max_steps:
        return True
    if max_tokens is not None and tokens is not None and tokens > max_tokens:
        return True
    return False


async def _wait_guarded(process, usage_path: Path,
                        ceilings: tuple[Optional[int], Optional[int]],
                        timeout: float, usage_poll: float,
                        on_stop) -> tuple[bool, bool, Optional[tuple[int, int]]]:
    """等子进程退出，顺带看两件事：墙钟超时、用量超预算。

    返回 ``(timed_out, budget_exhausted, last_usage)``；发生过任一叫停就先 ``await on_stop()``
    （调用方传 TERM→宽限→KILL 的闭包）再返回。``last_usage`` = 轮询期间**读到过的最后一份合法用量**
    （没读到过就是 None），调用方用它兜底（进程可能死在写文件中间）。
    """
    max_steps, max_tokens = ceilings
    has_ceilings = max_steps is not None or max_tokens is not None
    has_deadline = timeout > 0
    if not has_ceilings and not has_deadline:
        await process.wait()
        return False, False, None

    slice_ = usage_poll if usage_poll > 0 else 0.1
    deadline = asyncio.get_running_loop().time() + timeout if has_deadline else None
    last_usage: Optional[tuple[int, int]] = None
    while True:
        remaining = (deadline - asyncio.get_running_loop().time()) if has_deadline else float("inf")
        if has_deadline and remaining <= 0:
            await on_stop()
            return True, False, last_usage
        step = min(slice_, remaining) if has_deadline else slice_
        try:
            await asyncio.wait_for(process.wait(), step)
            return False, False, last_usage
        except asyncio.TimeoutError:
            pass
        if has_ceilings:
            steps, tokens, ok = await _read_usage(usage_path)
            if ok:
                last_usage = (steps, tokens)
                if _over_budget(steps, tokens, max_steps, max_tokens):
                    await on_stop()
                    return False, True, last_usage


def _sandbox_wrapper_argv(plan: Any, *, workdir: str, argv: Sequence[str]) -> list[str]:
    """把 ``argv`` 包进 ``python -m trimum_core.sandbox_exec``（单元内施加 Layer K）。

    **为什么必须在单元内施**：``sandbox_exec`` 的 Landlock/seccomp 是 `preexec` 钩子，
    只作用于它自己 fork 的那个子进程；cgroup 档下那个子进程是 ``systemd-run``，
    真正的 agent 由 ``systemd --user`` **重新 fork**，从不经过钩子 ⇒ 边界根本没套上。
    包一层之后，「施加 → execvp 成 agent」在同一个进程里完成，`execvp` 不改 PID，
    所以单元主进程仍是 agent（``systemctl --user kill --kill-whom=all`` 照旧有效）。

    口径从**本轮的 plan** 转录（不是重新推导）：档位 + 工作区 + 写根 + seccomp 档。
    ``plan.write_roots`` 喂回 ``--write`` 是幂等的（里面已含默认写根），
    这样单元内的写面与外面报出去的 ``sandbox`` 状态是同一套。
    """
    mode = plan.mode if plan.mode in sandbox_exec.MODES else sandbox_exec.MODE_OFF
    profile = "off"
    if plan.seccomp is not None and plan.seccomp.profile in seccomp_exec.PROFILES:
        profile = plan.seccomp.profile
    head = [
        sys.executable, "-m", "trimum_core.sandbox_exec",
        "--profile", mode,
        "--cwd", workdir,
    ]
    for root in plan.write_roots:
        head += ["--write", str(root)]
    head += ["--seccomp", profile, "--"]
    return head + [str(a) for a in argv]


async def run_agent(
    agent_id: str,
    agent_type: str,
    *,
    script: Optional[Path] = None,
    base: Optional[str | Path] = None,
    socket_path: Optional[str] = None,
    extra_env: Optional[dict[str, str]] = None,
    timeout: float = 0.0,
    terminate_grace: float = 3.0,
    limits: Optional[Any] = None,
    cgroup: bool = True,
    systemd_ok: Optional[bool] = None,
    killer: Optional[Any] = None,
    startup_grace: float = STARTUP_GRACE_SECONDS,
    budget: Optional[Any] = None,   # 鸭子类型预算（delegation.Budget 形状）；None = 不按用量叫停
    usage_poll: float = 0.1,        # 预算轮询间隔（秒）；<= 0 时按 0.1 处理
) -> AgentRun:
    """把子 Agent 拉起来并**看管**：资源上限（cgroup 包装）+ 等待/终止 + 用量回传。

    只新增，不改 ``launch_agent``；接线（``delegation.default_spawn`` 用它）是下一片。

    cgroup 档下 argv 里会包一层 ``python -m trimum_core.sandbox_exec``：Layer K 必须
    在**单元内**施加 —— systemd 是重新 fork 的，`preexec` 那一层管不到真正的 agent
    （详见 ``_sandbox_wrapper_argv``）。

    **超时/终止只看 ``timed_out`` / ``terminated``，别看 ``returncode``**：真机实测，
    单元被信号杀死时 ``systemd-run --wait --pipe`` 回传的 rc 是 **0**。

    **超预算也是「真终止」**（TERM → 宽限 → KILL），``terminated`` 覆盖两种叫停
    （墙钟超时 / 用量超预算）。
    """
    from . import sandbox_limits
    from .security_config import SecurityConfig

    usage_path = usage_path_for(agent_id, base)

    # 复用 agent_id 时先丢掉上一轮的用量：否则首轮轮询会读到陈旧值直接叫停（还没开跑就结束）。
    # 删不掉（路径是目录 / 权限不足）时只告警：旧行为是优雅降级，不能因为这个变成 launch 失败。
    try:
        usage_path.unlink(missing_ok=True)
    except OSError as e:
        log.warning("agent_launcher.stale_usage_unlink_failed", path=str(usage_path), error=str(e))

    # 1) 脚本解析 / 日志文件 / 环境变量（复用现有件），并补 TRIMUM_AGENT_USAGE_PATH
    resolved = script or resolve_agent_script(agent_type, base)
    if resolved is None:
        log.warning("agent_launcher.no_script", agent_id=agent_id, agent_type=agent_type)
        return AgentRun(
            launch=LaunchResult(script=None, error=f"agent script not found: {agent_type}"),
            error=f"agent script not found: {agent_type}",
            usage_path=usage_path,
        )
    script_path = Path(resolved).resolve()

    try:
        log_path = _prepare_log_file(agent_id, base)
    except OSError as e:
        return AgentRun(
            launch=LaunchResult(error=f"failed to open agent log: {e}", script=script_path),
            error=f"failed to open agent log: {e}",
            usage_path=usage_path,
        )

    merged_extra = dict(extra_env or {})
    merged_extra["TRIMUM_AGENT_USAGE_PATH"] = str(usage_path)
    env = build_agent_env(agent_id, agent_type, socket_path, merged_extra)

    # 2) 资源上限：limits 缺省时从 SecurityConfig 解析，失败退回默认（不许崩）
    limits_state = ""
    unit: Optional[str] = None
    if limits is None:
        limits = sandbox_limits.Limits()
        try:
            limits = sandbox_limits.Limits.from_mapping(SecurityConfig().get_limits())
        except Exception as e:  # noqa: BLE001 —— 解析失败必须降级，不许崩
            limits = sandbox_limits.Limits()
            limits_state = "config-fallback"
            log.warning("agent_launcher.limits_config_failed", error=str(e))

    # 3) cgroup 包装：单元内再包一层 Layer K 施加（argv_for 要拿到 plan 才拼得出）
    base_argv = [sys.executable, str(script_path), agent_id]
    argv_for = None
    if cgroup:
        state, unit = sandbox_limits.plan_unit(agent_type, systemd_ok)
        limits_state = limits_state or state
        unit = unit or None
        if state == sandbox_limits.STATE_SYSTEMD:
            workdir = str(script_path.parent)
            # 单元里看不到调用方的环境（systemd-run 不继承）：只透传 TRIMUM_* 前缀，
            # 让单元内的 plan_for 与外面看到同一套口径（明确给的键优先）。
            unit_env = {k: v for k, v in os.environ.items() if k.startswith("TRIMUM_")}
            unit_env.update(env)

            def argv_for(plan):  # 闭包：拿到 plan 才能拼出「单元内 argv」
                inner = _sandbox_wrapper_argv(plan, workdir=workdir, argv=base_argv)
                return list(
                    sandbox_limits.build_command(
                        inner,
                        agent_name=agent_type,
                        limits=limits,
                        systemd_ok=systemd_ok,
                        env=unit_env,
                        workdir=workdir,
                        unit=unit,
                    ).argv
                )
    else:
        limits_state = "off"
        unit = None

    # 4) 启动：复用 launch_agent（S2 唯一派生点在这里），不再自己 plan_for / spawn
    # usage 目录必须在施沙箱（fork）前存在，并显式加进写面（Landlock 写面之外写不了 usage.json）
    usage_path.parent.mkdir(parents=True, exist_ok=True)
    launch = await launch_agent(
        agent_id,
        agent_type,
        script=script_path,
        base=base,
        socket_path=socket_path,
        extra_env=merged_extra,
        startup_grace=startup_grace,
        extra_write=[str(usage_path.parent)],
        argv_for=argv_for,
    )
    process = launch.process
    # launch.error 非空且 process is None ⇒ 直接返回错误，不触碰 process.pid
    if process is None and launch.error:
        return AgentRun(
            launch=launch,
            error=launch.error,
            usage_path=usage_path, limits_state=limits_state, unit=unit,
        )
    # script 不存在时 launch_agent 只登记（process is None 且无 error）⇒ 直接返回
    if process is None and not launch.error:
        launch = LaunchResult(script=script_path, error=f"agent script not found: {agent_type}")
        return AgentRun(
            launch=launch,
            error=f"agent script not found: {agent_type}",
            usage_path=usage_path, limits_state=limits_state, unit=unit,
        )

    log.info(
        "agent_launcher.started",
        agent_id=agent_id, agent_type=agent_type, pid=process.pid,
        script=str(script_path), log_path=str(log_path),
        limits_state=limits_state, unit=unit,
    )

    run = AgentRun(
        launch=launch,
        usage_path=usage_path, limits_state=limits_state, unit=unit,
    )

    # 5) 等待与终止：墙钟超时 + 用量超预算（两条都真叫停）
    async def _stop() -> None:
        await _terminate_via(launch.plan, unit, process, killer, terminate_grace)

    ceilings = _budget_ceilings(budget)
    timed_out, budget_exhausted, seen_usage = await _wait_guarded(
        process, usage_path, ceilings, timeout, usage_poll, _stop
    )
    run.returncode = process.returncode

    # 6) 用量回传：先读 usage，再看 returncode（子 Agent 可能自己终止但写了用量）
    steps, tokens, ok = await _read_usage(usage_path)
    if not ok and seen_usage is not None:
        # 被叫停的进程可能死在写文件中间 ⇒ 用「叫停前亲眼读到的那一份」兜底（如实：这份确实读到过）
        steps, tokens, ok = seen_usage[0], seen_usage[1], True
        log.warning("agent_launcher.usage_fallback_after_kill", agent_id=agent_id)
    run.steps_used = steps
    run.tokens_used = tokens
    run.usage_reported = ok
    run.timed_out = timed_out
    run.budget_exhausted = budget_exhausted
    run.terminated = timed_out or budget_exhausted

    log.info(
        "agent_launcher.exited",
        agent_id=agent_id, agent_type=agent_type,
        returncode=run.returncode,
        timed_out=run.timed_out, terminated=run.terminated,
        usage_reported=run.usage_reported,
        budget_exhausted=run.budget_exhausted,
        limits_state=limits_state, unit=unit,
    )
    return run


async def _terminate_via(
    plan: Any,
    unit: Optional[str],
    process: asyncio.subprocess.Process,
    killer: Optional[Any],
    grace: float,
) -> None:
    """终止流程：先 TERM 等宽限，仍未退则 KILL（KILL 再超时也 ``process.kill()`` 兜底）。

    ``unit`` 非空 ⇒ 信号走 ``systemctl --user kill``（``killer`` 注入只用于单测）；
    ``unit`` 为空或 ``plan`` 缺失 ⇒ 走现有 ``process.terminate()`` / ``process.kill()``。
    """
    for signal_name in ("TERM", "KILL"):
        if unit and plan is not None:
            if killer is not None:
                await killer(unit, signal_name)
            else:
                await _kill_unit(plan, unit, signal_name)
        else:
            try:
                if signal_name == "TERM":
                    process.terminate()
                else:
                    process.kill()
            except ProcessLookupError:
                pass

        try:
            await asyncio.wait_for(process.wait(), grace)
            return  # 已退出
        except asyncio.TimeoutError:
            continue
        except ProcessLookupError:
            return
    # KILL 后仍没等到（极端情况）：兜底确保进程被杀掉
    try:
        process.kill()
    except ProcessLookupError:
        pass
    await process.wait()


__all__ = [
    "AgentRun",
    "LaunchResult",
    "agent_log_dir",
    "agents_root",
    "build_agent_env",
    "launch_agent",
    "resolve_agent_script",
    "run_agent",
    "terminate_process",
    "usage_path_for",
]
