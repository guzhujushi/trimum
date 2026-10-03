@echo off
rem Codex + SJTU jiaowusuan qwen3.8-27b  (free, 10 req/min, one-shot tasks)
rem Usage:  codex-qwen.cmd                 -> interactive
rem         codex-qwen.cmd -Exec "..."     -> one-shot
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0codex-model.ps1" qwen %*