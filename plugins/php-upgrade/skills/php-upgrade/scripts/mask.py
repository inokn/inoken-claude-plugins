"""パスワードらしき値を伏せる（run.sh mask …）。Claude が読む前に、手元だけで処理する。

  run.sh mask                    作業フォルダ全体を調べて伏せる（baseline が自動で呼ぶ）
  run.sh mask --add <file> <行>  人が「この行にもパスワードがある」と指定した行の文字列を伏せる
  run.sh mask --status           伏せたファイルの一覧（値は出さない）
  run.sh mask --restore          作業フォルダの印を本物の値に戻す（人が頼んだときだけ。戻したあとは Claude で開かない）

本物の値は作業フォルダの外（点検ツールの置き場所の secrets/）に保存する。画面には値を出さない。
取得時点の記録（git のタグ php-upgrade-baseline）は、伏せたあとの状態で残す（git diff から値が漏れないように）。
"""
import argparse
import subprocess
import sys
from pathlib import Path

from common import OUT, die, ensure_out
from secrets_lib import (PH_RE, candidate_files, find_values, load_store, mask_spans, save_state, save_store,
                         state, store_path, string_literals_on_line, unmask_bytes)

ap = argparse.ArgumentParser()
g = ap.add_mutually_exclusive_group()
g.add_argument("--add", nargs=2, metavar=("FILE", "LINE"))
g.add_argument("--status", action="store_true")
g.add_argument("--restore", action="store_true")
ap.add_argument("--no-commit", action="store_true", help="（baseline から呼ぶとき用）git に記録しない")
a = ap.parse_args()

ensure_out()
st = state()
store = load_store(st)
BASE = "php-upgrade-baseline"
G = ["git", "-c", "user.name=php-upgrade", "-c", "user.email=php-upgrade@localhost", "-c", "core.autocrlf=false"]


def git(*args):
    return subprocess.run(G + list(args), capture_output=True)


def record():
    """伏せた状態を、取得時点の記録に反映する（修正を始める前だけ）。"""
    if a.no_commit or not Path(".git").exists():
        return
    if git("rev-parse", "-q", "--verify", f"refs/tags/{BASE}").returncode != 0:
        return   # baseline がこのあとコミットする
    head = git("rev-parse", "HEAD").stdout.strip()
    base = git("rev-parse", f"{BASE}^{{commit}}").stdout.strip()
    if head != base:
        die("修正を始めたあとは、追加で伏せられません（git の差分に元の値が残るため）。\n"
            "修正をいったん git stash などで退避するか、作業フォルダを作り直してから伏せてください。")
    git("add", "-A")
    created = git("config", "--get", "php-upgrade.created").stdout.strip() == b"true"
    if created:
        # 自分で作った記録なら、取得時点のコミットそのものを伏せた状態に置き換え、古い中身も消す
        git("commit", "-q", "--amend", "--no-edit", "--allow-empty")
        git("tag", "-f", BASE)
        git("reflog", "expire", "--expire=now", "--all")
        git("gc", "-q", "--prune=now")
    else:
        git("commit", "-q", "-m", "認証情報を伏せた（php-upgrade）", "--allow-empty")
        git("tag", "-f", BASE)
        print("⚠️ もともとあった git の履歴には、伏せる前の値が残っています。git log -p などで過去の履歴を表示しないでください。")


if a.status:
    if not st["files"]:
        print("伏せたファイルはありません。")
    for f, ids in st["files"].items():
        print(f"  {f}: {len(ids)} 箇所")
    sys.exit(0)

if a.restore:
    n = 0
    for f in st["files"]:
        p = Path(f)
        if p.exists():
            data = p.read_bytes()
            if PH_RE.search(data):
                p.write_bytes(unmask_bytes(data, store, f))
                n += 1
    print(f"{n} ファイルを本物の値に戻しました。⚠️ 以後、これらのファイルを Claude で開かないでください。")
    sys.exit(0)

if a.add:
    f, line = a.add[0], int(a.add[1])
    p = Path(f)
    if not p.is_file():
        die(f"ファイルがありません: {f}")
    data = p.read_bytes()
    spans = string_literals_on_line(data, line)
    if not spans:
        die(f"{f} の {line} 行目に、伏せられる値が見つかりません（すでに伏せてあるか、値の形式が読めない）。")
    n = mask_spans(p, data, spans, st, store)
    save_store(st, store)
    save_state(st)
    record()
    print(f"{f} の {line} 行目の {n} 箇所を伏せました。")
    sys.exit(0)

total, files = 0, 0
for p in candidate_files():
    data = p.read_bytes()
    spans = find_values(data)
    if spans:
        total += mask_spans(p, data, spans, st, store)
        files += 1
save_store(st, store)
save_state(st)
record()
if total:
    print(f"🔒 パスワードらしき値を {files} ファイル・{total} 箇所伏せました（値は作業フォルダの外に保存）:")
    for f, ids in st["files"].items():
        print(f"    {f}: {len(ids)} 箇所")
else:
    print("🔒 伏せる値は見つかりませんでした。")
print(f"   保存先: {store_path(st).parent}（Claude で開かないこと）")
