"""Step 7 验证：trimum Phase 1 MVP 的 10 个典型场景（unittest + mock）。

覆盖（对应 PRD 验收标准 5 + 代码审查回归）：
1. 低风险自动执行（磁盘查询）
2. 中风险确认执行（删除 /tmp 缓存）
3. 高风险确认 + 警告 + 审计（系统日志清理；L-6 审计不含 explanation）
4. 关键风险直接拒绝（格式化磁盘）
5. 管道输入模式（stdin 上下文 + 解释模式）
6. C-1 回归（转义/引号/链式命令的策略拦截 + normalize_command）
7. H-1 平台安全符号（GBK 终端不崩溃）
8. H-2 fallback 意图方向（查看 tmp 不触发删除）
9. dry-run 模式（不弹确认、不执行）
10. 策略正则词边界（cat /etc/passwd 不误判；fdisk 只读列表放行）

运行：python test_scenarios.py -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from trimum_mvp import cli
from trimum_mvp.executor import Executor
from trimum_mvp.output import (
    _SafeConsoleFile,
    _select_symbols,
    _supports_unicode,
)
from trimum_mvp.planner import CommandPlan, Planner
from trimum_mvp.policy import PolicyEngine, normalize_command

POLICY_FILE = Path(__file__).resolve().parent / "policy.yaml"


class FakeLLM:
    """mock LLM：返回预设 JSON，记录最近一次 messages。"""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.last_messages: list[dict] = []

    def chat(self, messages: list[dict], stream: bool = False, on_chunk=None) -> str:
        self.last_messages = messages
        return self.reply


def plan_json(
    commands: list[str],
    risk: str,
    plan: list[str] | None = None,
    explanation: str = "说明",
) -> str:
    """构造 LLM 返回的 JSON 计划字符串。"""
    return json.dumps(
        {
            "plan": plan if plan is not None else ["步骤 1"],
            "commands": commands,
            "risk": risk,
            "explanation": explanation,
        },
        ensure_ascii=False,
    )


class _GBKStream:
    """模拟 cp936/GBK 终端：写入不可编码字符时抛 UnicodeEncodeError。"""

    encoding = "cp936"

    def __init__(self) -> None:
        self.data = ""

    def write(self, text: str) -> int:
        try:
            text.encode("cp936")
        except UnicodeEncodeError:
            raise UnicodeEncodeError("cp936", text, 0, 1, "simulated")
        self.data += text
        return len(text)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return True

    def fileno(self) -> int:
        raise OSError


class TestLowRiskAutoExecute(unittest.TestCase):
    """场景 1：低风险命令自动执行，不弹确认。"""

    def test_disk_space_query_auto_executes(self) -> None:
        llm = FakeLLM(plan_json(["df -h"], "low", explanation="查看磁盘使用情况"))
        plan = Planner(llm).plan("查看磁盘空间")
        self.assertEqual(plan.commands, ["df -h"])

        confirmed: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            executor = Executor(
                policy=PolicyEngine(POLICY_FILE),
                confirm_callback=lambda q: confirmed.append(q) or True,
                audit_log_path=Path(tmp) / "audit.log",
            )
            with patch(
                "trimum_mvp.executor.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout="Filesystem OK", stderr=""),
            ) as run:
                results = executor.execute(plan)
        self.assertEqual(len(confirmed), 0, "低风险不应请求确认")
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].executed)
        self.assertEqual(results[0].returncode, 0)
        run.assert_called_once()


class TestMediumRiskConfirmExecute(unittest.TestCase):
    """场景 2：中风险命令确认后执行。"""

    def test_delete_tmp_cache_requires_confirm(self) -> None:
        llm = FakeLLM(plan_json(["rm -rf /tmp/*"], "medium", explanation="清理缓存"))
        plan = Planner(llm).plan("清理 /tmp 缓存")

        confirmed: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            executor = Executor(
                policy=PolicyEngine(POLICY_FILE),
                confirm_callback=lambda q: confirmed.append(q) or True,
                audit_log_path=Path(tmp) / "audit.log",
            )
            with patch(
                "trimum_mvp.executor.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
            ) as run:
                results = executor.execute(plan)
        self.assertEqual(len(confirmed), 1, "中风险应请求确认")
        self.assertTrue(results[0].executed)
        run.assert_called_once()

    def test_medium_cancelled_when_user_says_no(self) -> None:
        plan = CommandPlan(
            plan=["清理缓存"], commands=["rm -rf /tmp/*"], risk="medium", explanation=""
        )
        with tempfile.TemporaryDirectory() as tmp:
            executor = Executor(
                policy=PolicyEngine(POLICY_FILE),
                confirm_callback=lambda q: False,
                audit_log_path=Path(tmp) / "audit.log",
            )
            with patch("trimum_mvp.executor.subprocess.run") as run:
                results = executor.execute(plan)
        self.assertFalse(results[0].executed)
        self.assertEqual(results[0].message, "用户取消（User cancelled）")
        run.assert_not_called()


class TestHighRiskAudit(unittest.TestCase):
    """场景 3：高风险确认 + 审计日志（L-6：日志不含 explanation）。"""

    def test_system_log_cleanup_audited(self) -> None:
        llm = FakeLLM(
            plan_json(["journalctl --vacuum-time=7d"], "high", explanation="清理系统日志")
        )
        plan = Planner(llm).plan("清理系统日志")

        confirmed: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            audit_path = Path(tmp) / "audit.log"
            executor = Executor(
                policy=PolicyEngine(POLICY_FILE),
                confirm_callback=lambda q: confirmed.append(q) or True,
                audit_log_path=audit_path,
            )
            with patch(
                "trimum_mvp.executor.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
            ) as run:
                results = executor.execute(plan)
            log = audit_path.read_text(encoding="utf-8")
        self.assertEqual(len(confirmed), 1, "高风险应请求确认")
        self.assertTrue(results[0].executed)
        self.assertIn("status=confirmed", log)
        self.assertIn("risk=high", log)
        self.assertIn("journalctl", log)
        self.assertNotIn("explanation=", log, "L-6：审计日志不应包含 explanation（隐私）")
        run.assert_called_once()


class TestCriticalDenied(unittest.TestCase):
    """场景 4：关键风险直接拒绝，不执行、不确认。"""

    def test_format_disk_denied(self) -> None:
        llm = FakeLLM(plan_json(["mkfs.ext4 /dev/sda"], "critical", explanation="格式化"))
        plan = Planner(llm).plan("格式化磁盘")

        def fail_if_called(question: str) -> bool:
            self.fail("critical 不应触发确认回调")

        with tempfile.TemporaryDirectory() as tmp:
            executor = Executor(
                policy=PolicyEngine(POLICY_FILE),
                confirm_callback=fail_if_called,
                audit_log_path=Path(tmp) / "audit.log",
            )
            with patch("trimum_mvp.executor.subprocess.run") as run:
                results = executor.execute(plan)
        self.assertFalse(results[0].executed)
        self.assertEqual(results[0].action, "deny")
        run.assert_not_called()


class TestPipeInputMode(unittest.TestCase):
    """场景 5：管道输入作为上下文；解释模式下不执行命令。"""

    def test_read_pipe_input_returns_stdin_content(self) -> None:
        fake_stdin = SimpleNamespace(isatty=lambda: False, read=lambda: "Traceback ...\n")
        with patch("trimum_mvp.cli.sys.stdin", fake_stdin):
            self.assertEqual(cli.read_pipe_input(), "Traceback ...")

    def test_read_pipe_input_empty_on_tty(self) -> None:
        fake_stdin = SimpleNamespace(isatty=lambda: True, read=lambda: "x")
        with patch("trimum_mvp.cli.sys.stdin", fake_stdin):
            self.assertEqual(cli.read_pipe_input(), "")

    def test_pipe_content_passed_as_context_to_llm(self) -> None:
        llm = FakeLLM(plan_json([], "low", explanation="解释输入内容"))
        planner = Planner(llm)
        plan = planner.plan("解释这个报错", pipe_input="Traceback (most recent call last)")
        self.assertEqual(plan.commands, [], "解释模式不应生成命令")
        user_message = llm.last_messages[-1]["content"]
        self.assertIn("Traceback (most recent call last)", user_message)


class TestC1EscapedCommands(unittest.TestCase):
    """场景 6（C-1 回归）：转义/引号/链式命令不能绕过策略引擎。"""

    def setUp(self) -> None:
        self.policy = PolicyEngine(POLICY_FILE)

    def test_escaped_space_denied(self) -> None:
        decision = self.policy.evaluate(r"rm\ -rf\ /")
        self.assertTrue(decision.denied)
        self.assertEqual(decision.risk, "critical")

    def test_quoted_root_denied(self) -> None:
        decision = self.policy.evaluate('rm -rf "/"')
        self.assertTrue(decision.denied)

    def test_chained_fork_bomb_denied(self) -> None:
        decision = self.policy.evaluate("echo x; :(){ :|:& };:")
        self.assertTrue(decision.denied)

    def test_dd_urandom_denied(self) -> None:
        decision = self.policy.evaluate("dd if=/dev/urandom of=/dev/sda")
        self.assertTrue(decision.denied)

    def test_pipe_chain_rm_denied(self) -> None:
        decision = self.policy.evaluate("ls | rm -rf /")
        self.assertTrue(decision.denied)

    def test_normalize_command(self) -> None:
        self.assertEqual(normalize_command(r"rm\ -rf\ /"), ["rm -rf /"])
        self.assertEqual(
            normalize_command("echo x; :(){ :|:& };:"),
            ["echo x", ":(){ :|:& }", ":"],
        )
        self.assertEqual(normalize_command("ls '/tmp/a b'"), ["ls /tmp/a b"])
        self.assertEqual(normalize_command("a && b || c | d"), ["a", "b", "c", "d"])

    def test_executor_denies_escaped_command(self) -> None:
        plan = CommandPlan(
            plan=["删除根目录"],
            commands=[r"rm\ -rf\ /"],
            risk="low",  # LLM 谎报 low 也不应被采纳
            explanation="",
        )
        with tempfile.TemporaryDirectory() as tmp:
            executor = Executor(
                policy=self.policy,
                audit_log_path=Path(tmp) / "audit.log",
            )
            with patch("trimum_mvp.executor.subprocess.run") as run:
                results = executor.execute(plan)
        self.assertFalse(results[0].executed)
        self.assertEqual(results[0].action, "deny")
        run.assert_not_called()


class TestH1WindowsSafeSymbols(unittest.TestCase):
    """场景 7（H-1）：GBK 终端不崩溃，符号自动回退 ASCII。"""

    def test_cp936_falls_back_to_ascii(self) -> None:
        self.assertEqual(
            _select_symbols("cp936"), {"warn": "[!]", "ok": "[OK]", "err": "[X]"}
        )

    def test_utf8_keeps_unicode_symbols(self) -> None:
        self.assertEqual(_select_symbols("utf-8")["warn"], "⚠")

    def test_none_encoding_uses_ascii(self) -> None:
        self.assertEqual(_select_symbols(None)["ok"], "[OK]")
        self.assertFalse(_supports_unicode(None))

    def test_safe_console_file_writes_gbk_without_crash(self) -> None:
        stream = _GBKStream()
        safe = _SafeConsoleFile(stream)
        safe.write("⚠ 高危操作 [OK]\n")  # ⚠ 无法编码 -> 替换为 '?'，不抛异常
        self.assertIn("?", stream.data)
        self.assertIn("[OK]", stream.data)

    def test_executor_report_safe_on_gbk_stream(self) -> None:
        from rich.console import Console as RichConsole

        from trimum_mvp import output as out_mod
        from trimum_mvp.executor import ExecutionResult

        stream = _GBKStream()
        old_console = out_mod.console
        try:
            out_mod.console = RichConsole(file=_SafeConsoleFile(stream), width=100)
            executor = Executor(policy=PolicyEngine(POLICY_FILE))
            result = ExecutionResult(
                command="df -h", risk="low", action="auto", executed=True, returncode=0
            )
            executor._report(result)  # 不应抛 UnicodeEncodeError
        finally:
            out_mod.console = old_console
        self.assertIn("df -h", stream.data)


class TestH2FallbackIntent(unittest.TestCase):
    """场景 8（H-2）：只读意图不被误判为删除动作。"""

    def test_view_tmp_is_read_only(self) -> None:
        plan = Planner._fallback_plan("看看 tmp 目录里有什么")
        self.assertEqual(plan.commands, ["ls -la"])
        self.assertEqual(plan.risk, "low")

    def test_clean_tmp_is_medium_delete(self) -> None:
        plan = Planner._fallback_plan("清理 /tmp 缓存")
        self.assertEqual(plan.commands, ["rm -rf /tmp/*"])
        self.assertEqual(plan.risk, "medium")

    def test_view_logs_is_read_only(self) -> None:
        plan = Planner._fallback_plan("查看日志")
        self.assertEqual(plan.commands, ["journalctl -n 50"])
        self.assertEqual(plan.risk, "low")

    def test_clean_logs_is_high(self) -> None:
        plan = Planner._fallback_plan("清理日志")
        self.assertEqual(plan.commands, ["journalctl --vacuum-time=7d"])
        self.assertEqual(plan.risk, "high")

    def test_tmp_word_boundary(self) -> None:
        # 'temporary' 不应命中 \btmp\b
        plan = Planner._fallback_plan("temporary 目录")
        self.assertNotEqual(plan.commands, ["rm -rf /tmp/*"])

    def test_m3_string_plan_field_not_iterated(self) -> None:
        plan = CommandPlan.from_dict(
            {"plan": "查看磁盘", "commands": "df -h", "risk": "low", "explanation": ""}
        )
        self.assertIsNotNone(plan)
        self.assertEqual(plan.plan, [])
        self.assertEqual(plan.commands, [])


class TestDryRun(unittest.TestCase):
    """场景 9：dry-run 不弹确认、不执行。"""

    def test_medium_dry_run_skips_confirm(self) -> None:
        plan = CommandPlan(
            plan=["清理缓存"], commands=["rm -rf /tmp/*"], risk="medium", explanation=""
        )
        confirmed: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            executor = Executor(
                policy=PolicyEngine(POLICY_FILE),
                dry_run=True,
                confirm_callback=lambda q: confirmed.append(q) or True,
                audit_log_path=Path(tmp) / "audit.log",
            )
            with patch("trimum_mvp.executor.subprocess.run") as run:
                results = executor.execute(plan)
        self.assertEqual(len(confirmed), 0, "dry-run 不应请求确认")
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].executed)
        self.assertIn("dry-run", results[0].message)
        run.assert_not_called()

    def test_low_dry_run_not_executed(self) -> None:
        plan = CommandPlan(
            plan=["查看磁盘"], commands=["df -h"], risk="low", explanation=""
        )
        with tempfile.TemporaryDirectory() as tmp:
            executor = Executor(
                policy=PolicyEngine(POLICY_FILE),
                dry_run=True,
                audit_log_path=Path(tmp) / "audit.log",
            )
            with patch("trimum_mvp.executor.subprocess.run") as run:
                results = executor.execute(plan)
        self.assertFalse(results[0].executed)
        run.assert_not_called()


class TestPolicyWordBoundaries(unittest.TestCase):
    """场景 10：策略正则词边界（M-1）与磁盘工具规则（C-2）。"""

    def setUp(self) -> None:
        self.policy = PolicyEngine(POLICY_FILE)

    def test_cat_passwd_is_low(self) -> None:
        decision = self.policy.evaluate("cat /etc/passwd")
        self.assertEqual(decision.risk, "low")
        self.assertEqual(decision.action, "auto")

    def test_passwd_command_is_high(self) -> None:
        decision = self.policy.evaluate("passwd")
        self.assertEqual(decision.risk, "high")

    def test_useradd_is_high(self) -> None:
        decision = self.policy.evaluate("sudo useradd bob")
        self.assertEqual(decision.risk, "high")

    def test_df_is_auto(self) -> None:
        decision = self.policy.evaluate("df -h")
        self.assertEqual(decision.action, "auto")

    def test_ls_is_auto(self) -> None:
        decision = self.policy.evaluate("ls -la /tmp")
        self.assertEqual(decision.action, "auto")

    def test_fdisk_list_allowed(self) -> None:
        decision = self.policy.evaluate("fdisk -l /dev/sda")
        self.assertFalse(decision.denied)

    def test_fdisk_write_denied(self) -> None:
        decision = self.policy.evaluate("fdisk /dev/sda")
        self.assertTrue(decision.denied)

    def test_wipefs_denied(self) -> None:
        decision = self.policy.evaluate("wipefs -a /dev/sda")
        self.assertTrue(decision.denied)

    def test_parted_mklabel_denied(self) -> None:
        decision = self.policy.evaluate("parted /dev/sda mklabel gpt")
        self.assertTrue(decision.denied)

    def test_evaluate_many_deny_wins(self) -> None:
        decision = self.policy.evaluate_many(["ls -la", "mkfs.ext4 /dev/sda"])
        self.assertTrue(decision.denied)

    def test_m6_rule_error_reports_index(self) -> None:
        import tempfile as _tf

        with _tf.TemporaryDirectory() as tmp:
            bad_yaml = Path(tmp) / "bad.yaml"
            bad_yaml.write_text(
                "rules:\n  - risk: high\n  - pattern: 'ls'\n  - pattern: 'rm'\n    risk: bad\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError) as ctx:
                PolicyEngine(bad_yaml)
            message = str(ctx.exception)
            self.assertIn("Rule #", message)


if __name__ == "__main__":
    unittest.main(verbosity=2)