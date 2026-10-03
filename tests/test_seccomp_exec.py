"""S3 seccomp 三档的用例（Windows 上也能跑全 —— 逻辑与"真机行为"分开测）。

两层测法：
* **逻辑层**：注入假的 capability / resolver / libseccomp 句柄，把档位解析、规则构建、
  施加调用序、失败路径全在 Windows 上跑完（真机上跑得到的只是"能拦"，逻辑才是容易错的地方）；
* **真机层**：Linux 专属用例（本机 Windows 上 skip），用子进程做端到端对照。
  判别器只选**正常会成功**的 syscall（`ptrace(TRACEME)` / `io_uring_setup`），
  因为 `bpf` / `mount` / `setns` 非特权本来就失败，拿它们验收会得出"拦住了"的假结论。
"""

from __future__ import annotations

import ast
import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from trimum_core import sandbox_exec, seccomp_exec
from trimum_core.models import AuditEvent, ExecuteResponse

LINUX = sys.platform.startswith("linux")
#: 导入根（PYTHONPATH 要指到这里）——踩过的坑：指到 trimum_core 里，子进程会
#: 静默退回 site-packages 的 editable 路径（另一棵树），于是「测试绿了、代码还是旧的」。
SRC = Path(__file__).resolve().parents[1] / "src"
#: 源码目录（静态守卫逐个文件扫这里）
PKG = SRC / "trimum_core"


@pytest.fixture(autouse=True)
def _isolate_seccomp_cache():
    """能力探测与库句柄都是进程级缓存，用例之间必须隔离。"""
    seccomp_exec.reset_cache()
    yield
    seccomp_exec.reset_cache()


def _supported(api_level: int = 6) -> seccomp_exec.SeccompCapability:
    return seccomp_exec.SeccompCapability(True, api_level, "libseccomp.so.2", f"api_level={api_level}")


def _unsupported() -> seccomp_exec.SeccompCapability:
    return seccomp_exec.SeccompCapability(False, 0, "", "platform:win32")


def _fake_resolver(table: dict[str, int] | None = None, *, default: int = 500):
    """稳定的假解析器：表里查得到就用表，查不到给一个自增的假号。"""
    known = dict(table or {})
    counter = {"n": default}

    def resolve(name: str) -> int:
        if name in known:
            return known[name]
        counter["n"] += 1
        known[name] = counter["n"]
        return known[name]

    return resolve


def _num(value: Any) -> int:
    """ctypes 标量 → int（假的 C 函数拿到的应该是数值本身）。

    Windows 上 ``ctypes.c_uint32`` 是 ``c_ulong`` 的别名，直接 ``int()`` 会把它当
    bytes 解析而炸（``invalid literal for int() ... b'\\x00\\x00\\xff\\x7f'``）。
    """
    return int(getattr(value, "value", value))


def _manifest(name: str = "third-party", **sandbox: Any):
    """最小合法的 ``AgentManifest``（``version`` / ``capabilities`` 是必填字段）。"""
    from trimum_core.models import AgentManifest

    return AgentManifest(name=name, version="1", capabilities=[], sandbox=dict(sandbox))


@pytest.fixture
def landlock_ok(monkeypatch):
    """假装内核支持 Landlock（abi=4）：让 ``plan_for`` 走「会施加」的那条路。

    本机（Windows）默认走 ``unsupported``，那条路上 seccomp 只构建、不判失败，
    测不到「两个状态各记各的」。
    """
    monkeypatch.setattr(
        sandbox_exec, "_probe_uncached", lambda: sandbox_exec.SandboxCapability(True, 4, "abi=4")
    )
    sandbox_exec.reset_cache()
    yield
    sandbox_exec.reset_cache()


@pytest.fixture
def seccomp_ok(monkeypatch):
    """假 seccomp 能力 + 假解析器：Windows 上也能把 seccomp 的逻辑跑全。"""
    monkeypatch.setattr(seccomp_exec, "probe", lambda refresh=False: _supported())
    monkeypatch.setattr(seccomp_exec, "libc_library", lambda: None)
    monkeypatch.setattr(seccomp_exec, "_resolver_default", lambda name, lib: 100)


class _FakeLib:
    """假 libseccomp：记录调用序，并可指定某一步失败。

    函数用 **lambda 属性**而不是绑定方法 —— ctypes 的真实对象允许 `fn.argtypes = ...`，
    绑定方法不行，而我们要断言"调用前切换了 argtypes"。
    """

    def __init__(self, *, init_result: int = 1234, rule_rc: int = 0, load_rc: int = 0) -> None:
        self.calls: list[tuple] = []
        self.seccomp_init = lambda action: (self.calls.append(("init", _num(action))), init_result)[1]
        self.seccomp_load = lambda ctx: (self.calls.append(("load",)), load_rc)[1]
        self.seccomp_release = lambda ctx: self.calls.append(("release",))
        self.seccomp_rule_add = lambda *args: (
            self.calls.append(("rule_add", args)),
            rule_rc,
        )[1]


class TestCapability:
    def test_non_linux_is_unsupported_not_silent_pass(self):
        if LINUX:
            pytest.skip("这条只针对非 Linux")
        capability = seccomp_exec.probe()
        assert capability.supported is False
        assert "platform:" in capability.reason
        assert "unsupported" in capability.summary()

    def test_probe_is_cached_and_resetable(self, monkeypatch):
        calls = {"n": 0}

        def fake_probe():
            calls["n"] += 1
            return _supported()

        monkeypatch.setattr(seccomp_exec, "_probe_uncached", fake_probe)
        seccomp_exec.reset_cache()
        assert seccomp_exec.probe().supported is True
        seccomp_exec.probe()
        assert calls["n"] == 1
        seccomp_exec.reset_cache()
        seccomp_exec.probe()
        assert calls["n"] == 2

    @pytest.mark.skipif(not LINUX, reason="libseccomp 只在 Linux 上")
    def test_linux_reports_api_level(self):
        capability = seccomp_exec.probe(refresh=True)
        assert capability.supported is True
        assert capability.api_level >= 1
        # 版本号走 ctypes 读不出来（真机实测），所以口径是 API level 而不是版本
        assert "api_level=" in capability.summary()


class TestNormalizeProfile:
    @pytest.mark.parametrize(
        ("raw", "want"),
        [
            ("l1", "l1"),
            ("L1", "l1"),
            ("L1_standard", "l1"),
            ("standard", "l1"),
            ("strict", "strict"),
            ("L2_restricted", "strict"),
            ("L3_jail", "strict"),
            ("jail", "strict"),
            ("off", "off"),
            ("L0_unrestricted", "off"),
            ("none", "off"),
            ("  STRICT  ", "strict"),
            ("L3-Jail", "strict"),
        ],
    )
    def test_aliases(self, raw, want):
        assert seccomp_exec.normalize_profile(raw) == want

    @pytest.mark.parametrize("raw", ["banana", "", "   ", None, "L9"])
    def test_unknown(self, raw):
        assert seccomp_exec.normalize_profile(raw) is None


class TestBuildPlan:
    def test_l1_default_is_denylist(self):
        plan = seccomp_exec.build_plan("l1", resolver=_fake_resolver(), capability=_supported())
        assert plan.state == "l1"
        assert plan.whitelist is False
        assert plan.default_action == seccomp_exec.SCMP_ACT_ALLOW
        names = {rule.name for rule in plan.rules}
        for dangerous in ("bpf", "mount", "ptrace", "setns", "init_module", "io_uring_setup"):
            assert dangerous in names
        assert plan.denied >= 25  # 内置清单是"危险内核面"整段，不是三五条
        assert plan.allowed == 0

    def test_default_profile_is_l1(self):
        plan = seccomp_exec.build_plan(None, resolver=_fake_resolver(), capability=_supported())
        assert plan.profile == "l1"

    def test_off_has_no_rules(self):
        plan = seccomp_exec.build_plan("off", resolver=_fake_resolver(), capability=_supported())
        assert plan.state == "off"
        assert plan.rules == []
        assert plan.enforcing is False

    def test_unknown_profile_is_failed_and_explained(self):
        plan = seccomp_exec.build_plan("banana", resolver=_fake_resolver(), capability=_supported())
        assert plan.state == "banana:failed"
        assert plan.rules == []
        assert any("未知的 seccomp 档位" in note for note in plan.notes)

    def test_unsupported_platform_does_not_assemble_rules(self):
        plan = seccomp_exec.build_plan("strict", resolver=_fake_resolver(), capability=_unsupported())
        assert plan.state == "unsupported"
        assert plan.rules == []
        assert plan.summary().startswith("unsupported")

    def test_strict_blocks_network_by_address_family(self):
        plan = seccomp_exec.build_plan("strict", resolver=_fake_resolver({"socket": 41}), capability=_supported())
        socket_rules = [rule for rule in plan.rules if rule.name == "socket"]
        assert {rule.arg_value for rule in socket_rules} == {2, 10, 17, 16}  # INET / INET6 / PACKET / NETLINK
        assert all(rule.arg_index == 0 for rule in socket_rules)
        assert all(rule.action != seccomp_exec.SCMP_ACT_ALLOW for rule in socket_rules)
        # AF_UNIX(1) **不在**拦截名单里 —— 子 Agent 的 RPC 靠它
        assert 1 not in {rule.arg_value for rule in socket_rules}

    def test_strict_adds_its_own_blocklist(self):
        plan = seccomp_exec.build_plan("strict", resolver=_fake_resolver(), capability=_supported())
        names = {rule.name for rule in plan.rules}
        assert "pidfd_getfd" in names
        assert "process_madvise" in names

    def test_declared_allow_switches_strict_to_whitelist(self):
        plan = seccomp_exec.build_plan(
            "strict", allow=["openat", "read"], resolver=_fake_resolver(), capability=_supported()
        )
        assert plan.whitelist is True
        assert plan.default_action == (seccomp_exec.SCMP_ACT_ERRNO | seccomp_exec.EPERM)
        allowed = {rule.name for rule in plan.rules if rule.action == seccomp_exec.SCMP_ACT_ALLOW}
        assert {"openat", "read"} <= allowed
        assert allowed >= set(seccomp_exec.WHITELIST_BASELINE)
        # 白名单模式下不该再有"拦截规则"（默认就拒了）
        assert all(rule.action == seccomp_exec.SCMP_ACT_ALLOW for rule in plan.rules)
        assert any("白名单模式" in note for note in plan.notes)

    def test_declared_allow_on_l1_is_ignored_with_note(self):
        plan = seccomp_exec.build_plan(
            "l1", allow=["clone"], resolver=_fake_resolver(), capability=_supported()
        )
        assert plan.whitelist is False
        assert all(rule.name != "clone" for rule in plan.rules)
        assert any("只在 strict 档有效" in note for note in plan.notes)

    def test_declared_block_is_added(self):
        plan = seccomp_exec.build_plan(
            "l1", block=["clone3"], resolver=_fake_resolver(), capability=_supported()
        )
        rules = [rule for rule in plan.rules if rule.name == "clone3"]
        assert len(rules) == 1
        assert rules[0].action != seccomp_exec.SCMP_ACT_ALLOW

    def test_duplicate_rules_are_deduped(self):
        # `ptrace` 既在声明里又在内置清单里 —— 只应留一条
        plan = seccomp_exec.build_plan(
            "l1", block=["ptrace"], resolver=_fake_resolver(), capability=_supported()
        )
        assert len([rule for rule in plan.rules if rule.name == "ptrace"]) == 1

    def test_unknown_syscall_names_are_reported_not_fatal(self):
        def resolver(name: str) -> int:
            if name == "poweroff":
                return -1
            if name == "swapcontext":
                return -10190
            return 100

        plan = seccomp_exec.build_plan(
            "l1", block=["poweroff", "swapcontext"], resolver=resolver, capability=_supported()
        )
        assert plan.unknown == ["poweroff", "swapcontext"]
        assert all(rule.name not in ("poweroff", "swapcontext") for rule in plan.rules)
        assert plan.state == "l1"  # 不因为一两个名字解析不了就判失败

    def test_all_names_unknown_is_failed(self):
        plan = seccomp_exec.build_plan("l1", resolver=lambda name: -1, capability=_supported())
        assert plan.state == "l1:failed"
        assert plan.rules == []

    def test_documented_clist_drops_non_syscalls(self):
        """§7.2 清单里的 `swapcontext`（libc 函数）与 `poweroff`（命令）**不该**在内置清单里。"""
        assert "swapcontext" not in seccomp_exec.KERNEL_BLOCK
        assert "poweroff" not in seccomp_exec.KERNEL_BLOCK
        assert "reboot" in seccomp_exec.KERNEL_BLOCK  # 这个是真的 syscall

    def test_summary_and_dict_are_audit_ready(self):
        plan = seccomp_exec.build_plan("strict", resolver=_fake_resolver(), capability=_supported())
        assert "strict" in plan.summary() and "mode=" in plan.summary()
        data = plan.as_dict()
        for key in ("profile", "state", "mode", "deny", "allow", "unknown"):
            assert key in data
        assert data["mode"] == "denylist"

class TestApplyCurrent:
    def _plan(self, profile: str = "l1", **kwargs):
        return seccomp_exec.build_plan(
            profile, resolver=_fake_resolver({"ptrace": 101, "bpf": 321}), capability=_supported(), **kwargs
        )

    def test_call_sequence_is_init_rules_load_release(self):
        lib = _FakeLib()
        plan = self._plan()
        seccomp_exec.apply_current(plan, lib=lib)
        kinds = [call[0] for call in lib.calls]
        assert kinds[0] == "init"
        assert kinds[-1] == "release"
        assert kinds[-2] == "load"
        assert kinds.count("rule_add") == len(plan.rules)

    def test_arg_filtered_rule_carries_scmp_arg_cmp(self):
        lib = _FakeLib()
        plan = self._plan("strict")
        seccomp_exec.apply_current(plan, lib=lib)
        arg_calls = [call for call in lib.calls if call[0] == "rule_add" and len(call[1]) == 5]
        assert arg_calls, "按地址族的 socket 规则必须带上参数比较"
        struct = arg_calls[0][1][4]
        assert isinstance(struct, seccomp_exec._ScmpArgCmp)
        assert struct.arg == 0  # SCMP_A0
        # SCMP_CMP_EQ **是 4 不是 0**（enum 从 _SCMP_CMP_MIN=0 起算）；填 0 libseccomp 认非法算子
        assert struct.op == seccomp_exec._SCMP_CMP_EQ == 4
        assert struct.datum_a in {2, 10, 16, 17}
        # 两条原型之间必须切换 argtypes，否则 ctypes 会因为"参数多一个"直接拒掉
        assert lib.seccomp_rule_add.argtypes is not None

    def test_load_failure_raises_and_still_releases(self):
        lib = _FakeLib(load_rc=-1)
        plan = self._plan()
        with pytest.raises(seccomp_exec.SeccompError) as info:
            seccomp_exec.apply_current(plan, lib=lib)
        assert "seccomp_load" in str(info.value)
        assert ("release",) in lib.calls

    def test_rule_add_failure_raises(self):
        lib = _FakeLib(rule_rc=-22)
        plan = self._plan()
        with pytest.raises(seccomp_exec.SeccompError) as info:
            seccomp_exec.apply_current(plan, lib=lib)
        assert "seccomp_rule_add" in str(info.value)
        assert ("release",) in lib.calls

    def test_init_failure_raises(self):
        lib = _FakeLib(init_result=0)
        plan = self._plan()
        with pytest.raises(seccomp_exec.SeccompError):
            seccomp_exec.apply_current(plan, lib=lib)

    def test_empty_plan_refuses_to_apply(self):
        plan = seccomp_exec.build_plan("off", resolver=_fake_resolver(), capability=_supported())
        with pytest.raises(seccomp_exec.SeccompError):
            seccomp_exec.apply_current(plan, lib=_FakeLib())

    def test_error_carries_state_for_audit(self):
        plan = self._plan()
        try:
            seccomp_exec.apply_current(plan, lib=_FakeLib(load_rc=-1))
        except seccomp_exec.SeccompError as exc:
            assert exc.state == plan.state
            assert exc.plan is plan


class TestSandboxExecWiring:
    """S3 是**接在** S2 的档案上的：两个状态各记各的，但共用一个 fail-closed 开关。"""

    def test_plan_for_attaches_seccomp_plan(self, seccomp_ok):
        plan = sandbox_exec.plan_for(None, mode="workspace-write")
        assert plan.seccomp is not None
        assert plan.seccomp.state == "l1"
        assert plan.seccomp_state == "l1"

    def test_off_turns_both_halves_off(self, seccomp_ok):
        plan = sandbox_exec.plan_for(None, mode="off")
        assert plan.state == "off"
        assert plan.seccomp.state == "off"
        assert plan.seccomp.profile == "off"
        assert plan.seccomp.rules == []

    def test_env_overrides_and_manifest_can_only_tighten(self, seccomp_ok, monkeypatch):
        monkeypatch.setenv(sandbox_exec.ENV_SECCOMP, "l1")
        loose = sandbox_exec.plan_for(None, mode="workspace-write")
        assert loose.seccomp.profile == "l1"

        tight = sandbox_exec.plan_for(
            {"agent_manifest": _manifest(seccomp_profile="strict")}, mode="workspace-write"
        )
        assert tight.seccomp.profile == "strict"

        loosening = sandbox_exec.plan_for(
            {"agent_manifest": _manifest(seccomp_profile="off")}, mode="workspace-write"
        )
        assert loosening.seccomp.profile == "l1", "包不许把 seccomp 放回 off"

    def test_manifest_extra_syscalls_are_ignored(self, seccomp_ok):
        manifest = _manifest(seccomp_profile="strict", extra_syscalls=["bpf"])
        plan = sandbox_exec.plan_for({"agent_manifest": manifest}, mode="workspace-write")
        # 白名单模式没被打开（包的 allow 被忽略），bpf 仍在拦截清单里
        assert plan.seccomp.whitelist is False
        assert "bpf" in {
            rule.name for rule in plan.seccomp.rules if rule.action != seccomp_exec.SCMP_ACT_ALLOW
        }

    def test_unknown_seccomp_profile_blocks_spawn(self, landlock_ok, seccomp_ok):
        plan = sandbox_exec.plan_for(None, mode="workspace-write", seccomp_profile="banana")
        assert any("未知的 seccomp 档位" in item for item in plan.blockers)
        assert plan.state.endswith(":failed")
        assert plan.seccomp.state == "banana:failed"

    def test_mark_sets_both_states(self, seccomp_ok):
        plan = sandbox_exec.plan_for(None, mode="workspace-write", seccomp_profile="strict")
        sandbox_exec._mark(plan, sandbox_exec.SUFFIX_FAILED)
        assert plan.state == "workspace-write:failed"
        assert plan.seccomp.state == "strict:failed"
        sandbox_exec._mark(plan)
        assert plan.state == "workspace-write"
        assert plan.seccomp.state == "strict"

    def test_state_is_written_back_to_request(self, seccomp_ok):
        from trimum_core.models import ExecuteRequest

        request = ExecuteRequest(tool="shell", args=["echo", "hi"])
        plan = sandbox_exec.plan_for(request, mode="workspace-write")
        assert request.seccomp == plan.seccomp_state
        assert request.sandbox == plan.state

    @pytest.mark.asyncio
    async def test_seccomp_failure_is_fail_closed(self, landlock_ok, seccomp_ok, monkeypatch):
        """seccomp 施不上 → 命令**不执行**（与 Landlock 同一个出口）。"""
        plan = sandbox_exec.plan_for(None, mode="workspace-write")
        assert plan.seccomp.state == "l1"

        # 只让 seccomp 那一半炸：Landlock 是 Linux 专有，本机真施必失败，先摘掉
        monkeypatch.setattr(sandbox_exec, "apply_current", lambda _plan: None)

        def boom(_plan, **_kwargs):
            raise seccomp_exec.SeccompError("seccomp_load 失败", plan=_plan)

        monkeypatch.setattr(seccomp_exec, "apply_current", boom)

        spawned: list[dict] = []

        async def fake_spawn(shell, args, kwargs):
            spawned.append(kwargs)
            try:
                kwargs["preexec_fn"]()  # 子进程里跑钩子（CPython 会把异常包成 SubprocessError）
            except BaseException as exc:
                raise subprocess.SubprocessError("Exception occurred in preexec_fn.") from exc
            return "PROC"

        monkeypatch.setattr(sandbox_exec, "_spawn_process", fake_spawn)
        with pytest.raises(sandbox_exec.SandboxError):
            await sandbox_exec.spawn_shell(plan, "echo hi")
        assert plan.state == "workspace-write:failed"
        assert plan.seccomp.state == "l1:failed"
        assert len(spawned) == 1

    def test_reset_cache_clears_both_modules(self):
        seccomp_exec.probe()
        sandbox_exec.reset_cache()
        assert seccomp_exec._capability is None and seccomp_exec._LIB is None


class _Executed(Exception):
    """模拟 ``os.execvp`` 成功（正常不返回，用异常把控制权交给用例）。"""


class TestModuleCli:
    """``python -m trimum_core.seccomp_exec`` 的三个出口（真机踩过 off 档那条）。"""

    def test_off_profile_does_not_apply_and_still_execs(self, monkeypatch):
        """off 档 = 一键退：**不施加**、也不算失败（踩过的 bug：空档案被当失败，退 126）。"""
        seen: dict = {}

        def fake_execvp(prog, argv):
            seen.update(prog=prog, argv=list(argv))
            raise _Executed()  # execvp 正常不返回；用异常模拟"已经把控制权交出去"

        monkeypatch.setattr(seccomp_exec.os, "execvp", fake_execvp)
        with pytest.raises(_Executed):
            seccomp_exec.main(["--profile", "off", "--", "echo", "hi"])
        assert seen["prog"] == "echo"
        assert seen["argv"] == ["echo", "hi"]

    def test_failed_plan_refuses_to_exec(self, monkeypatch, capsys):
        seen: dict = {}
        monkeypatch.setattr(seccomp_exec.os, "execvp", lambda *args: seen.update(ran=True))
        assert seccomp_exec.main(["--profile", "banana", "--", "echo", "hi"]) == 126
        assert not seen, "档案不可用时不许把命令放出去"
        assert "档案不可用" in capsys.readouterr().err

    def test_status_prints_capability_and_plan(self, capsys):
        assert seccomp_exec.main(["--status"]) == 0
        out = capsys.readouterr().out
        assert "capability :" in out and "plan       :" in out and "state      :" in out


@pytest.mark.skipif(not LINUX, reason="seccomp 是 Linux 专有")
class TestSeccompReal:
    """真机端到端（Linux 专属）：判别器**只选正常会成功**的 syscall。

    ``bpf`` / ``mount`` / ``setns`` 在非特权下本来就失败（EINVAL / ENOENT），拿它们当
    判据会得出「拦住了」的**假结论**（2026-09-22 真机实测）。所以这里只用
    ``ptrace(PTRACE_TRACEME)``（对照组 rc=0）与 ``io_uring_setup``（对照组返回 fd），
    并且**先跑一遍不施加的对照组**，证明这两个判据在本机真的会成功。
    """

    PROBE = """
import ctypes, os
libc = ctypes.CDLL(None, use_errno=True)
libc.syscall.restype = ctypes.c_long

class Params(ctypes.Structure):
    _fields_ = [("pad", ctypes.c_uint64 * 16)]

def probe(label, fn):
    ctypes.set_errno(0)
    rc = fn()
    print("%s rc=%d errno=%d" % (label, rc, ctypes.get_errno()))

params = Params()
probe("ptrace", lambda: libc.ptrace(0, 0, 0, 0))
probe("io_uring_setup", lambda: libc.syscall(__NR_IO_URING__, 2, ctypes.byref(params)))
probe("getpid", lambda: libc.getpid())
"""

    SOCKET_PROBE = """
import socket
for label, family in (("inet", socket.AF_INET), ("unix", socket.AF_UNIX)):
    try:
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.close()
        print("%s ok" % label)
    except OSError as exc:
        print("%s errno=%d" % (label, exc.errno or 0))
"""

    def _nr(self, name: str) -> int:
        """本架构的 syscall 号（走 libseccomp 的名字表，不硬编码）。"""
        capability = seccomp_exec.probe(refresh=True)
        if not capability.supported:
            pytest.skip(f"本机 libseccomp 不可用：{capability.reason}")
        nr = seccomp_exec._resolver_default(name, seccomp_exec.libc_library())
        if nr < 0:
            pytest.skip(f"本架构没有 {name}（libseccomp 返回 {nr}）")
        return nr

    def _probe_script(self) -> str:
        return self.PROBE.replace("__NR_IO_URING__", str(self._nr("io_uring_setup")))

    @staticmethod
    def _parse(text: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for line in text.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                out[parts[0]] = " ".join(parts[1:])
        return out

    @staticmethod
    def _rc(entry: str) -> int:
        return int(entry.split("rc=")[1].split()[0])

    @staticmethod
    def _errno(entry: str) -> int:
        return int(entry.split("errno=")[1].split()[0])

    def _plain(self, script: str) -> dict[str, str]:
        """对照组：**不施加**过滤器跑同一段脚本。"""
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            env={**os.environ, "PYTHONPATH": str(SRC)},
            text=True,
        )
        return self._parse(proc.stdout)

    def _sandboxed(self, script: str, *, profile: str, extra: list[str] | None = None):
        proc = subprocess.run(
            [
                sys.executable, "-m", "trimum_core.seccomp_exec",
                "--profile", profile, *(extra or []),
                "--", sys.executable, "-c", script,
            ],
            capture_output=True,
            env={**os.environ, "PYTHONPATH": str(SRC)},
            text=True,
        )
        return proc, self._parse(proc.stdout)

    def test_discriminators_really_succeed_without_filter(self):
        """先自证判据：不施加时这两个 syscall **必须**成功，否则后面的结论不成立。"""
        got = self._plain(self._probe_script())
        assert self._rc(got["ptrace"]) == 0 and self._errno(got["ptrace"]) == 0, got
        assert self._errno(got["io_uring_setup"]) == 0, got
        assert self._rc(got["io_uring_setup"]) >= 0, got

    def test_l1_blocks_the_dangerous_face_only(self):
        script = self._probe_script()
        proc, got = self._sandboxed(script, profile="l1")
        assert proc.returncode == 0, proc.stderr

        assert self._errno(got["ptrace"]) == seccomp_exec.EPERM, got
        assert self._errno(got["io_uring_setup"]) == seccomp_exec.EPERM, got
        # 良性 syscall 不受影响。getpid 每个进程都不一样，只能断言「正常返回了正数」，
        # 别跟对照组比相等（真机首跑就是这么挂的）
        assert self._errno(got["getpid"]) == 0, got
        assert self._rc(got["getpid"]) > 0, got

    def test_off_profile_is_a_noop(self):
        script = self._probe_script()
        base = self._plain(script)
        proc, got = self._sandboxed(script, profile="off")
        assert proc.returncode == 0, proc.stderr
        assert self._rc(got["ptrace"]) == self._rc(base["ptrace"]) == 0, got
        assert self._errno(got["ptrace"]) == 0, got

    def test_strict_blocks_inet_but_keeps_unix(self):
        """AF_UNIX 是红线：子 Agent 的 RPC 靠它。"""
        base = self._plain(self.SOCKET_PROBE)
        assert base == {"inet": "ok", "unix": "ok"}, base

        proc, got = self._sandboxed(self.SOCKET_PROBE, profile="strict")
        assert proc.returncode == 0, proc.stderr
        assert self._errno(got["inet"]) == seccomp_exec.EPERM, got
        assert got["unix"] == "ok", got

    def test_sandbox_exec_spawn_carries_seccomp(self, tmp_path):
        """S2 × S3 联动：走 ``sandbox_exec.spawn_exec`` 派生的子进程也带着 seccomp。"""
        plan = sandbox_exec.plan_for(cwd=str(tmp_path), mode="workspace-write")
        assert plan.seccomp.state == "l1"

        async def run():
            proc = await sandbox_exec.spawn_exec(
                plan,
                sys.executable,
                "-c",
                self._probe_script(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await proc.communicate()
            return out.decode(), err.decode()

        out, err = asyncio.run(run())
        got = self._parse(out)
        assert plan.state == "workspace-write" and plan.seccomp.state == "l1", (out, err)
        assert self._errno(got["ptrace"]) == seccomp_exec.EPERM, (got, err)

    def test_module_status_reports_api_level_and_mode(self):
        env = {**os.environ, "PYTHONPATH": str(SRC)}
        proc = subprocess.run(
            [sys.executable, "-m", "trimum_core.seccomp_exec", "--status"],
            capture_output=True, env=env, text=True,
        )
        assert proc.returncode == 0, proc.stderr
        assert "api_level=" in proc.stdout, proc.stdout
        assert "state      : l1" in proc.stdout, proc.stdout

        whitelist = subprocess.run(
            [
                sys.executable, "-m", "trimum_core.seccomp_exec", "--status",
                "--profile", "strict", "--allow", "read",
            ],
            capture_output=True, env=env, text=True,
        )
        assert "mode=whitelist" in whitelist.stdout, whitelist.stdout
class TestStaticGuards:
    """静态守卫：这几类错误在运行期是**静默**的，只能靠读源码拦住。"""

    def test_pydantic_calls_only_use_real_fields(self):
        """不许给 pydantic 模型传**不存在的字段名**。

        pydantic 默认忽略未知字段 —— 把 ``plan=plan`` 传进 ``ExecuteResponse(...)``
        不报错也不告警，只会让审计里的 ``sandbox`` / ``seccomp`` 悄悄变成空串
        （S3 编写时真踩过这一步）。运行期看不见，只能在源码上拦。
        """
        models = {"ExecuteResponse": ExecuteResponse, "AuditEvent": AuditEvent}
        offenders: list[str] = []
        for path in sorted(PKG.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                    continue
                model = models.get(node.func.id)
                if model is None:
                    continue
                allowed = set(model.model_fields)
                for kw in node.keywords:
                    if kw.arg is not None and kw.arg not in allowed:
                        offenders.append(f"{path.name}:{node.lineno} {node.func.id}({kw.arg}=...)")
        assert offenders == [], f"这些关键字模型里没有，pydantic 会静默丢掉：{offenders}"

    def test_both_states_travel_together(self):
        """``sandbox=`` 与 ``seccomp=`` 必须成对出现 —— 少一个就是审计里少了半边。"""
        offenders: list[str] = []
        for path in sorted(PKG.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                    continue
                if node.func.id not in ("ExecuteResponse", "AuditEvent"):
                    continue
                names = {kw.arg for kw in node.keywords if kw.arg}
                if ("sandbox" in names) != ("seccomp" in names):
                    offenders.append(f"{path.name}:{node.lineno}")
        assert offenders == [], f"这些调用只带了一侧状态：{offenders}"

    def test_seccomp_is_applied_from_exactly_one_place(self):
        text = (PKG / "sandbox_exec.py").read_text(encoding="utf-8")
        assert text.count("seccomp_exec.apply_current(") == 1, "施加 seccomp 只能有一个入口（apply_plan）"
        assert "def apply_plan(" in text

    def test_no_direct_subprocess_in_seccomp_module(self):
        text = (PKG / "seccomp_exec.py").read_text(encoding="utf-8")
        assert "create_subprocess" not in text
        assert "subprocess" not in text.split("import")[0]  # 不是靠起进程来施加
