<#
  注意：本文件必须是 **UTF-8 with BOM**。Windows PowerShell 5.1 用 -File 跑脚本时
  会把「无 BOM 的 UTF-8」按 ANSI(GBK) 解，中文会把脚本解析弄挂（已实测）。
  仓库里 bash 脚本「UTF-8 无 BOM」的规则是给 Linux shell 的，不适用于这里。
#>
<#
.SYNOPSIS
  用 trimum 的 .env 起 Codex，并按任务选模型（Qwen 免费 / deepseek-flash 收费）。

.DESCRIPTION
  Codex 0.151 的「换模型」靠**独立 profile 文件**：$env:CODEX_HOME\<name>.config.toml，
  用 `codex -p <name>` 选；profile **不能**写在 config.toml 里（会直接报错）。本机已有：
    qwen → 交我算 qwen3.8-27b（免费，10 次/分；只适合单次小任务）
    ds   → DeepSeek deepseek-flash（收费；长会话 / 难题）

  本脚本额外做一件事：把 trimum 的 .env 灌进本次进程的环境。Codex 用 provider 的
  env_key 取 key，而 DEEPSEEK_API_KEY / JIAOWOISAN_API_KEY 并不是持久化的用户环境变量。
  已存在的环境变量优先（与 trimum_core.env_file 同口径）。

.EXAMPLE
  .\scripts\codex-model.ps1 qwen                 # 交互式，Qwen
  .\scripts\codex-model.ps1 ds                   # 交互式，deepseek-flash
  .\scripts\codex-model.ps1 qwen -Exec "把 TODO.md 里的提交号回填"
  .\scripts\codex-model.ps1 qwen -PromptFile tmp\task.md -Sandbox read-only
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)][ValidateSet('qwen', 'ds')][string]$Model = 'ds',
    [string]$Exec,
    [string]$PromptFile,
    [ValidateSet('read-only', 'workspace-write', 'danger-full-access')][string]$Sandbox = 'workspace-write',
    [switch]$SkipGitRepoCheck,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest
)

$ErrorActionPreference = 'Stop'

$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME '.codex' }
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

function Find-EnvFile {
    $cands = @()
    if ($env:TRIMUM_ENV_FILE) { $cands += $env:TRIMUM_ENV_FILE }
    if ($env:TRIMUM_HOME) { $cands += (Join-Path $env:TRIMUM_HOME '.env') }
    $cands += (Join-Path $HOME '.trimum\.env')
    $cands += (Join-Path $repoRoot '.env')
    foreach ($c in $cands) {
        if ($c -and (Test-Path -LiteralPath $c)) { return $c }
    }
    return $null
}

$envFile = Find-EnvFile
$applied = New-Object System.Collections.Generic.List[string]
if ($envFile) {
    foreach ($line in [System.IO.File]::ReadAllLines($envFile)) {
        $t = $line.Trim()
        if (-not $t -or $t.StartsWith('#')) { continue }
        if ($t.StartsWith('export ')) { $t = $t.Substring(7).Trim() }
        $i = $t.IndexOf('=')
        if ($i -lt 1) { continue }
        $key = $t.Substring(0, $i).Trim()
        $val = $t.Substring($i + 1).Trim()
        if ($val.Length -ge 2 -and $val[0] -eq $val[-1] -and ($val[0] -eq '"' -or $val[0] -eq "'")) {
            $val = $val.Substring(1, $val.Length - 2)
        }
        if (-not [Environment]::GetEnvironmentVariable($key)) {
            [Environment]::SetEnvironmentVariable($key, $val, 'Process')
            $applied.Add($key)
        }
    }
}

$profileFile = Join-Path $codexHome "$Model.config.toml"
if (-not (Test-Path -LiteralPath $profileFile)) {
    throw "profile 文件不存在：$profileFile（Codex 0.151 的 profile 必须是独立文件，不能写在 config.toml 里）"
}

$codex = (Get-Command codex -ErrorAction SilentlyContinue).Source
if (-not $codex) {
    $known = Join-Path $env:LOCALAPPDATA 'OpenAI\Codex\bin'
    $found = Get-ChildItem -Path $known -Filter 'codex.exe' -Recurse -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($found) { $codex = $found.FullName }
}
if (-not $codex) { throw '找不到 codex：既不在 PATH 上，也没在 %LOCALAPPDATA%\OpenAI\Codex\bin 下找到' }

Write-Host ("[codex-model] profile={0}  provider-key-env 注入 {1} 个  env-file={2}" -f $Model, $applied.Count, $envFile) -ForegroundColor DarkGray

$codexArgs = @('-p', $Model)
if ($Exec -or $PromptFile) {
    $codexArgs += 'exec', '--skip-git-repo-check', '-s', $Sandbox
    if ($PromptFile) { $codexArgs += (Get-Content -LiteralPath $PromptFile -Raw -Encoding UTF8) }
    else { $codexArgs += $Exec }
}
elseif ($SkipGitRepoCheck) {
    $codexArgs += '--skip-git-repo-check'
}
if ($Rest) { $codexArgs += $Rest }

& $codex @codexArgs
exit $LASTEXITCODE
