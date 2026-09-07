"""威胁应对工作流预注册库。

每个威胁对应一个应对工作流定义（纯 JSON 格式，无 LLM 参与）。
通过 Event Bus 的 workflow.trigger 事件触发，WorkflowEngine 执行。
"""

from __future__ import annotations

from typing import Any

# ─── 威胁工作流结构 ───────────────────────────────
# name:     工作流名称，与 ThreatMatch.workflow_name 对应
# trigger:  触发器事件类型
# filter:   可选的事件 payload 过滤条件
# steps:    执行步骤列表（字符串命令或结构化操作）
# ─────────────────────────────────────────────────

THREAT_WORKFLOWS: list[dict[str, Any]] = [
    # ─── 权限逃逸类 ─────────────────────────────
    {
        "name": "threat-prelink-check",
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
