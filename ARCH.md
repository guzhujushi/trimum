# ARCH — trimum

## 技术选型

- 语言：Python 3.12+
- Web 框架：FastAPI
- 数据模型：Pydantic v2
- 工具插件：`~/.trimum/tools/<name>/{tool.json5,main.py}`

完整架构文档见 `docs/ARCHITECTURE.md` 与 `docs/ARCH.md`。

## browser 路由设计

1. `models.ToolType` 新增 `BROWSER = "browser"`，使 `ExecuteRequest.tool` 接受
   `"browser"`。
2. `ToolGateway.execute()` 以 `request.tool.value`（即 `"browser"`）查询
   `ToolRegistry`，命中文件工具定义后调用 `ToolRegistry.get_executor("browser")`。
3. `tool_file_loader.TOOL_KINDS` 增加 `"browser" -> ToolType.BROWSER` 映射。
4. `ToolGateway._check_cwd_jail()` 将 `ToolType.BROWSER` 加入免 cwd 校验集合，
   与 `CUSTOM` 等无文件系统路径依赖的工具一致。
5. CDP 地址解析优先级：`cdp` 请求参数 > `CLI_ANYTHING_CDP_URL` > `http://localhost:9222`。

## `trm` CLI 设计

### 目录结构

- `src/trimum_core/cli/__init__.py`：`main(argv)` 入口，分发到 handler。
- `src/trimum_core/cli/__main__.py`：支持 `python -m trimum_core.cli`。
- `src/trimum_core/cli/parser.py`：构建根 parser 与全局 `--json`/`--version`。
- `src/trimum_core/cli/_utils.py`：版本、JSON 输出、RPC/HTTP 探测、daemon 状态等公共能力。
- `src/trimum_core/cli/commands/`：每个命令模块导出 `add_subparsers()`。

### 关键规则

- `commands.register_all()` 使用 `pkgutil` 动态导入命令模块，跳过私有模块。
- 每个子命令通过 `parser.set_defaults(handler=handler)` 绑定 `def handler(args) -> int`。
- 全局 `--json` 递归注入所有子 parser，使用 `argparse.SUPPRESS` 避免覆盖根参数。
- 不引入 click/typer；daemon 交互优先 JSON-RPC，HTTP API 作为 fallback。
