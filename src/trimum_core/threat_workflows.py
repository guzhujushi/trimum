"""威胁应对工作流预注册库。

每个威胁对应一个应对工作流定义（纯 JSON 格式，无 LLM 参与）。
监听 Event Bus 的 **security.monitor_result** 事件（L4 事实链，唯一自动触发路径），
由 WorkflowRuntime 驱动执行 —— 归属决策见 ``sec_executor`` 模块 docstring 的「触发归属」。
"""

from __future__ import annotations

import re
from typing import Any

# ─── 威胁工作流结构 ───────────────────────────────
# name:     工作流名称，与 ThreatMatch.workflow_name 对应
# trigger:  触发器事件类型
# filter:   可选的事件 payload 过滤条件
# steps:    执行步骤列表（字符串命令或结构化操作）
# auto_trigger: 事件来了要不要**自动跑**（取证类 True / 处置类 False；判据见 step_kind）
# ─────────────────────────────────────────────────

THREAT_WORKFLOWS: list[dict[str, Any]] = [
    # ─── 权限逃逸类 ─────────────────────────────
    {
        "name": "threat-prelink-check",
        "auto_trigger": True,
        "trigger": "security.monitor_result",
        "filter": {"threat_name": "ld_preload"},
        "steps": [
            "cat /etc/ld.so.preload",
            "ls -la /etc/ld.so.preload",
            "sha256sum /etc/ld.so.preload",
            "比对上次 hash 基线",
            "report",
        ],
    },
    {
        "name": "threat-ebpf-scan",
        "auto_trigger": True,
        "trigger": "security.monitor_result",
        "filter": {"threat_name": "ebpf_hijack"},
        "steps": [
            "ls /sys/fs/bpf/",
            "bpftool prog list (mock)",
            "find /lib/modules/ -mmin -10",
            "比对 bpffs hash 基线",
            "report",
        ],
    },
    {
        "name": "threat-kernel-scan",
        "auto_trigger": True,
        "trigger": "security.monitor_result",
        "filter": {"threat_name": "kernel_module"},
        "steps": [
            "lsmod",
            "比对 /lib/modules/ hash",
            "检查已加载模块签名",
            "report",
        ],
    },
    # ─── 恶意软件类 ─────────────────────────────
    {
        "name": "threat-revshell-cleanup",
        "auto_trigger": False,
        "trigger": "security.monitor_result",
        "filter": {"threat_name": "reverse_shell"},
        "steps": [
            "ss -tupn",
            "kill 对应 PID",
            "firewall-cmd --add-rich-rule 阻断 IP",
            "report",
        ],
    },
    {
        "name": "threat-crypto-scan",
        "auto_trigger": True,
        "trigger": "security.monitor_result",
        "filter": {"threat_name": "crypto_miner"},
        "steps": [
            "lsof -i",
            "ps aux | grep crypto",
            "crontab -l",
            "ls /dev/shm/",
            "检查 /var/tmp/ 疑似文件",
            "report",
        ],
    },
    {
        "name": "threat-pipe-download-check",
        "auto_trigger": False,
        "trigger": "security.monitor_result",
        "filter": {"threat_name": "curl_pipe_bash"},
        "steps": [
            "检查 ~/.bashrc 是否被改",
            "检查 /tmp/ 新文件",
            "检查定时任务",
            "report",
        ],
    },
    # ─── 数据窃取/勒索类 ─────────────────────────
    {
        "name": "threat-ransomware-response",
        "auto_trigger": False,
        "trigger": "security.monitor_result",
        "filter": {"threat_name": "ransomware"},
        "steps": [
            "SIGSTOP 冻结进程",
            "find / -mmin -2 -type f",
            "记录受影响文件 hash",
            "btrfs subvolume snapshot -r /（如 Btrfs）",
            "发布 security.alert:ransomware_suspected",
            "report",
        ],
    },
    {
        "name": "threat-btrfs-snapshot-protect",
        "auto_trigger": False,
        "trigger": "security.monitor_result",
        "filter": {"threat_name": "ransomware"},
        "steps": [
            "snapper create（如安装）",
            "检查现有 snapshot 是否被破坏",
            "保护所有 snapshot 不可删除",
            "report",
        ],
    },
    {
        "name": "threat-ssh-audit",
        "auto_trigger": True,
        "trigger": "security.monitor_result",
        "filter": {"threat_name": "ssh_key_steal"},
        "steps": [
            "cat ~/.ssh/authorized_keys",
            "ls -la ~/.ssh/",
            "比对 known_hosts 变化",
            "检查 SSHD 失败登录日志",
            "report",
        ],
    },
    # ─── 持久化类 ───────────────────────────────
    {
        "name": "threat-cron-audit",
        "auto_trigger": True,
        "trigger": "security.monitor_result",
        "filter": {"threat_name": "cron_persistence"},
        "steps": [
            "crontab -l",
            "ls /etc/cron.d/",
            "比对上次 cron hash",
            "报告新增条目",
        ],
    },
    {
        "name": "threat-systemd-audit",
        "auto_trigger": True,
        "trigger": "security.monitor_result",
        "filter": {"threat_name": "systemd_persistence"},
        "steps": [
            "systemctl list-units --state=enabled",
            "find /etc/systemd/system/ -newer timestamp",
            "检查 ExecStart 路径合法性",
            "report",
        ],
    },
    {
        "name": "threat-persistence-sweep",
        "auto_trigger": False,
        "trigger": "security.monitor_result",
        "filter": {"threat_name": "persistence"},
        "steps": [
            "检查 /etc/ld.so.preload",
            "crontab -l",
            "systemctl list-units --state=enabled",
            "ls /etc/init.d/",
            "cat ~/.bashrc ~/.profile",
            "ls ~/.config/autostart/ ~/.config/systemd/user/",
            "一次性清理全部异常条目",
            "重新扫描确认无残留",
            "更新各持久化点 hash 基线",
            "report",
        ],
    },
    # ─── 供应链类 ───────────────────────────────
    {
        "name": "threat-supply-chain-audit",
        "auto_trigger": False,
        "trigger": "security.monitor_result",
        "filter": {"threat_name": "supply_chain"},
        "steps": [
            "记录安装的包名 + 版本",
            "对比已知恶意包清单",
            "检查 postinstall 脚本内容",
            "检查 AUR PKGBUILD（如适用）",
            "audit",
        ],
    },
    # ─── LLM 攻击面 ─────────────────────────────
    {
        "name": "threat-prompt-injection-check",
        "auto_trigger": False,
        "trigger": "security.monitor_result",
        "filter": {"threat_name": "prompt_injection"},
        "steps": [
            "检查用户输入注入模式",
            "检查外部数据源信任分",
            "检查命令参数异常拼接字符",
            "audit",
        ],
    },
    # ─── 审计完整性 ─────────────────────────────
    {
        "name": "threat-audit-integrity-check",
        "auto_trigger": False,
        "trigger": "cron",
        "steps": [
            "验证审计日志 hash 链",
            "验证 HMAC 签名",
            "断链检测 → 阻断高风险操作",
            "report",
        ],
    },
    # ─── 内存执行类 ─────────────────────────────
    {
        "name": "threat-memfd-scan",
        "auto_trigger": True,
        "trigger": "security.monitor_result",
        "filter": {"threat_name": "memfd_exec"},
        "steps": [
            "lsof | grep memfd",
            "检查 /dev/shm/ 内容",
            "检查 /proc/*/maps 匿名内存段",
            "报告 memfd 文件描述符",
        ],
    },
]


def get_workflow_by_name(name: str) -> dict[str, Any] | None:
    """按名称查找威胁工作流定义。"""
    for wf in THREAT_WORKFLOWS:
        if wf["name"] == name:
            return wf
    return None


def get_workflows_by_trigger(trigger: str) -> list[dict[str, Any]]:
    """按触发事件类型查找工作流列表。"""
    return [wf for wf in THREAT_WORKFLOWS if wf.get("trigger") == trigger]


# ─── 剧本 → 可执行 workflow（W1）──────────────────────────────────────────
#
# 下面这些剧本此前是「有数据、没接线」的响应手册：谁都没把它们交给引擎。
# `builtin_workflows()` 把它们编译成 `WorkflowDefV2`，由 `WorkflowRuntime` 注册：
#
# - `trigger` / `filter` → step 的触发器（filter 翻译成条件表达式）
# - 命令式步骤（`crontab -l`）→ `agent_type: shell`，执行经 ToolGateway
#   （策略 / 风险 / 审计 / 脱敏照常生效）
# - 散文式步骤（「比对上次 hash 基线」这种要判断的）→ `agent_type: trm-agent`，
#   交给子 Agent；没有 driver / 没装 Agent 脚本时节点**明确失败**，不装成功
# - `config.enabled`：取证类剧本（`auto_trigger=True`）事件来了自动跑；含处置步骤的剧本
#   默认不武装 —— 处置要人点，不做「半自动处置」
# - 步骤闸门：自动触发只跑**只读取证命令**步骤；要判断的散文步骤不派子 Agent（见 step_kind）
# ─────────────────────────────────────────────────────────────────────────

#: 本地命令步骤（与 workflow_catalog 同值：都是 `agent_type: shell` 这个约定）
SHELL_AGENT = "shell"
#: 需要判断的步骤 → 子 Agent
REVIEW_AGENT = "trm-agent"
STEP_TIMEOUT_SECONDS = 30.0

_CJK_RE = re.compile(r"[⺀-鿿가-힯＀-￯]")
_COMMAND_HEAD_RE = re.compile(r"^[A-Za-z0-9_./~$@-]+$")

#: 剧本里这几个词是「动作代称」（写手册时的简写），不是能跑的命令
PROSE_STEPS = frozenset({"report", "audit"})
# ─── 步骤性质与「自动触发」判据（2026-09-21 定）────────────────────────
#
# 背景：剧本步骤是混合的 —— 命令式步骤（`cat /etc/ld.so.preload`）走网关，散文式步骤
# （「比对上次 hash 基线」/「kill 对应 PID」）派子 Agent。子 Agent 会干什么不由剧本决定，
# 所以「只读剧本」不等于「只读运行」，自动触发必须**按步骤**放行。三种性质：
#
#   auto   —— 只读取证命令：事件自动触发时照跑（仍走网关 / 策略 / 审计）
#   review —— 要判断的散文：自动触发不派子 Agent，留人工
#   action —— 处置（散文含处置动词，或命令不在只读白名单里）：留人工
#
# 看不懂的散文一律当 `action`（保守），新增剧本请让测试来判。

#: 只读取证命令白名单：白名单之外一律不自动跑
READONLY_COMMANDS = frozenset({
    "cat", "ls", "stat", "file", "head", "tail", "sha256sum", "md5sum",
    "find", "grep", "sort", "uniq", "wc",
    "ps", "ss", "lsof", "ip", "who", "w", "id", "uname", "env", "printenv",
    "lsmod", "modinfo", "bpftool", "systemctl", "crontab", "journalctl",
    "df", "du", "getent", "systemd-analyze", "rpm", "dpkg",
})

#: 出现这些参数 → 判为写操作（`find -delete`、`... > file`）
MUTATING_FLAGS = ("-delete", "-exec", "-execdir", "-ok", ">", ">>")

#: 白名单里这几个命令还要看子命令 / 参数才算只读
READONLY_SUBCOMMANDS: dict[str, tuple[str, ...]] = {
    "systemctl": (
        "list-units", "list-unit-files", "list-timers", "status", "show", "is-enabled",
    ),
    "crontab": ("-l",),
    "bpftool": ("list", "show"),
}

#: 散文里的处置动词（命中即 `action`）
RESPONSE_MARKERS = (
    "kill", "pkill", "killall", "firewall", "iptables", "nft ", "sigstop", "冻结", "隔离",
    "阻断", "拦截", "删除", "清理", "恢复", "回滚", "重启", "停止", "禁用", "更新基线",
    "写入", "落盘", "snapper", "snapshot", "创建", "修改", "修复", "加固", "卸载", "安装",
    "启用", "关闭", "开启", "注入",
)

#: 散文里的取证动词（先看处置动词，再看这个；都不命中 = `action`）
REVIEW_MARKERS = (
    "比对", "检查", "审查", "核对", "记录", "汇总", "验证", "评估", "统计", "查看",
    "报告", "列出", "枚举", "清点",
)


def _first_segment(step: str) -> list[str]:
    """取管道第一段的 token（`ps aux | grep x` → `["ps", "aux"]`）。"""
    return (step or "").strip().split("|")[0].split()


def command_head(step: str) -> str:
    """这一步跑的是哪个命令（`/usr/bin/cat` → `cat`；`sudo ls` → `ls`）。"""
    tokens = _first_segment(step)
    if not tokens:
        return ""
    head = tokens[0].split("/")[-1]
    if head == "sudo" and len(tokens) > 1:
        head = tokens[1].split("/")[-1]
    return head


def is_readonly_command(step: str) -> bool:
    """命令式步骤是不是「只读取证」？白名单 + 子命令 + 危险参数三关。"""
    head = command_head(step)
    if not head or head not in READONLY_COMMANDS:
        return False
    tokens = _first_segment(step)
    if any(flag in tokens for flag in MUTATING_FLAGS):
        return False
    subcommands = READONLY_SUBCOMMANDS.get(head)
    if subcommands:
        return any(token in subcommands for token in tokens[1:])
    return True


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(marker in low for marker in markers)


def step_kind(step: str) -> str:
    """这一步算什么：``auto``（取证命令，自动跑）/ ``review``（判断，人工）/ ``action``（处置）。"""
    text = (step or "").strip()
    if text.lower() in PROSE_STEPS:
        return "review"
    if is_local_command(text):
        return "auto" if is_readonly_command(text) else "action"
    if text and _contains_any(text, RESPONSE_MARKERS):
        return "action"
    if _contains_any(text, REVIEW_MARKERS):
        return "review"
    return "action"


def step_runs_automatically(step: str) -> bool:
    """事件自动触发时这一步跑不跑（``auto`` 才跑）。"""
    return step_kind(step) == "auto"


def auto_trigger_workflows() -> list[str]:
    """取证类剧本的名字（`auto_trigger=True`，会被 daemon 武装）。"""
    return [entry["name"] for entry in THREAT_WORKFLOWS if entry.get("auto_trigger")]


def is_local_command(step: str) -> bool:
    """这一步是「能直接跑的本地命令」还是「要判断的散文」？

    判据很土但够用：含中日韩字符 → 散文；首 token 不像命令 → 散文。
    """
    text = (step or "").strip()
    if not text or _CJK_RE.search(text):
        return False
    if text.lower() in PROSE_STEPS:
        return False
    return bool(_COMMAND_HEAD_RE.match(text.split()[0]))


def trigger_condition(entry: dict[str, Any]) -> str:
    """把 `filter` 翻译成 WorkflowDefV2 的条件表达式。"""
    filters = entry.get("filter") or {}
    return " and ".join(
        "payload.get({!r}) == {!r}".format(key, value)
        for key, value in sorted(filters.items())
    )


def to_workflow_def_v2(entry: dict[str, Any]) -> Any:
    """一条威胁响应剧本 → WorkflowDefV2（延迟 import：workflow_engine 较重）。"""
    from .workflow_engine import (
        AgentTask,
        WorkflowDefV2,
        WorkflowStep,
        WorkflowStepCondition,
    )

    name = entry["name"]
    threat = (entry.get("filter") or {}).get("threat_name", "")
    auto_trigger = bool(entry.get("auto_trigger"))
    tasks = [
        AgentTask(
            task_id=f"{name}_step_{index}",
            agent_type=SHELL_AGENT if is_local_command(step) else REVIEW_AGENT,
            instruction=step,
            timeout_seconds=STEP_TIMEOUT_SECONDS,
            # 步骤性质落到节点 config：引擎在事件自动触发的运行里据此放行 / 跳过
            config={"step_kind": step_kind(step), "auto_run": step_runs_automatically(step)},
        )
        for index, step in enumerate(entry.get("steps") or [])
    ]
    return WorkflowDefV2(
        id=name,
        name=name,
        description=f"内置威胁响应剧本（{threat or '通用'}）：{len(tasks)} 步",
        steps=[WorkflowStep(
            trigger=WorkflowStepCondition(
                event_type=entry.get("trigger", ""),
                condition=trigger_condition(entry),
            ),
            execute=tasks,
        )],
        config={
            "enabled": auto_trigger,
            "builtin": True,
            "auto_trigger": auto_trigger,
            "threat_name": threat,
            "source": "threat_workflows",
            "note": (
                "取证类剧本：事件来了自动跑取证命令步骤（仍走网关 / 策略 / 审计），"
                "要判断的散文步骤自动触发时不派子 Agent，留 trm workflow run 人工跑"
                if auto_trigger else
                "处置类 / 无自动步骤的剧本：默认不武装（处置要人点），"
                "trm workflow run <id> 手动跑全流程"
            ),
        },
    )


def builtin_workflows() -> list[Any]:
    """全部内置剧本（WorkflowDefV2 列表）。"""
    return [to_workflow_def_v2(entry) for entry in THREAT_WORKFLOWS]
