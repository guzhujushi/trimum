# ai.ps1 - trimum PowerShell 等价入口（Windows 开发验证）
# 用法：
#   .\ai.ps1 "查看磁盘空间"
#   Get-Content log.txt | .\ai.ps1 "解释这个报错"

param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Prompt
)

$ErrorActionPreference = "Stop"

# 确保 UTF-8 输入/输出，避免 GBK 控制台乱码或崩溃
try {
    [Console]::InputEncoding = [System.Text.Encoding]::UTF8
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
    # 某些宿主不支持修改编码，忽略即可
}

# 检查 trm 是否可用
if (-not (Get-Command trm -ErrorAction SilentlyContinue)) {
    Write-Host "未找到 trm 命令，请先安装：pip install -e src\trimum-mvp" -ForegroundColor Red
    exit 1
}

# 管道模式：stdin 被重定向时读取全部内容作为上下文
$pipeInput = ""
if ([Console]::IsInputRedirected) {
    $pipeInput = [Console]::In.ReadToEnd().Trim()
}

if ($pipeInput) {
    $pipeInput | trm $Prompt
} else {
    trm $Prompt
}