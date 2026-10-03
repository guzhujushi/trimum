@echo off
rem Codex + DeepSeek deepseek-flash  (paid, long sessions / hard tasks)
rem Usage:  codex-ds.cmd                   -> interactive
rem         codex-ds.cmd -Exec "..."       -> one-shot
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0codex-model.ps1" ds %*