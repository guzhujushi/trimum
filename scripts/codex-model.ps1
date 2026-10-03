<#
  注意：本文件必须是 **UTF-8 with BOM**。Windows PowerShell 5.1 用 -File 跑脚本时
  会把「无 BOM 的 UTF-8」按 ANSI(GBK) 解，中文会把脚本解析弄挂（已实测）。
  仓库里 bash 脚本「UTF-8 无 BOM」的规则是给 Linux shell 的，不适用于这里。
#>
<#
.SYNOPSIS
  用 trimum 的 .env 起 Codex，并按任务选模型（Qwen 免费 / deepseek-flash 收费）。

.DESCRIPTION
  Codex 的「换模型」靠**独立 profile 文件**：$env:CODEX_HOME\<name>.config.toml，
  用 `codex -p <name>` 选；profile **不能**写在 config.toml 里（会直接报错）。本机已有：
    qwen → 交我算 qwen3.8-27b（免费，10 次/分；只适合单次小任务）
    ds   → DeepSeek deepseek-flash（收费；长会话 / 难题）

  ⚠ profile 同时**决定 provider**：qwen3.8-27b 只存在于 provider=sjtu-jiaowusuan（交我算）上。
  交互界面里用 /model 只改「模型名」，**不会**改 provider —— 于是请求还是发给
  provider=deepseek-api，被 DeepSeek 以「The supported API model names are
  deepseek-flash, deepseek-v4-pro」拒掉。换 provider 只能重开进程：`codex -p qwen`
  （或本脚本）。sjtu-jiaowusuan 是 **provider 名，不是模型名**，永远不要写进 /model。

  本脚本额外做两件事：
  1. 把 trimum 的 .env 灌进本次进程的环境。Codex 用 provider 的 env_key 取 key，
     而 DEEPSEEK_API_KEY / JIAOWOISAN_API_KEY 并不是持久化的用户环境变量。
     进程原有环境变量优先（与 trimum_core.env_file 同口径）；多个 .env 候选
     **按低→高优先级**依次加载，仓库根的 .env 是权威。
  2. 起 codex 前先校验 profile 需要的 env_key 在不在，缺了就明确报错，
     而不是让 codex 抛一句 `Missing environment variable`。

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

# .env 候选，**低优先级在前**（后加载的覆盖先加载的）：仓库根 .env 是权威。
function Get-EnvFileCandidates {
    $cands = New-Object System.Collections.Generic.List[string]
    $cands.Add((Join-Path $HOME '.trimum\.env'))
    if ($env:TRIMUM_HOME) { $cands.Add((Join-Path $env:TRIMUM_HOME '.env')) }
    $cands.Add((Join-Path $repoRoot '.env'))
    if ($env:TRIMUM_ENV_FILE) { $cands.Add($env:TRIMUM_ENV_FILE) }
    return $cands
}

function Get-ProfileProviderId([string]$profilePath) {
    $txt = [System.IO.File]::ReadAllText($profilePath)
    $m = [regex]::Match($txt, '(?m)^\s*model_provider\s*=\s*"([^"]+)"')
    if ($m.Success) { return $m.Groups[1].Value }
    return $null
}

function Get-ProviderEnvKey([string]$providerId) {
    $cfgPath = Join-Path $codexHome 'config.toml'
    if (-not (Test-Path -LiteralPath $cfgPath)) { return $null }
    $txt = [System.IO.File]::ReadAllText($cfgPath)
    $block = [regex]::Match($txt, '(?ms)^\s*\[model_providers\.' + [regex]::Escape($providerId) + '\]\s*$(.*?)(?=^\s*\[|\z)')
    if (-not $block.Success) { return $null }
    $k = [regex]::Match($block.Groups[1].Value, '(?m)^\s*env_key\s*=\s*"([^"]+)"')
    if ($k.Success) { return $k.Groups[1].Value }
    return $null
}

# 先给「进程原有环境变量」拍快照，它们优先于任何 .env。
$preExisting = @{}
foreach ($k in [System.Environment]::GetEnvironmentVariables('Process').Keys) { $preExisting[$k] = $true }

$loadedFiles = New-Object System.Collections.Generic.List[string]
$applied = New-Object System.Collections.Generic.List[string]
foreach ($cand in (Get-EnvFileCandidates)) {
    if (-not $cand -or -not (Test-Path -LiteralPath $cand)) { continue }
    $loadedFiles.Add($cand)
    foreach ($line in [System.IO.File]::ReadAllLines($cand)) {
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
        if ($preExisting.ContainsKey($key)) { continue }
        [Environment]::SetEnvironmentVariable($key, $val, 'Process')
        if (-not $applied.Contains($key)) { $applied.Add($key) }
    }
}

$profileFile = Join-Path $codexHome "$Model.config.toml"
if (-not (Test-Path -LiteralPath $profileFile)) {
    throw "profile 文件不存在：$profileFile（profile 必须是 CODEX_HOME 下的独立文件，不能写在 config.toml 里）"
}

$providerId = Get-ProfileProviderId $profileFile
$needKey = $null
if ($providerId) { $needKey = Get-ProviderEnvKey $providerId }
if ($needKey -and -not [Environment]::GetEnvironmentVariable($needKey)) {
    $envList = ($loadedFiles -join "`n    ")
    throw ("profile '$Model' 走 provider '$providerId'，需要环境变量 $needKey，但当前进程里没有。`n" +
           "已加载的 .env：`n    $envList`n" +
           "→ 请确认 $repoRoot\.env 里定义了 $needKey。")
}

$codex = (Get-Command codex -ErrorAction SilentlyContinue).Source
if (-not $codex) {
    $known = Join-Path $env:LOCALAPPDATA 'OpenAI\Codex\bin'
    $found = Get-ChildItem -Path $known -Filter 'codex.exe' -Recurse -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($found) { $codex = $found.FullName }
}
if (-not $codex) { throw '找不到 codex：既不在 PATH 上，也没在 %LOCALAPPDATA%\OpenAI\Codex\bin 下找到' }

$summary = "[codex-model] profile={0}  provider={1}  key-env={2}" -f $Model, $providerId, $needKey
$summary += "  |  注入 {0} 个变量" -f $applied.Count
$summary += "  |  .env: " + ($loadedFiles -join ' ; ')
Write-Host $summary -ForegroundColor DarkGray

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

# PS 5.1 会把原生命令写到 stderr 的每一行包成 ErrorRecord；配合 $ErrorActionPreference='Stop'
# 会在 codex 刚启动（它总会往 stderr 写 "Reading additional input from stdin..."）时就抛错。
# 真正的成败看 $LASTEXITCODE，所以这里放开 Stop。
$ErrorActionPreference = 'Continue'
& $codex @codexArgs
exit $LASTEXITCODE
