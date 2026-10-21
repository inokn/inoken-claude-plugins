"""修正の差分と、人がやる作業票を作る（run.sh finalize [--allow-stale]）。

- 未コミットの修正があればコミットする（手元の git だけ）
- 取得時点（タグ php-upgrade-baseline）からの差分を出す
    .php-upgrade/アップロード用/        上げるファイル（伏せたパスワードを本物に戻したもの）
    .php-upgrade/修正差分.patch       差分（レビュー用。パスワードは伏せたまま）
    .php-upgrade/アップロード一覧.txt   検証環境・本番へ上げるファイル
    .php-upgrade/元ファイル/           変更前のファイル（問題が出たときに上げ直して戻す。本物の値に戻してある）

作業フォルダの中のファイルはパスワードが伏せてあるので、そのまま上げるとサイトが止まる。必ずアップロード用/ から上げる。
    .php-upgrade/作業票.md             検証 → 本番 → 戻し方 のチェックリスト
"""
import argparse
import os
import shutil
import subprocess
from pathlib import Path

from common import OUT, die, load_json, notes, require, today
from secrets_lib import PH_RE, load_store, state, unmask_bytes

ap = argparse.ArgumentParser()
ap.add_argument("--allow-stale", action="store_true", help="修正後に点検し直していなくても作る")
a = ap.parse_args()

summary = require("summary.json", "run.sh report")
tgt = require("target.json", "run.sh target <今のPHP版>")
BASE = "php-upgrade-baseline"
G = ["git", "-c", "user.name=php-upgrade", "-c", "user.email=php-upgrade@localhost",
     "-c", "core.autocrlf=false", "-c", "core.quotepath=false"]


def git(*args, check=True):
    r = subprocess.run(G + list(args), capture_output=True)
    if check and r.returncode != 0:
        die("git " + " ".join(args) + " が失敗しました:\n" + r.stderr.decode("utf-8", "replace"))
    return r.stdout


if subprocess.run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{BASE}"], capture_output=True).returncode != 0:
    die("取得時点の記録がありません。先に run.sh baseline を実行してください。")

pending = load_json(OUT / "recode.json", {})
if pending:
    die("UTF-8 に変換したままのファイルがあります。run.sh recode close で元の文字コードに戻してください:\n  "
        + "\n  ".join(pending))

# 修正をコミット（手元だけ）
git("add", "-A")
if git("diff", "--cached", "--name-only").strip():
    git("commit", "-q", "-m", f"PHP {tgt['target']} 対応の修正（php-upgrade）")

changes = []
raw = git("diff", "--name-status", "-z", "--no-renames", BASE, "HEAD").decode("utf-8").split("\0")
for i in range(0, len(raw) - 1, 2):
    status, path = raw[i], raw[i + 1]
    if path.startswith(".php-upgrade/"):
        continue
    changes.append((status, path))

# 修正したのに点検し直していないなら止める
scan_mtime = (OUT / "scan.json").stat().st_mtime if (OUT / "scan.json").exists() else 0
stale = [p for s, p in changes if s != "D" and os.path.exists(p) and os.path.getmtime(p) > scan_mtime]
if stale and not a.allow_stale:
    die("修正したあとに点検し直していません。run.sh scan → run.sh report を実行してから、もう一度 finalize してください。\n"
        "  例: " + ", ".join(stale[:5]))

# 差分・一覧・元ファイル
(OUT / "修正差分.patch").write_bytes(git("diff", "--binary", BASE, "HEAD", "--", ".", ":(exclude).php-upgrade"))
# 伏せた値を本物に戻して書き出す（作業フォルダの中は伏せたまま）
mst = state()
store = load_store(mst)
if mst["files"] and not store:
    die("伏せたパスワードの保存先が見つかりません。点検ツールの置き場所（secrets/）を消していないか確認してください。")


def export(dst, data, where):
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        dst.write_bytes(unmask_bytes(data, store, where))
    except ValueError as e:
        die(str(e))


orig, upd = OUT / "元ファイル", OUT / "アップロード用"
for d in (orig, upd):
    if d.exists():
        shutil.rmtree(d)
up, dele, added = [], [], []
for status, path in changes:
    if status in ("M", "D", "T"):
        export(orig / path, git("show", f"{BASE}:{path}"), path)
    if status != "D":
        export(upd / path, Path(path).read_bytes(), path)
    if status == "D":
        dele.append(path)
    else:
        up.append(path)
        if status == "A":
            added.append(path)
# 書き出したものに印が残っていないか（残っていたらサイトが止まる）
left = [str(p) for d in (orig, upd) if d.exists() for p in d.rglob("*") if p.is_file() and PH_RE.search(p.read_bytes())]
if left:
    die("本物の値に戻せなかったファイルがあります（印が残っている）: " + ", ".join(left[:5]))

lst = ["# アップロードするファイル（サイトのルートからの相対パス）",
       "# ⚠️ 上げるのは .php-upgrade/アップロード用/ の中のファイル。作業フォルダの中のファイルはパスワードが伏せてある"] + up
if dele:
    lst += ["", "# サーバーから削除するファイル（手作業。削除前にバックアップ）"] + dele
(OUT / "アップロード一覧.txt").write_text("\n".join(lst) + "\n", encoding="utf-8")

# 作業票
s = summary
w = load_json(OUT / "inventory.json", {}).get("wordpress")
L = [f"# 作業票: {s['site']}（PHP {s['current']} → {s['target']}）", "",
     f"- 作成日: {today()}", f"- 判定: **{s['grade']}** — {s['why']}",
     f"- 修正したファイル: {len(up)} 件" + (f"（うち新規 {len(added)} 件）" if added else "") + (f"／ 削除 {len(dele)} 件" if dele else ""), ""]
if s.get("eol_note"):
    L += [f"> ⚠️ PHP 8.2 のセキュリティ修正は {tgt['security_support_until']} で終わります。今回は応急処置です。次は 8.3 以上を計画してください。", ""]
L += ["**AI はサーバーに触れていません。以下はすべて人が行います。** 検証環境で確認してから本番へ。", "",
      "## 0. 事前準備", "",
      "- [ ] 本番のファイル一式をバックアップ（FTPでダウンロード）",
      "- [ ] 本番のデータベースをバックアップ" if w else "- [ ] データベースがあればバックアップ",
      "- [ ] 検証環境が本番と同じ状態か確認（違うなら本番から複製し直す）", "",
      "## 1. 検証環境", ""]
pre = [t["text"] for t in s["tasks"] if t["level"] in ("必須", "推奨", "検討", "確認") and "コード修正" not in t["text"]]
if pre:
    L.append("- [ ] 次の更新・確認を検証環境で行う")
    L += [f"    - [ ] {t}" for t in pre]
if up:
    L.append("- [ ] **`.php-upgrade/アップロード用/` の中身**を、フォルダ構成をそのまま検証環境へアップロード（一覧は `アップロード一覧.txt`）")
    if mst["files"]:
        L.append("    - ⚠️ 作業フォルダの中のファイルはパスワードが伏せてある（`__PHPUP_SECRET_…__`）。**作業フォルダから直接上げるとサイトが止まる**")
if dele:
    L.append("- [ ] `アップロード一覧.txt` の「削除するファイル」を検証環境から削除")
extra = notes()
L += [f"- [ ] 検証環境の PHP を **{s['target']}** に切り替える",
      "- [ ] 確認: トップページ・主要な下層ページが表示される",
      "- [ ] 確認: お問い合わせなどのフォームを送信できる（メールが届く）",
      "- [ ] 確認: 管理画面にログインでき、投稿の編集・保存ができる" if w else "- [ ] 確認: 管理画面・ログインがあれば操作できる",
      "- [ ] 確認: PHP のエラーログに Fatal / Warning / Deprecated が出ていない"]
L += [f"- [ ] 確認: {t}" for t in extra]
L += ["- [ ] お客様に検証環境を見てもらう（いつもの運用どおり）", "",
      "## 2. 本番", "",
      "- [ ] 1. と同じ更新・アップロードを本番で行う",
      f"- [ ] 本番の PHP を **{s['target']}** に切り替える",
      "- [ ] 1. と同じ確認を本番で行う",
      "- [ ] 棚卸し表の「PHP Ver.」を更新し、`一覧表用.tsv` の1行を貼る", "",
      "## 3. 問題が出たときの戻し方", "",
      f"- [ ] PHP を元の版（{s['current']}）に戻す（まずこれで止血）"]
if up or dele:
    L.append("- [ ] `元ファイル/` の中身を同じ場所へアップロードし直す（修正前に戻る）")
    if added:
        L.append("- [ ] 新しく追加したファイルを削除: " + ", ".join(f"`{x}`" for x in added))
L += ["- [ ] それでも戻らなければ、0. のバックアップから復元", ""]
(OUT / "作業票.md").write_text("\n".join(L), encoding="utf-8")

print(f"修正したファイル: {len(up)} 件" + (f" ／ 削除: {len(dele)} 件" if dele else ""))
for p in up[:20]:
    print(f"  {p}")
print(f"作業票: {OUT / '作業票.md'}")
print(f"アップロード用: {upd}/ ／ 元ファイル: {orig}/（どちらも本物の値に戻してある）")
print(f"差分: {OUT / '修正差分.patch'} ／ 一覧: {OUT / 'アップロード一覧.txt'}")
