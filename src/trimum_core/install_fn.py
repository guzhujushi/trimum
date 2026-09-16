"""Interactive install command for trimum CLI."""

import os
import subprocess
import sys


def install() -> None:
    """Interactive 'trm install' — guide user through first-time setup.

    Does NOT perform the actual package installation (that's what
    scripts/install.sh is for). Instead, it:

    1. Checks if trimum is already installed and running
    2. Points user to run 'sudo bash /opt/trimum/scripts/install.sh'
    3. Guides through post-install configuration:
       - Create ~/.trimum/agents/ directory structure
       - Configure LLM API key (if desired)
       - Suggest enabling systemd service
    """

    def prompt(question: str, default: str = "Y") -> bool:
        """Ask a yes/no question on terminal."""
        suffix = " [Y/n]" if default.upper() == "Y" else " [y/N]"
        try:
            answer = input(f"  {question}{suffix} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if not answer:
            return default.upper() == "Y"
        return answer in ("y", "yes")

    def info(msg: str) -> None:
        print(f"  [i] {msg}")

    def headline(msg: str) -> None:
        print(f"\n{'=' * 50}")
        print(f"  {msg}")
        print(f"{'=' * 50}")

    print(f"\n{'=' * 50}")
    print("  trimum — AI Process Runtime")
    print(f"  {'=' * 50}")

    # ── 检查 daemon 是否已安装 ──
    opt_dir = "/opt/trimum"
    installed = os.path.isdir(opt_dir) and os.path.isfile(f"{opt_dir}/pyproject.toml")
    systemd_installed = os.path.isfile("/etc/systemd/system/trmd.service")

    if installed:
        info(f"检测到 trimum 已安装在 {opt_dir}")
        if systemd_installed:
            info("systemd 服务 trmd.service 已安装")
            try:
                result = subprocess.run(
                    ["systemctl", "is-active", "trmd"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.stdout.strip() == "active":
                    info("trmd 正在运行 ✅")
                else:
                    info("trmd 未运行，运行 sudo systemctl start trmd 启动")
            except (FileNotFoundError, subprocess.TimeoutExpired):
                info("无法检测 trmd 状态（可能不在 systemd 环境）")
        else:
            info("systemd 服务未安装，运行 sudo systemctl enable trmd")
    else:
        info("trimum 尚未安装")
        info("请先运行以下命令安装:")
        print()
        print("    sudo bash scripts/install.sh")
        print()
        info("或从 GitHub 克隆后安装:")
        print()
        print("    git clone https://github.com/guzhujushi/trimum.git /opt/trimum")
        print("    cd /opt/trimum")
        print("    sudo bash scripts/install.sh")
        print()

    # ── 后续配置 ──
    headline("安装后配置")

    home = os.path.expanduser("~")

    # 1. ~/.trimum 目录检查
    trimum_dir = os.path.join(home, ".trimum")
    if not os.path.isdir(trimum_dir):
        info("创建 ~/.trimum/ 目录结构")
        for sub in ["agents", "tools", "skills", "workflows", "memory", "certs", "learning"]:
            os.makedirs(os.path.join(trimum_dir, sub), exist_ok=True)
        info(f"已创建 {trimum_dir}/ 及子目录")
    else:
        info(f"{trimum_dir}/ 已存在 ✅")

    # 2. API Key 配置
    headline("API Key 配置（可选）")

    if prompt("配置 LLM API Key？(Planner Agent 需要) ", "N"):
        print("  请输入 LLM API Key（输入后以 *** 显示，不会记录到日志）:")
        try:
            import getpass
            api_key = getpass.getpass("  API Key: ")
            if api_key.strip():
                env_file = os.path.join(home, ".trimum", ".env")
                with open(env_file, "a", encoding="utf-8") as f:
                    f.write(f"\nTRIMUM_LLM_API_KEY={api_key.strip()}\n")
                info(f"API Key 已写入 {env_file}")
            else:
                info("已跳过，未写入 API Key")
        except (EOFError, KeyboardInterrupt):
            info("已取消")

    # 3. 系统服务
    headline("系统服务")

    if systemd_installed:
        if prompt("是否开机自启 trimum 服务？", "Y"):
            try:
                subprocess.run(
                    ["systemctl", "enable", "trmd"],
                    capture_output=True, text=True, timeout=5,
                )
                info("trmd 已设为开机自启")
            except (FileNotFoundError, subprocess.TimeoutExpired):
                info("无法配置开机自启（可能不在 systemd 环境），跳过")
        if prompt("现在启动 trimum？", "Y"):
            try:
                subprocess.run(
                    ["systemctl", "start", "trmd"],
                    capture_output=True, text=True, timeout=10,
                )
                info("trmd 已启动")
            except (FileNotFoundError, subprocess.TimeoutExpired):
                info("无法启动 trmd（可能不在 systemd 环境），跳过")

    # 4. 预设 Agent
    headline("预设 Agent")

    agents_dir = os.path.join(trimum_dir, "agents")
    existing = [d for d in os.listdir(agents_dir) if os.path.isdir(os.path.join(agents_dir, d))] if os.path.isdir(agents_dir) else []
    if existing:
        info(f"已安装 {len(existing)} 个预设 Agent: {', '.join(existing)}")
    else:
        info("暂无预设 Agent，在 Ubuntu 上安装后会自动提供 maintenance/fs-helper/system-monitor")

    # 5. 总结
    headline("下一步")

    info("运行 trm health 检查系统状态")
    info("运行 trm --help 查看完整命令列表")
    info("参考 https://github.com/guzhujushi/trimum 获取更多文档")
    print()
