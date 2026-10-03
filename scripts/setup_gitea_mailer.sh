#!/usr/bin/env bash
# 给真机 Gitea 配 SMTP mailer（163 邮箱 + 授权码）。
#
# 背景：Gitea 本地账号必须有密码；给「博客好友同步」发的临时口令、
#       「忘记密码」重置，都要 mailer 才能送达。
#
# 凭据来源：~/trimum/.env 的 EMAIL / EMAIL_AUTH_TOKEN（163 授权码，不是登录密码）。
#
# 用法：
#   sudo bash scripts/setup_gitea_mailer.sh              # dry-run
#   sudo bash scripts/setup_gitea_mailer.sh --apply      # 落地 + 重启 gitea + 实测发信
#   sudo bash scripts/setup_gitea_mailer.sh --apply --rollback
#
# 安全：改前备份 app.ini；重启后校验 gitea 起来；实测发信不过自动回滚（--keep 可禁）。
set -uo pipefail

APPLY=0; ROLLBACK=0; KEEP=0
for a in "$@"; do case "$a" in
  --apply) APPLY=1;; --dry-run) APPLY=0;; --rollback) ROLLBACK=1;;
  --keep) KEEP=1;; -h|--help) sed -n '2,20p' "$0"|sed 's/^# \{0,1\}//'; exit 0;;
  *) echo "未知参数：$a" >&2; exit 2;; esac; done

CONF=/etc/gitea/app.ini
ENVF=/home/guzhujushi/trimum/.env
say(){ printf "%s\n" "$*"; }
ok(){ printf "  [ok] %s\n" "$*"; }
warn(){ printf "  [!!] %s\n" "$*"; }

[ "$(id -u)" -eq 0 ] || { echo "需要 root：sudo bash $0 $*" >&2; exit 1; }
[ -f "$CONF" ] || { echo "找不到 $CONF" >&2; exit 1; }
[ -f "$ENVF" ] || { echo "找不到 $ENVF" >&2; exit 1; }
EMAIL=$(sed -n 's/^EMAIL=//p' "$ENVF" | head -1 | tr -d '\r' | tr -d '"'"'"'')
PASSWD=$(sed -n 's/^EMAIL_AUTH_TOKEN=//p' "$ENVF" | head -1 | tr -d '\r' | tr -d '"'"'"'')
[ -n "$EMAIL" ] && [ -n "$PASSWD" ] || { echo "$ENVF 缺 EMAIL / EMAIL_AUTH_TOKEN" >&2; exit 1; }
DOMAIN="${EMAIL#*@}"; SMTP="smtp.${DOMAIN}"

say "== 现状 =="
say "  config      : $CONF"
say "  发件邮箱    : $EMAIL"
say "  SMTP        : $SMTP:465 (smtps)"
say "  现有 mailer : $(grep -qi '^\[mailer\]' "$CONF" && echo '已存在 [mailer]（将覆盖）' || echo '无')"

if [ "$ROLLBACK" -eq 1 ]; then
  say; say "== 回滚 =="; [ "$APPLY" -eq 1 ] || { say "  （dry-run：加 --apply）"; exit 0; }
  BAK=$(ls -1t "$CONF".bak_trimum_mailer_* 2>/dev/null | head -1)
  [ -n "$BAK" ] || { warn "找不到备份，无法回滚"; exit 1; }
  cp -a "$BAK" "$CONF" && ok "已还原 $BAK"; systemctl restart gitea && ok "gitea 已重启"
  exit 0
fi

say; say "== 计划 =="
say "  在 $CONF 写入/替换 [mailer] 段（ENABLED/PROTOCOL/SMTP_ADDR/PORT/FROM/USER/PASSWD），备份后重启 gitea"
[ "$APPLY" -eq 1 ] || { say; say "（dry-run：确认后加 --apply）"; exit 0; }

BAK="$CONF.bak_trimum_mailer_$(date +%Y%m%d-%H%M%S)"
cp -a "$CONF" "$BAK" && ok "已备份 $BAK"

# 删掉旧 [mailer] 段（到下一个 [ 段或文件尾），再追加新段
python3 - "$CONF" "$EMAIL" "$PASSWD" "$SMTP" <<'PY'
import sys, re
conf, email, passwd, smtp = sys.argv[1:5]
lines = open(conf, encoding='utf-8').read().split('\n')
out, skip = [], False
for ln in lines:
    if re.match(r'^\[mailer\]\s*$', ln, re.I): skip = True; continue
    if skip and re.match(r'^\[', ln): skip = False
    if skip: continue
    out.append(ln)
while out and out[-1].strip() == '': out.pop()
out += ['', '[mailer]',
        'ENABLED = true',
        'PROTOCOL = smtps',
        f'SMTP_ADDR = {smtp}',
        'SMTP_PORT = 465',
        f'FROM = {email}',
        f'USER = {email}',
        f'PASSWD = {passwd}',
        '']
open(conf, 'w', encoding='utf-8').write('\n'.join(out))
print('mailer section written')
PY
ok "[mailer] 已写入"

systemctl restart gitea; sleep 3
if [ "$(systemctl is-active gitea)" = active ] && curl -sf -m 5 http://127.0.0.1:3000/api/v1/version >/dev/null; then
  ok "gitea 已重启且 API 正常"
else
  warn "gitea 起不来！"; [ "$KEEP" -eq 0 ] && { cp -a "$BAK" "$CONF"; systemctl restart gitea; ok "已回滚"; }; exit 1
fi

say; say "== 实测发信 =="
if python3 - <<PY
import smtplib, ssl
with smtplib.SMTP_SSL('$SMTP', 465, timeout=20, context=ssl.create_default_context()) as s:
    s.login('$EMAIL', '$PASSWD')
    s.sendmail('$EMAIL', ['$EMAIL'], 'From: $EMAIL\r\nTo: $EMAIL\r\nSubject: [trimum] gitea mailer test\r\n\r\nmailer OK')
print('sent')
PY
then ok "测试邮件已发往 $EMAIL（查收）"; else
  warn "发信失败"; [ "$KEEP" -eq 0 ] && { cp -a "$BAK" "$CONF"; systemctl restart gitea; ok "已回滚"; }; exit 1
fi
say; say "完成。Gitea 现在可发「忘记密码 / 新用户通知」邮件。"
