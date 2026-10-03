#!/usr/bin/env python3
"""把博客的「好友(role=friend)」同步成 Gitea 账号。

源：博客 SQLite 的 users+friends（导出成 JSON：[{"id","username","email"}]）。
目标：真机 Gitea admin API（POST /api/v1/admin/users）。

- 中文用户名 -> 拼音（pypinyin；失败则回退 user<id>），只保留 [a-z0-9_.-]，冲突自动加后缀。
- 密码不能从博客迁移（bcrypt）=> 生成随机临时口令 + must_change_password=true。
- 幂等：按 email 判重，已存在则跳过。
- 默认 dry-run；--apply 才真建号；--send-notify 才让 Gitea 发「新账号」邮件（需 mailer 已配）。

用法：
  .venv/bin/python scripts/sync_blog_friends_to_gitea.py --source tmp/blog-friends.json
  .venv/bin/python scripts/sync_blog_friends_to_gitea.py --source tmp/blog-friends.json --apply
  ... --apply --send-notify
凭据：~/trimum/.env 的 GITEA_ADMIN_TOKEN（或环境变量）。
"""
from __future__ import annotations
import argparse, json, os, re, secrets, string, sys, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_token() -> str:
    tok = os.environ.get("GITEA_ADMIN_TOKEN")
    if tok:
        return tok
    envf = os.path.join(ROOT, ".env")
    if os.path.isfile(envf):
        for line in open(envf, encoding="utf-8"):
            line = line.strip()
            if line.startswith("GITEA_ADMIN_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("找不到 GITEA_ADMIN_TOKEN（放 ~/trimum/.env 或设环境变量）")

def api(url: str, token: str, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"token {token}")
    if data: req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        try: payload = json.loads(e.read().decode() or "null")
        except Exception: payload = None
        return e.code, payload

def to_username(name: str, uid: int) -> str:
    if re.fullmatch(r"[A-Za-z0-9_.-]+", name or ""):
        base = name
    else:
        try:
            from pypinyin import lazy_pinyin
            base = "".join(lazy_pinyin(name))
        except Exception:
            base = f"user{uid}"
    base = re.sub(r"[^A-Za-z0-9_.-]", "", base).lower().lstrip("._-") or f"user{uid}"
    return base[:39]

def gen_password(n=16) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(n))
        if any(c.islower() for c in pw) and any(c.isupper() for c in pw) and any(c.isdigit() for c in pw):
            return pw

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=os.path.join(ROOT, "tmp", "blog-friends.json"))
    ap.add_argument("--gitea-url", default="http://127.0.0.1:3000")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--send-notify", action="store_true")
    ap.add_argument("--creds-out", default=None, help="生成的口令写这里（0600）")
    a = ap.parse_args()

    token = load_token()
    friends = json.load(open(a.source, encoding="utf-8"))
    st, existing = api(f"{a.gitea_url}/api/v1/admin/users?limit=100", token)
    if st != 200: sys.exit(f"列用户失败 HTTP {st}: {existing}")
    by_email = {u["email"].lower(): u["login"] for u in existing}
    used = {u["login"].lower() for u in existing}

    plan, creds = [], []
    for f in friends:
        email = (f.get("email") or "").lower()
        uname = to_username(f.get("username", ""), f.get("id", 0))
        while uname in used:
            uname = (uname[:37] + secrets.token_hex(1))
        existing_login = by_email.get(email)
        if existing_login:
            plan.append((f["username"], uname, email, f"跳过（已存在: {existing_login}）"))
            continue
        pw = gen_password()
        used.add(uname)
        creds.append((uname, email, pw))
        plan.append((f["username"], uname, email, "创建"))

    print(f"{'博客名':<10} {'Gitea 用户名':<24} {'邮箱':<24} 动作")
    for src, uname, email, act in plan:
        print(f"{src:<10} {uname:<24} {email:<24} {act}")

    if not a.apply:
        print("\n(dry-run；加 --apply 真建号)")
        return 0

    made = []
    for (src, uname, email, act), (cu, ce, cp) in zip([p for p in plan if p[3] == "创建"], creds):
        st, res = api(f"{a.gitea_url}/api/v1/admin/users", token, "POST", {
            "username": uname, "email": email, "password": cp,
            "must_change_password": True, "send_notify": bool(a.send_notify),
        })
        print(("  [ok] " if st == 201 else f"  [!! HTTP {st}] ") + f"{uname} <{email}> {'' if st==201 else res}")
        if st == 201: made.append((uname, email, cp))

    if made:
        out = a.creds_out or os.path.join(ROOT, "tmp", "gitea-friend-credentials.txt")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write("# 博客好友 -> Gitea 账号（临时口令，首登需改密；用后删除）\n")
            for u, e, p in made: fh.write(f"{u}\t{e}\t{p}\n")
        os.chmod(out, 0o600)
        print(f"\n口令已写 {out}（0600）：{len(made)} 条")
    if not a.send_notify:
        print("未发通知邮件（加 --send-notify 才发；或本人用上面的口令线下转交）")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
