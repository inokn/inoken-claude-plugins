"""判定とレポートを作る（run.sh report）。

出力:
  .php-upgrade/report.md      人が読むレポート
  .php-upgrade/一覧表用.tsv    棚卸し表の右側に貼り足す1行（点検日 / 移行先PHP / 判定 / 要修正件数 / 要更新プラグイン数 / 主な作業）
  .php-upgrade/summary.json   finalize と Claude が読む要約

判定: A=そのままで可 / B=更新で対応 / C=コードの修正が必要 / D=作り直しを検討
"""
import re
import subprocess

from common import OUT, load_json, notes, require, save_json, today, vtuple

tgt = require("target.json", "run.sh target <今のPHP版>")
inv = require("inventory.json", "run.sh inventory")
scan = require("scan.json", "run.sh scan")

D_THRESHOLD = 200   # 自分で直すコードのエラーがこれ以上なら、作り直しも選択肢に入れる
TB = tgt["target_branch"]

def composer_allows(cons, version):
    """composer の PHP 指定（^7.4 || ^8.0 など）が version を許すか。読めなければ None。"""
    v = vtuple(version) + (0, 0, 0)
    v = v[:3]

    def pad(x):
        t = vtuple(x)
        return (t + (0, 0, 0))[:3], len(t)

    def ok(part):
        part = part.strip()
        if not part or part == "*":
            return True
        m = re.match(r"^(\^|~|>=|<=|>|<|==|=|!=)?\s*v?([\d.*x]+)", part)
        if not m:
            raise ValueError(part)
        op, ver = m.group(1) or "", m.group(2).rstrip(".")
        if "*" in ver or "x" in ver:
            base = [int(x) for x in re.findall(r"\d+", ver)]
            return list(v[:len(base)]) == base
        b, n = pad(ver)
        if op == "^":
            upper = (b[0] + 1, 0, 0) if b[0] > 0 else (0, b[1] + 1, 0)
            return b <= v < upper
        if op == "~":
            upper = (b[0] + 1, 0, 0) if n <= 2 else (b[0], b[1] + 1, 0)
            return b <= v < upper
        return {">=": v >= b, "<=": v <= b, ">": v > b, "<": v < b, "!=": v != b}.get(op, v[:n] == b[:n])

    try:
        for alt in re.split(r"\s*\|\|?\s*", cons):
            parts = [x for x in re.split(r"[\s,]+", alt.strip()) if x]
            if all(ok(x) for x in parts):
                return True
        return False
    except ValueError:
        return None


comps = {("mu-plugins" if c["kind"] == "mu-plugins" else "dropins" if c["kind"] == "dropins"
          else f"{c['kind']}:{c['slug']}"): c for c in inv["components"]}


def editable(comp_id):
    """自分たちで直してよいコードか（自作）。"""
    if comp_id in ("site", "orphan", "mu-plugins", "dropins", "vendor"):
        return comp_id != "vendor"
    c = comps.get(comp_id)
    return bool(c and c.get("origin") == "custom")


def comp_label(comp_id):
    if comp_id == "site":
        return "サイト本体（自作のPHP）"
    if comp_id == "orphan":
        return "wp-content 内のヘッダーの無いPHP"
    if comp_id == "vendor":
        return "composer の vendor/"
    c = comps.get(comp_id)
    if not c:
        return comp_id
    kind = {"plugin": "プラグイン", "theme": "テーマ"}.get(c["kind"], "")
    return f"{kind}「{c.get('name') or c['slug']}」（{c['slug']}）" if kind else c.get("name", comp_id)


issues = scan.get("issues", [])
errors = [i for i in issues if i["type"] == "ERROR"]
warns = [i for i in issues if i["type"] == "WARNING"]
err_edit = [i for i in errors if editable(i["component"])]
err_other = [i for i in errors if not editable(i["component"])]


def spots(items):
    """直す箇所の数（同じ行への複数の指摘は1箇所と数える）。"""
    return len({(i["file"], i["line"]) for i in items})

# ---- 作業の洗い出し
tasks = []          # (区分, 内容)
updates = []        # 更新が要るプラグイン・テーマ
w = inv.get("wordpress")
patch_only = tgt["mode"] in ("none", "patch")

if w and not patch_only:
    need = tgt.get("wordpress_min")
    if w.get("version") and need and vtuple(w["version"]) < vtuple(need):
        tasks.append(("必須", f"WordPress 本体を更新（今 {w['version']} → 最新 {w.get('latest') or ''}）。PHP {TB} には {need} 以上が必要"))
    elif w.get("version") and w.get("latest") and vtuple(w["version"]) < vtuple(w["latest"]):
        tasks.append(("推奨", f"WordPress 本体を最新 {w['latest']} へ更新（今 {w['version']}）"))

for cid, c in comps.items():
    if c.get("origin") != "wporg" or patch_only:
        continue
    info = c.get("wporg", {})
    if c.get("outdated"):
        rp = info.get("requires_php")
        note = f"（最新版は PHP {rp} 以上が必要なため、この移行先では最新まで上げられない）" if rp and vtuple(rp) > vtuple(TB) else ""
        updates.append(c)
        tasks.append(("必須", f"{comp_label(cid)} を {c.get('version')} → {info.get('latest')} に更新{note}"))
    elif c.get("abandoned"):
        tasks.append(("検討", f"{comp_label(cid)} は最終更新 {info.get('last_updated')}。2年以上更新が無いので置き換えを検討"))

for cid, c in comps.items():
    if c.get("origin") == "closed":
        n = sum(1 for i in errors if i["component"] == cid)
        tasks.append(("必須" if n else "検討", f"{comp_label(cid)} は WordPress.org で配布停止。代わりのプラグインへの置き換えを検討" + (f"（エラー {n} 件）" if n else "")))

for cid, c in comps.items():
    if c.get("origin") == "custom" and (c.get("wporg") or {}).get("status") == "listed":
        tasks.append(("確認", f"{comp_label(cid)} は WordPress.org の「{c['wporg'].get('name')}」と同じフォルダ名の別物。"
                      "一括更新で上書きされる危険があるので、更新から除外する（フォルダ名の変更も検討）"))

ext_with_err = sorted({i["component"] for i in err_other})
for cid in ext_with_err:
    n = spots([i for i in err_other if i["component"] == cid])
    c = comps.get(cid, {})
    tasks.append(("必須", f"{comp_label(cid)}: {n} 箇所。有料・外部配布なら販売元の最新版に更新、自作なら修正（{c.get('note', '出どころ要確認')}）"))

if inv.get("uploads_php"):
    tasks.append(("確認", f"wp-content/uploads の中の PHP ファイル {len(inv['uploads_php'])} 件を確認（改ざんの疑い）: "
                  + ", ".join(inv["uploads_php"][:3])))

edit_comps = sorted({i["component"] for i in err_edit})
for cid in edit_comps:
    n = spots([i for i in err_edit if i["component"] == cid])
    tasks.append(("修正", f"{comp_label(cid)}: {n} 箇所をコード修正"))

if inv.get("composer_php") and not patch_only:
    cons = inv["composer_php"]
    allowed = composer_allows(cons, tgt["target"])
    if allowed is False:
        tasks.append(("必須", f"composer.json の PHP 指定（{cons}）が PHP {tgt['target']} を許していない。依存パッケージごと見直しが必要"))
    elif allowed is None:
        tasks.append(("確認", f"composer.json の PHP 指定（{cons}）が読めない。PHP {tgt['target']} を許すか確認"))
if inv.get("frameworks") and not patch_only:
    for fw in inv["frameworks"]:
        tasks.append(("確認", f"{fw['name']} {fw.get('version') or ''} が PHP {TB} に対応しているか公式のサポート表で確認"))

# ---- 判定
if tgt["mode"] == "none":
    grade, why = "A", "すでに脆弱性の修正版"
elif patch_only:
    grade, why = "A", f"同じ系列内のパッチ更新（{tgt['current']} → {tgt['target']}）。コードの修正は不要"
elif spots(err_edit) >= D_THRESHOLD:
    grade, why = "D", f"自作コードの要修正が {spots(err_edit)} 箇所。直すより作り直しが安い可能性がある（人が判断）"
elif err_edit or ext_with_err or any(l == "必須" and t.startswith("composer.json") for l, t in tasks):
    grade, why = "C", (f"コードの修正が必要（自作 {spots(err_edit)} 箇所 / 出どころ要確認 {spots(err_other)} 箇所）"
                       if err_edit or ext_with_err else "composer の依存の見直しが必要")
elif any(t[0] == "必須" for t in tasks):
    grade, why = "B", "本体・プラグインの更新で対応できる"
else:
    grade, why = "A", "点検で問題なし"

# 一覧表の1セルに収まる短い要約
mw = []
if any(t.startswith("WordPress 本体") and l == "必須" for l, t in tasks):
    mw.append("WP本体更新")
if updates:
    mw.append(f"プラグイン等の更新{len(updates)}件")
fix_names = [comps[c]["slug"] if c in comps else {"site": "サイト本体", "orphan": "wp-content内"}.get(c, c)
             for c in edit_comps + ext_with_err]
if fix_names:
    mw.append("修正: " + ", ".join(fix_names))
if any("配布停止" in t for _, t in tasks):
    mw.append("配布停止プラグインの置き換え")
if any(t.startswith("composer.json") and l == "必須" for l, t in tasks):
    mw.append("composerの依存見直し")
if warns and not patch_only:
    mw.append(f"非推奨{spots(warns)}箇所")
main_work = " / ".join(mw) or ("PHPのパッチ更新のみ" if patch_only else "PHPの切り替えのみ")
if TB == "8.2" and tgt["mode"] != "none":
    main_work += "（8.2は2026-12末で修正終了→次は8.3以上）"

# 最初の点検の結果を覚えておく（修正後に report し直しても、一覧表には「どれだけ手が要ったか」を残す）
cur = {"target": tgt["target"], "grade": grade, "why": why, "spots": spots(errors), "date": today()}
initial = load_json(OUT / "initial.json")
if not initial or initial.get("target") != tgt["target"]:
    initial = cur
    save_json(OUT / "initial.json", initial)


def changed_files():
    """取得時点（baseline）から変わったファイル（修正したファイル）。"""
    r = subprocess.run(["git", "-c", "core.quotepath=false", "diff", "--name-only", "php-upgrade-baseline", "--", ".",
                        ":(exclude).php-upgrade"], capture_output=True, text=True, encoding="utf-8")
    u = subprocess.run(["git", "-c", "core.quotepath=false", "ls-files", "--others", "--exclude-standard"],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        return []
    return sorted(set(x for x in (r.stdout + u.stdout).splitlines() if x and not x.startswith(".php-upgrade/")))


fixed = changed_files()
if fixed:
    left = spots(err_edit)
    main_work = (f"自作コード修正済み（{len(fixed)}ファイル）" + (f"・残り{left}箇所" if left else "")) + " / " + main_work

summary = {
    "date": today(), "site": inv["root"], "type": inv["type"],
    "current": tgt["current"], "target": tgt["target"], "target_branch": TB, "mode": tgt["mode"],
    "grade": grade, "why": why, "errors_editable": spots(err_edit), "errors_external": spots(err_other),
    "warnings": spots(warns), "updates": len(updates), "tasks": [{"level": l, "text": t} for l, t in tasks],
    "scanned_files": scan.get("files", 0), "lint": scan.get("lint"), "skipped": scan.get("skipped"),
    "eol_note": TB == "8.2", "notes": notes(),
    "initial": initial, "fixed_files": fixed,
}
save_json(OUT / "summary.json", summary)

# ---- 一覧表用の1行
row = [today(), tgt["target"], initial["grade"], str(initial["spots"]), str(len(updates)), main_work.replace("\t", " ")]
(OUT / "一覧表用.tsv").write_text("\t".join(row) + "\n", encoding="utf-8")

# ---- report.md
L = []
L.append(f"# PHP 移行点検レポート: {inv['root']}")
L.append("")
L.append(f"- 点検日: {today()}")
L.append(f"- サイトの種類: {({'wordpress': 'WordPress', 'framework': 'フレームワーク', 'php': '素のPHP'})[inv['type']]}"
         + (f"（WordPress {w['version']}、最新 {w.get('latest') or '不明'}）" if w else ""))
for fw in inv.get("frameworks", []):
    L.append(f"- フレームワーク: {fw['name']} {fw.get('version') or ''}")
L.append(f"- PHP: **{tgt['current']} → {tgt['target']}**（{tgt['reason']}）")
if fixed and initial["grade"] != grade:
    L.append(f"- 判定: **{initial['grade']}**（修正前: {initial['why']}）→ 修正後の今は **{grade}** — {why}")
else:
    L.append(f"- 判定: **{grade}** — {why}")
if fixed:
    L.append(f"- 修正したファイル: {len(fixed)} 件（{', '.join('`' + x + '`' for x in fixed[:10])}{' ほか' if len(fixed) > 10 else ''}）")
L.append("")
if TB == "8.2":
    L.append(f"> ⚠️ **PHP 8.2 のセキュリティ修正は {tgt['security_support_until']} で終わります。** 今回の 8.2 への移行は応急処置です。"
             "次は 8.3 以上への移行を計画してください。")
    L.append("")

L.append("## やること")
L.append("")
if tasks:
    for lvl, t in tasks:
        L.append(f"- [ ] **{lvl}** {t}")
else:
    L.append("- [ ] サーバーの PHP を移行先へ切り替える（コード側の作業はなし）")
L.append("")

extra = notes()
if extra:
    L.append("## 点検ツールでは見つからない確認事項（確認事項.md）")
    L.append("")
    for t in extra:
        L.append(f"- [ ] {t}")
    L.append("")

if not patch_only:
    L.append("## 点検の結果")
    L.append("")
    if scan.get("skipped"):
        L.append(f"点検は省きました: {scan.get('skip_reason')}")
    else:
        L.append(f"- 点検したファイル: {scan.get('files', 0)}（{scan.get('standard')} / testVersion {scan.get('testVersion')}）")
        L.append(f"- エラー（移行先で動かない）: {spots(errors)} 箇所 ／ 警告（非推奨。今は動く）: {spots(warns)} 箇所")
        L.append("- 構文チェック（php -l）: " + (f"実施（{scan['lint']['php']}）" if scan.get("lint") else "省略（移行先と同じ系列の PHP が手元に無い）"))
        L.append("- 点検していないもの: WordPress 本体、WordPress.org 配布で更新版があるもの（更新で対応）、"
                 "wp-config.php / .env（認証情報）、uploads・キャッシュ")
        L.append("")
        by = {}
        for i in issues:
            by.setdefault(i["component"], []).append(i)
        for cid in sorted(by, key=lambda k: (not editable(k), k)):
            items = by[cid]
            e = spots([i for i in items if i["type"] == "ERROR"])
            wn = spots([i for i in items if i["type"] == "WARNING"])
            L.append(f"### {comp_label(cid)} — エラー {e} 箇所 / 警告 {wn} 箇所"
                     + ("" if editable(cid) else "（出どころ要確認: 自作なら修正、有料・外部配布なら販売元の最新版へ）"))
            L.append("")
            L.append("| 種別 | 場所 | 分類 | 内容 |")
            L.append("|---|---|---|---|")
            for i in items[:80]:
                msg = (i["message"] or "").replace("|", "\\|")
                L.append(f"| {'エラー' if i['type'] == 'ERROR' else '警告'} | `{i['file']}:{i['line']}` | {i['category']} | {msg} |")
            if len(items) > 80:
                L.append(f"| … | ほか {len(items) - 80} 件 | | scan.json を参照 |")
            L.append("")
        if scan.get("tool_errors"):
            L.append(f"⚠️ 点検ツールが読めなかったファイルが {len(scan['tool_errors'])} 件あります（scan.json の tool_errors）。手で確認してください。")
            L.append("")

enc = inv.get("encodings") or {}
if enc:
    L.append("## 文字コードの注意")
    L.append("")
    for k, v in enc.items():
        L.append(f"- {k}: {len(v)} ファイル（例: {', '.join('`' + x + '`' for x in v[:5])}）")
    L.append("")
    L.append("修正するときは、元の文字コードのまま保存すること（UTF-8 に変えると画面が文字化けする）。")
    L.append("")

if inv.get("components"):
    L.append("## プラグイン・テーマ")
    L.append("")
    L.append("| 種類 | フォルダ | 名前 | 今の版 | 最新 | 出どころ | 状態 |")
    L.append("|---|---|---|---|---|---|---|")
    org = {"wporg": "WordPress.org", "external": "ディレクトリ外", "custom": "自作", "closed": "配布停止", "unknown": "不明"}
    for c in inv["components"]:
        info = c.get("wporg") or {}
        state = "更新あり" if c.get("outdated") else ("2年以上更新なし" if c.get("abandoned") else (c.get("note") or ""))
        L.append(f"| {c['kind']} | `{c['slug']}` | {c.get('name') or ''} | {c.get('version') or ''} | {info.get('latest') or ''} | {org.get(c.get('origin'), '')} | {state} |")
    L.append("")

for n in inv.get("notes", []):
    L.append(f"- ※ {n}")
L.append("")
L.append("## この点検でわからないこと")
L.append("")
L.append("- コードを読んで調べる静的な点検です。DB・外部API・メール送信など、**動かしてみないとわからない不具合は、検証環境での確認が必須**です。")
L.append("- 点検ツール PHPCompatibility 10 は alpha 版です。見落としや誤検知がありえます。")
L.append("- 有料プラグインや外部配布のものは、販売元の対応状況もあわせて確認してください。")
L.append("")
L.append("## 一覧表に貼る1行")
L.append("")
L.append("`一覧表用.tsv` の中身を、棚卸し表の右側（「備考」の次）に貼り付けます。列: 点検日 / 移行先PHP / 判定 / 要修正箇所 / 要更新プラグイン数 / 主な作業")
L.append("")
L.append("判定と要修正箇所は**最初の点検の結果**（どれだけ手が要ったか）。修正したら「主な作業」に「自作コード修正済み」と出る。")
L.append("")
(OUT / "report.md").write_text("\n".join(L), encoding="utf-8")

print(f"判定: {grade} — {why}" + (f"（修正前は {initial['grade']}）" if fixed and initial["grade"] != grade else ""))
for lvl, t in tasks:
    print(f"  [{lvl}] {t}")
if TB == "8.2":
    print(f"  ⚠️ 8.2 は {tgt['security_support_until']} でセキュリティ修正が終わります（応急処置）")
print(f"レポート: {OUT / 'report.md'} ／ 一覧表用: {OUT / '一覧表用.tsv'}")
