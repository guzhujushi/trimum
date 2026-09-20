# trimum Tool 创作指南（Tool Developer Guide）

> 本文档面向所有需要在 trimum 中创建/维护 tool 的开发者。
> 目标是：**即使你完全没读过 trimum 源码，照着这份指南也能写出一个可用的 tool。**

---

## 1. Tool 是什么

在 trimum 中，**Tool** 是一个自包含的目录，放在 `~/.trimum/tools/<tool-name>/` 下。

每个 tool 目录中至少包含两个文件：

```
~/.trimum/tools/<tool-name>/
├── tool.json5      # 工具清单（元数据 + 资源权限声明）
└── main.py         # 工具入口（必须导出 execute() 函数）
```

trimum 启动时，`ToolRegistry` 会扫描这个目录，加载每个 tool，并暴露给上层 Agent 调用。

**一句话：tool = 一个目录 + 一份清单 + 一个入口函数。**

---

## 2. 快速上手（30 秒版）

如果你已经有一个可运行的 tool 目录，只需要确保：

1. `tool.json5` 的 `name` 字段 = 目录名（例如目录叫 `browser`，name 就是 `"browser"`）
2. `main.py` 导出了一个 **async** 的 `execute(request: dict) -> dict` 函数
3. 返回值必须包含 `output`、`status`、`error` 三个字段
4. `tool.json5` 的 `kind` 字段必须是 `kind` 表里注册过的值

**如果你的 tool 没有出现在 Gateway 路由中，80% 是下面第 4 节的问题。**

---

## 3. 文件规范详解

### 3.1 tool.json5

`tool.json5` 是一个 JSON5 格式（JSON + 注释）的清单文件。完整字段如下：

```json5
{
  // 必填：工具名，必须与所在目录名完全一致！
  name: "browser",

  // 必填：一句话描述，展示给 Agent/用户看
  description: "Browser automation via CLI-Anything: open pages, read text, click, type, screenshot.",

  // 必填：工具大类。必须是 tool_file_loader.py 中 TOOL_KINDS 已注册的 key。
  // 常用值：shell, file_read, file_write, file_delete, file_list, file_move,
  //         file_copy, git, custom, browser 等。
  // ⚠️ 如果是新的大类，必须先修改 TOOL_KINDS 映射并申请注册！
  kind: "custom",

  // 必填：入口文件（相对当前目录）
  entry: "./main.py",

  // 可选：默认超时（秒）
  timeout: 30.0,

  // 可选：风险等级（low / medium / high / critical）
  risk: "medium",

  // 可选：权限声明（写进 tool.json5，Gateway 据此做安全检查）
  permissions: {
    // 是否允许访问网络
    network: true,
    // 文件系统读写路径列表
    filesystem: ["tool/browser/*"],
    // 是否允许执行外部进程
    exec: false,
  },

  // 可选：该工具依赖的其他工具（用于声明依赖关系）
  tools: [],
}
```

### 3.2 main.py 的 execute() 函数

`main.py` 是工具的实际实现。**唯一硬性要求：导出一个 async `execute` 函数。**

```python
"""Tool: mytool — 一句话描述"""

from __future__ import annotations

import asyncio, json
from typing import Any


# 定义工具支持的动作
ACTIONS = {
    "do_something": ("arg1", "arg2"),  # 动作名: (必填参数字段名, ...)
}

def _ok(output: str = "", data: Any = None) -> dict[str, Any]:
    """统一成功返回格式。"""
    return {
        "status": "allowed",
        "output": output,
        "data": data,
        "error": "",
        "exit_code": 0,
    }

def _err(error: str, exit_code: int = 1) -> dict[str, Any]:
    """统一失败返回格式。"""
    return {
        "status": "denied",
        "output": "",
        "data": None,
        "error": error,
        "exit_code": exit_code,
    }


async def execute(request: dict[str, Any]) -> dict[str, Any]:
    """工具入口。request 是 Gateway 传来的完整请求 dict。

    必须返回 dict，且必须包含 status / output / error 三个字段。
    """
    action = str(request.get("action") or "").strip()
    if not action:
        return _err("Missing required field: action")

    if action not in ACTIONS:
        return _err(f"Unsupported action: {action}. Supported: {sorted(ACTIONS)}")

    # 收集动作参数
    fields = ACTIONS[action]
    args = {}
    for field in fields:
        args[field] = str(request.get(field) or "").strip()
        if not args[field]:
            return _err(f"Missing required field: {field}")

    # ---- 核心逻辑 ----
    # 在这里实现你的工具逻辑...

    if action == "do_something":
        result = do_something(args["arg1"], args["arg2"])
        return _ok(output=json.dumps(result, ensure_ascii=False))
    # ...


def do_something(a: str, b: str) -> dict:
    return {"a": a, "b": b}


__tool_name__ = "mytool"
__tool_version__ = "1.0.0"
__tool_description__ = "我的工具：一句话描述"
```

> **注意事项：**
> - `execute` 必须返回 **dict**，字段至少包含 `output`、`status`、`error`。
> - `output` 一般是文本/JSON 字符串；`data` 可选，可以放结构化数据。
> - 尽量不要在 execute 里抛异常 —— 捕获后返回 `_err(...)` 更友好。
> - 长耗时操作请用 `asyncio.to_thread(...)` 包住阻塞调用，不要 block 主事件循环。

---

## 4. ⚠️ 最容易踩的坑：ToolType 枚举注册

**这是 90% 的 tool 无法被调用的原因。**

`trimum` 的 `ToolType` 枚举控制着哪些 tool 类型是**合法的**。如果工具不在枚举里：
- 向 Gateway 发送 `tool: "<你的工具名>"` 时，Pydantic 校验直接失败，请求根本到不了你的代码。
- 会看到类似 `Input should be 'shell', 'file.read', ... or 'custom'` 的报错。

### 规则

1. **新增一个 tool 类型时**，必须：
   - 在 `src/trimum_core/models.py` 的 `ToolType` 枚举中新增成员，例如：
     ```python
     class ToolType(str, Enum):
         ...
         BROWSER = "browser"      # Browser automation via file-based tool
     ```
   - 在 `src/trimum_core/tool_file_loader.py` 的 `TOOL_KINDS` 映射中新增映射：
     ```python
     TOOL_KINDS: dict[str, ToolType] = {
         ...
         "browser": ToolType.BROWSER,
     }
     ```
   - 如工具需要跳过 cwd jail（如浏览器这种网络型工具），在 `tool_gateway.py` 的 `_check_cwd_jail()` 的 `skip_tools` 集合中加入对应枚举。

2. **如果只是新增一个 tool 实例**（例如已有 `git` 类型，再加一个 `git-lfs` 工具），通常只需要：
   - 新建目录 `~/.trimum/tools/git-lfs/`
   - 写 `tool.json5`（`name: "git-lfs"`, `kind: "git"`）
   - 写 `main.py`，`execute` 用和 git 相同的行为
   - **不需要**改 `models.py`

### 判断标准

| 你要做的事 | 要改哪些文件 |
|---|---|
| 用已有的 tool 类型，新增一个工具 | 只在 `~/.trimum/tools/` 下新建目录 |
| 新增一种全新的 tool 类型 | `models.py`（加枚举）+ `tool_file_loader.py`（加映射）+ 视情况改 `tool_gateway.py` |
| 修改某个工具的行为 | 只改该工具目录下的文件 |

---

## 5. Return 格式规范

所有 tool 都必须返回统一的 dict 结构。上层（Agent/API）依赖这个格式解析结果：

```json
{
  "execution_id": "a1b2c3d4e5f6",
  "status": "allowed",
  "output": "text output or JSON string",
  "data": {"optional": "structured data"},
  "error": "",
  "exit_code": 0,
  "risk": "medium",
  "action": "auto"
}
```

- `status`: `allowed` | `denied` | `confirmed`
  - `allowed` = 成功或已授权执行
  - `denied` = 安全策略拒绝
  - `confirmed` = 等待人工确认
- `output`: 给上层看的主要输出（文本或 JSON）
- `data`: 可选的结构化数据（建议放机器可读的结果）
- `error`: 错误描述，成功时为空字符串
- `exit_code`: 0 成功，非 0 失败
- `execution_id`: 由 Gateway 生成并回填

---

## 6. 环境变量与配置约定

推荐在 tool 中使用以下顺序读取配置：

```python
import os

def _get_cfg(request: dict, key: str, default: str = "") -> str:
    """配置优先级：请求参数 > 环境变量 > 默认值"""
    v = str(request.get(key) or "").strip()
    if v:
        return v
    v = os.environ.get(f"TRIMUM_{key.upper()}")
    if v:
        return v
    return default
```

例如 `browser` tool 中的 CDP URL：

```python
cdp_url = str(
    request.get("cdp")
    or os.environ.get("CLI_ANYTHING_CDP_URL")
    or "http://localhost:9222"
).strip()
```

**优先级统一：请求参数 > 环境变量（`TRIMUM_*` / `CLI_ANYTHING_*`） > 代码默认值。**

---

## 7. 常见错误与排查清单

| 症状 | 可能原因 | 排查方法 |
|---|---|---|
| `Input should be 'shell', 'file.read', ...` | 你的 tool 类型没在 `ToolType` 枚举里 | 看第 4 节，在 `models.py` 加枚举 |
| `Custom tool dispatch not yet available` | Gateway 路由到了内置 custom dispatcher，而不是你的文件 tool | 检查 `tool.json5` 的 name/kind 是否正确注册 |
| Tool 目录扫描不到 | 目录名与 `tool.json5` 的 name 不一致 | 确保两者完全一致 |
| execute 返回了非 dict | 返回值格式错误 | 看第 5 节 |
| `execution_id` 为空 | 没有走 Gateway 的 execute 路径 | 检查是否正确调用了 `gateway.execute()` |
| 中文乱码 | 编码问题 | 写文件用 `Set-Content -Encoding UTF8`，代码里 `open(..., encoding='utf-8')` |
| `__tool` 未定义 / 模块加载失败 | main.py 语法错误或最后一行不完整 | 打开 main.py 检查末尾 |

---

## 8. 完整示例：从零创建一个 `time` tool

以下演示完整的创建流程。

### 第 1 步：创建目录

```powershell
New-Item -ItemType Directory -Path "$env:USERPROFILE\.trimum\tools\time" -Force
```

### 第 2 步：写 tool.json5

```powershell
@'
{
  name: "time",
  description: "Show current time and date",
  kind: "custom",
  entry: "./main.py",
  timeout: 10.0,
  risk: "low",
  permissions: {
    network: false,
    filesystem: [],
    exec: false,
  },
}
'@ | Set-Content -Path "$env:USERPROFILE\.trimum\tools\time\tool.json5" -Encoding UTF8
```

### 第 3 步：写 main.py

```powershell
@'
"""Tool: time — 返回当前时间"""

from __future__ import annotations

import asyncio, json, datetime
from typing import Any


def _ok(output: str = "", data: Any = None) -> dict[str, Any]:
    return {
        "status": "allowed",
        "output": output,
        "data": data,
        "error": "",
        "exit_code": 0,
    }


def _err(error: str, exit_code: int = 1) -> dict[str, Any]:
    return {
        "status": "denied",
        "output": "",
        "data": None,
        "error": error,
        "exit_code": exit_code,
    }


async def execute(request: dict[str, Any]) -> dict[str, Any]:
    action = str(request.get("action") or "now").strip()
    if action == "now":
        now = datetime.datetime.now().isoformat()
        return _ok(output=now, data={"iso": now, "ts": datetime.datetime.now().timestamp()})
    if action == "utc":
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return _ok(output=now, data={"iso": now})
    return _err(f"Unsupported action: {action}. Supported: now, utc")


__tool_name__ = "time"
__tool_version__ = "1.0.0"
__tool_description__ = "返回当前时间与日期"
'@ | Set-Content -Path "$env:USERPROFILE\.trimum\tools\time\main.py" -Encoding UTF8
```

### 第 4 步：检测 tool 是否被发现

```powershell
cd D:\trimum
python -m pytest tests/test_tool_file_loading.py -q
```

如果没出现 `time`，检查：
- `tool.json5` 的 name 是否 = `time`
- kind 是否是 `TOOL_KINDS` 中注册过的值（本例用 `custom`）
- main.py 是否能正常 import（没有语法错误）

### 第 5 步：注册（如需新增类型）

如果 `time` 需要自己的 ToolType（而不是复用 `custom`）：

1. `src/trimum_core/models.py`：
   ```python
   TIME = "time"
   ```

2. `src/trimum_core/tool_file_loader.py`：
   ```python
   "time": ToolType.TIME,
   ```

3. 在 `tool_gateway.py` 的 `skip_tools` 中按需加入。

---

## 9. 测试要求

任何新 tool 都应至少通过以下检查：

```python
# tests/test_mytool.py
import asyncio, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from trimum_core.models import ExecuteRequest
from trimum_core.tool_file_loader import scan_tools


def test_tool_is_registered():
    tools = scan_tools()
    names = [t.name for t in tools]
    assert "mytool" in names


def test_execute_returns_expected_shape():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "mytool", os.path.expanduser("~/.trimum/tools/mytool/main.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    result = asyncio.run(mod.execute({"action": "do_something", "arg1": "a", "arg2": "b"}))
    assert isinstance(result, dict)
    assert "status" in result
    assert "output" in result
    assert "error" in result
```

---

## 10. Checklist（提交前自查）

- [ ] `tool.json5` 的 `name` = 目录名
- [ ] `tool.json5` 的 `kind` 已在 `TOOL_KINDS` 中注册
- [ ] `main.py` 导出了 async `execute(request: dict) -> dict`
- [ ] 返回值包含 `output` / `status` / `error`
- [ ] 配置优先级：请求参数 > 环境变量 > 默认值
- [ ] 阻塞操作用了 `asyncio.to_thread` 包裹
- [ ] 有基本测试（至少在 `tests/` 下有一个能跑的用例）
- [ ] 编码用 UTF-8，行尾 LF（尤其生成 .sh / .py 时避免 CRLF）
- [ ] 不硬编码凭据/密钥，一律走环境变量

## 11. 可借鉴：外部工具目录的两种约定（2026-09-20）

调研 `epiral/bb-browser`（见 `docs/BB-BROWSER-EVALUATION.md`）时撞见两条值得抄的约定，
本仓库暂未强制，写在这里供新工具参考：

1. **适配器自带示例**：bb-browser 的 `site info <name>` 会给出 `args / example / domain`，
   调用方不必读源码就知道怎么用。trimum 的 `tool.json5` 目前只有 `allowed_flags`，
   新工具建议在 `description` 里写清一条可复制的调用示例（`trm exec <tool> ...`）。
2. **稳定元素编号**：它的 `snapshot -i` 把可访问性树压成 `@1`、`@2`… 之后 `click @3` /
   `fill @5 "x"` 全用编号指代，杜绝「让 LLM 编 CSS 选择器」。写浏览器类/UI 类工具时优先
   返回编号而不是选择器。

