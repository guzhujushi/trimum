# trimum-mvp

trimum AI Shell Phase 1 MVP：自然语言 -> 安全命令执行。

## 安装（开发模式）

```powershell
cd src\trimum-mvp
pip install -e . --no-build-isolation
```

## 用法

```powershell
trm "查看磁盘空间"          # 低风险，自动执行
trm "删除 /tmp 缓存"        # 中风险，确认后执行
trm "清理系统日志"          # 高风险，确认 + 警告 + 审计
trm "格式化磁盘"            # 关键风险，直接拒绝
cat log.txt | trm "解释报错"  # 管道输入作为上下文
trm "查看磁盘" --dry-run     # 只展示计划与风险
```

## 配置

- `config.yaml`：LLM 端点、超时等默认配置。
- `policy.yaml`：安全策略规则（正则 -> 风险级别 + 动作）。

## 测试

```powershell
python test_scenarios.py -v
```