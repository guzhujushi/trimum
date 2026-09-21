#!/usr/bin/env bash
# trimum —— 让 daemon 吃到 /opt/trimum/.env（LLM key 与模型路由）
#
# 背景：trmd.service 里没有任何 EnvironmentFile，daemon 的环境里只有 PATH 与 TRIMUM_SOCKET，
# 所以「.env 里配了 key，trm doctor 还是 MISSING」——LLM 一次都调不起来。
# 本脚本给 trmd 加一个 drop-in，把 /opt/trimum/.env 喂给 daemon，并做验证。
#
# 用法（都要 sudo）：
#   sudo bash /tmp/llm_env_dropin.sh --check      # 只看现状，不动任何东西
#   sudo bash /tmp/llm_env_dropin.sh --apply      # 写 drop-in → daemon-reload → 重启 → 验证
#   sudo bash /tmp/llm_env_dropin.sh --rollback   # 删 drop-in → 重启（daemon 不再读 .env）
#
# 设计要点：
#   * EnvironmentFile=-/opt/trimum/.env —— 前导 `-` 表示文件不存在也不报错（fail-open 于「缺失」，
#     但缺 key 时 LLM 会在调用点降级，不会拖垮 daemon）。
#   * 验证只**看键名**，绝不打印键值：日志里出现 sk-... 是不可接受的。
#   * 路由表由 /opt/trimum/venv/bin/python 直接问 llm_router（部署树的真实配置）。
set -uo pipefail

UNIT="${UNIT:-trmd}"
UNIT_DIR="/etc/systemd/system"
DROPIN_DIR="$UNIT_DIR/${UNIT}.service.d"
DROPIN="$DROPIN_DIR/30-llm-env.conf"
ENV_FILE="${ENV_FILE:-/opt/trimum/.env}"
PY="${PY:-/opt/trimum/venv/bin/python}"
EVIDENCE_LOG="${EVIDENCE_LOG:-/tmp/llm-env-dropin-$(date +%Y%m%d-%H%M%S).log}"

PASS=0; WARN=0; FAIL=0
STEP="init"
trap 'code=$?; if [ "$code" -ne 0 ]; then echo "!! 失败：step=$STEP exit=$code（行 $LINENO）" | tee -a "$EVIDENCE_LOG" >&2; fi' ERR

ok()   { printf '  [PASS] %s\n' "$1"; printf '  [PASS] %s\n' "$1" >> "$EVIDENCE_LOG"; PASS=$((PASS+1)); }
warn() { printf '  [WARN] %s\n' "$1"; printf '  [WARN] %s\n' "$1" >> "$EVIDENCE_LOG"; WARN=$((WARN+1)); }
bad()  { printf '  [FAIL] %s\n' "$1"; printf '  [FAIL] %s\n' "$1" >> "$EVIDENCE_LOG"; FAIL=$((FAIL+1)); }
sec()  { printf '\n== %s\n' "$1"; printf '\n== %s\n' "$1" >> "$EVIDENCE_LOG"; }

need_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "需要 root：sudo bash $0 $1" >&2
    exit 2
  fi
}

# ── 路由表：直接问部署树里的 llm_router（只打印模型/地址/限速/键名，不打印键值）──
show_routing() {
  sec "当前 LLM 路由（部署树的真实解析结果）"
  if [ ! -x "$PY" ]; then
    bad "找不到 $PY，跳过路由表"
    return
  fi
  local out
  out="$(TRIMUM_ENV_FILE="$ENV_FILE" "$PY" - <<'PYEOF' 2>&1
import sys
sys.path.insert(0, "/opt/trimum/src")
from trimum_core import env_file, llm_router as R
env_file.load_env_file()
for role in (R.ROLE_POLICY, R.ROLE_PLANNER, R.ROLE_TRANSFORM, R.ROLE_EXPERIENCE, R.ROLE_AGENT):
    for t in R.resolve_targets(role):
        print(f"{role:10s} {t.tier:8s} model={t.model:16s} rpm={t.rpm:<3d} "
              f"key_env={t.api_key_env:22s} key={'有' if t.api_key else '缺':1s} ({t.label})")
PYEOF
)"
  printf '%s\n' "$out" | tee -a "$EVIDENCE_LOG"
  if printf '%s' "$out" | grep -q 'key=缺'; then
    warn "有 target 缺 key（对应 *_API_KEY 没进环境/.env）"
  else
    ok "所有 target 都有 key"
  fi
}

# ── 现状 ──
show_state() {
  sec "现状"
  printf '  单元          : %s\n' "$UNIT"
  printf '  is-active     : %s\n' "$(systemctl is-active "$UNIT" 2>/dev/null)"
  printf '  MainPID       : %s\n' "$(systemctl show "$UNIT" -p MainPID --value 2>/dev/null)"
  printf '  EnvironmentFiles: %s\n' "$(systemctl show "$UNIT" -p EnvironmentFiles --value 2>/dev/null)"
  printf '  drop-in       : %s\n' "$([ -f "$DROPIN" ] && echo 在 || echo 不在)"
  printf '  %s : %s\n' "$ENV_FILE" "$([ -f "$ENV_FILE" ] && stat -c '在（%a %U:%G, %s 字节）' "$ENV_FILE" || echo 不在)"
  # 键名清单（只看名字）
  if [ -f "$ENV_FILE" ]; then
    printf '  .env 里的键  : %s\n' "$(grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' "$ENV_FILE" 2>/dev/null | tr -d '=' | sort | tr '\n' ' ')"
  fi
}

# ── daemon 实际拿到的环境（读 /proc/PID/environ 的**键名**）──
proc_keys() {
  local pid="$1"
  [ -r "/proc/$pid/environ" ] || return 1
  tr '\0' '\n' < "/proc/$pid/environ" | sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' | sort
}

verify() {
  sec "验证（只看键名，不打印键值）"
  [ -x "$PY" ] && ok "部署树 python 可用：$PY" || bad "缺 $PY"
  if [ -f "$DROPIN" ]; then ok "drop-in 在：$DROPIN"; else bad "drop-in 不在：$DROPIN"; fi
  if systemctl show "$UNIT" -p EnvironmentFiles --value 2>/dev/null | grep -q "$ENV_FILE"; then
    ok "systemd 已把 $ENV_FILE 记为该单元的 EnvironmentFile"
  else
    bad "systemd 还没加载到 $ENV_FILE（daemon-reload 没跑？）"
  fi

  local pid
  pid="$(systemctl show "$UNIT" -p MainPID --value 2>/dev/null)"
  if [ -z "$pid" ] || [ "$pid" = "0" ]; then
    bad "daemon 没在跑，环境验证无从谈起"
    return
  fi
  ok "daemon pid=$pid"

  local keys missing=""
  keys="$(proc_keys "$pid")" || { warn "读不到 /proc/$pid/environ（权限？）"; return; }
  local name
  for name in TRIMUM_LLM_BASE_URL TRIMUM_LLM_MODEL TRIMUM_LLM_API_KEY_ENV JIAOWOISAN_API_KEY DEEPSEEK_API_KEY; do
    if printf '%s\n' "$keys" | grep -qx "$name"; then
      ok "daemon 环境里有 $name"
    else
      missing="$missing $name"
    fi
  done
  [ -n "$missing" ] && bad "daemon 环境里缺：$missing"

  if journalctl -u "$UNIT" --since '-3 min' 2>/dev/null | grep -qE 'Traceback|socket_start_failed'; then
    bad "最近 3 分钟 journal 里有 Traceback / socket_start_failed"
  else
    ok "最近 3 分钟 journal 干净"
  fi
}

smoke() {
  sec "网络冒烟：真调一次主模型（会花一次配额）"
  if [ ! -x "$PY" ]; then bad "缺 $PY，跳过"; return; fi
  local out
  out="$(TRIMUM_ENV_FILE="$ENV_FILE" "$PY" - <<'PYEOF' 2>&1
import json, sys, urllib.request
sys.path.insert(0, "/opt/trimum/src")
from trimum_core import env_file, llm_router as R
env_file.load_env_file()

def attempt(t):
    req = urllib.request.Request(
        t.base_url.rstrip("/") + "/chat/completions",
        data=json.dumps({
            "model": t.model,
            "messages": [{"role": "user", "content": "只回复两个字：可用"}],
            "temperature": 0, "max_tokens": 16,
        }).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {t.api_key}"},
        method="POST")
    with urllib.request.urlopen(req, timeout=t.timeout) as resp:
        body = json.loads(resp.read().decode())
    return body["choices"][0]["message"]["content"]

try:
    text, target = R.run_with_fallback(R.ROLE_POLICY, attempt)
    print(f"OK  走的 target：{target.label}  回复：{text.strip()[:40]}")
except Exception as exc:
    print(f"FAIL  {type(exc).__name__}: {exc}")
    raise SystemExit(1)
PYEOF
)"
  printf '%s\n' "$out" | tee -a "$EVIDENCE_LOG"
  if printf '%s' "$out" | grep -q '^OK'; then ok "主模型真调通过"; else bad "主模型真调失败"; fi
}

render_dropin() {
  cat > "$DROPIN" <<EOF
# trimum LLM 环境 —— 由 scripts/llm_env_dropin.sh 生成，别手改（重跑脚本即可）
# 作用：把 $ENV_FILE 里的 key 与模型路由喂给 daemon。
# 为什么需要：trmd.service 本身没有 EnvironmentFile，daemon 环境里只有 PATH 与 TRIMUM_SOCKET。
# 回滚：sudo bash scripts/llm_env_dropin.sh --rollback（= 删掉本文件 + 重启）
[Service]
EnvironmentFile=-$ENV_FILE
EOF
}

do_rollback() {
  sec "回滚：删掉 LLM 环境 drop-in"
  if [ -f "$DROPIN" ]; then
    cp -a "$DROPIN" "/tmp/30-llm-env.conf.removed.$(date +%s)" 2>/dev/null || true
    rm -f "$DROPIN"
    rmdir "$DROPIN_DIR" 2>/dev/null || true
    echo "  已删除 $DROPIN（副本留在 /tmp/）"
  else
    echo "  $DROPIN 本来就不存在（无需回滚）"
  fi
  systemctl daemon-reload
  systemctl restart "$UNIT"
  sleep 2
  sec "回滚后状态"
  systemctl is-active "$UNIT" >/dev/null 2>&1 && ok "$UNIT active" || bad "$UNIT 没起来"
  warn "daemon 现在不再读 $ENV_FILE（LLM 会走「无 key → 降级」路径）"
}

case "${1:---check}" in
  --check)
    show_state
    show_routing
    verify
    printf '\n  证据：%s\n' "$EVIDENCE_LOG"
    ;;
  --apply)
    need_root --apply
    show_state
    show_routing
    sec "前置（fail-closed）"
    if [ ! -f "$ENV_FILE" ]; then
      bad "$ENV_FILE 不存在 —— 先把 .env 推上去再 --apply"
      echo "前置不满足，一个字都没改。证据：$EVIDENCE_LOG" >&2
      exit 2
    fi
    ok "$ENV_FILE 在"
    if ! grep -qE '^[A-Za-z_]+_API_KEY=' "$ENV_FILE"; then
      warn "$ENV_FILE 里似乎没有 *_API_KEY（只有键名检查，不打印值）"
    else
      ok "$ENV_FILE 里有 *_API_KEY 键"
    fi

    STEP="render dropin"
    install -d -m 0755 "$DROPIN_DIR"
    render_dropin
    echo "  已写入 $DROPIN"
    STEP="daemon-reload"
    systemctl daemon-reload
    STEP="restart"
    systemctl restart "$UNIT"

    STEP="verify"
    sleep 2
    verify
    show_routing
    if [ "$FAIL" -eq 0 ]; then
      sec "完成"
      printf '  结果：daemon 已能读到 %s 里的 LLM key 与模型路由\n' "$ENV_FILE"
      printf '  真调冒烟：sudo bash %s --smoke\n' "$0"
      printf '  回滚    ：sudo bash %s --rollback\n' "$0"
    else
      bad "验证有 FAIL，建议回滚：sudo bash $0 --rollback"
    fi
    printf '\n  证据：%s\n' "$EVIDENCE_LOG"
    [ "$FAIL" -eq 0 ] || exit 1
    ;;
  --smoke)
    need_root --smoke
    smoke
    printf '\n  证据：%s\n' "$EVIDENCE_LOG"
    [ "$FAIL" -eq 0 ] || exit 1
    ;;
  --rollback)
    need_root --rollback
    do_rollback
    ;;
  *)
    echo "用法：sudo bash $0 [--check|--apply|--smoke|--rollback]" >&2
    exit 2
    ;;
esac