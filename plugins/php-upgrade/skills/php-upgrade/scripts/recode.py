"""UTF-8 以外のファイルを安全に直すための変換（run.sh recode open|close <ファイル>...）。

  open   元の文字コード（Shift_JIS / EUC-JP）を記録して、UTF-8 に変換する。改行コードは保つ
  close  記録しておいた元の文字コードに戻す。戻せない文字があれば止まる（ファイルは UTF-8 のまま）
  status 変換中のファイルの一覧

open → 修正 → close の順に使う。close を忘れると、サーバーに上げたとき画面が文字化けする。
"""
import argparse
from pathlib import Path

from common import OUT, die, ensure_out, load_json, save_json

ENC = {"shift_jis": "cp932", "euc-jp": "euc_jp"}
STATE = OUT / "recode.json"

ap = argparse.ArgumentParser()
ap.add_argument("action", choices=["open", "close", "status"])
ap.add_argument("files", nargs="*")
a = ap.parse_args()

ensure_out()
state = load_json(STATE, {})


def detect(b):
    try:
        b.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    for name, codec in ENC.items():
        try:
            b.decode(codec)
            return name
        except UnicodeDecodeError:
            continue
    return None


if a.action == "status":
    if not state:
        print("変換中のファイルはありません。")
    for f, e in state.items():
        print(f"  {f}（元: {e}）")
    raise SystemExit(0)

if not a.files:
    die("ファイルを指定してください。")

for f in a.files:
    p = Path(f)
    key = p.as_posix()
    if not p.is_file():
        die(f"ファイルがありません: {f}")
    b = p.read_bytes()
    if a.action == "open":
        if key in state:
            print(f"  {key}: すでに UTF-8 に変換済み（元: {state[key]}）")
            continue
        e = detect(b)
        if e == "utf-8":
            print(f"  {key}: もともと UTF-8。変換不要")
            continue
        if e is None:
            die(f"{key}: 文字コードを判別できません。手で確認してください。")
        text = b.decode(ENC[e])
        if text.encode(ENC[e]) != b:
            die(f"{key}: 変換して戻すと内容が変わるため中止しました（{e} として正しく読めない文字がある）。")
        p.write_bytes(text.encode("utf-8"))
        state[key] = e
        print(f"  {key}: {e} → UTF-8（修正後に run.sh recode close {key}）")
    else:
        if key not in state:
            print(f"  {key}: 変換していないファイルです。そのまま")
            continue
        e = state[key]
        try:
            out = b.decode("utf-8").encode(ENC[e])
        except UnicodeEncodeError as ex:
            die(f"{key}: {e} で表せない文字があります（{ex.object[ex.start:ex.end]!r}）。その文字を直してから、もう一度 close してください。")
        p.write_bytes(out)
        del state[key]
        print(f"  {key}: UTF-8 → {e} に戻しました")
save_json(STATE, state)
