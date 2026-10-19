#!/usr/bin/env python3
"""カンプの画像をHTML用に取り出す。

  python3 assets.py <spec.json> -o <outdir> [--extracted <pdfimagesの出力dir>]

方針は2段構え:
  ① .ai は埋め込んだ画像の **元ファイルのパスを覚えている**。それが手元にあれば
     そのまま使う。元の形式・元のバイトなので劣化ゼロで、JPEGはJPEGのまま軽い。
  ② 元ファイルが無ければ .ai から抽出したものを使う（--extracted）。
     PNGは完全一致、JPEG由来は可逆で取り出せるが PNG になるので要再エンコード。
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys

# Windows で .sh を通さず直接実行しても、日本語や © を cp932 で出そうとして落ちないように
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


def slug(s):
    s = re.sub(r"^img/", "", s or "")
    s = re.sub(r"[^\w぀-ヿ一-鿿-]+", "-", s).strip("-")
    return s or "image"


def collect(spec):
    """画像グループを拾う。(表示名, 元パス, 箱) の並びを返す。"""
    out = []

    def walk(items, name=None):
        for it in items:
            n = it.get("name") or name
            if it.get("type") in ("Raster", "Placed") and it.get("file"):
                out.append({"name": n or "image", "src": it["file"],
                            "box": it.get("box")})
            walk(it.get("children", []), n)

    for layer in spec.get("layers", []):
        walk(layer.get("items", []))
    return out


def main():
    ap = argparse.ArgumentParser(description="カンプの画像をHTML用に取り出す")
    ap.add_argument("spec")
    ap.add_argument("-o", "--out", default="assets")
    ap.add_argument("--extracted", help="pdfimages -all の出力ディレクトリ")
    args = ap.parse_args()

    with open(args.spec, encoding="utf-8") as f:
        spec = json.load(f)

    imgs = collect(spec)
    if not imgs:
        print("この .ai に埋め込み画像はありません（プレースホルダのみ）")
        return 0

    os.makedirs(args.out, exist_ok=True)
    pool = []
    if args.extracted and os.path.isdir(args.extracted):
        for f in sorted(os.listdir(args.extracted)):
            p = os.path.join(args.extracted, f)
            if os.path.isfile(p):
                pool.append(p)

    manifest, seen, missing = [], {}, []
    for im in imgs:
        src = im["src"]
        base = os.path.basename(src)
        if os.path.isfile(src):
            key = hashlib.sha1(open(src, "rb").read()).hexdigest()[:12]
            if key in seen:                      # 同じ画像を複数箇所で使っている
                dst = seen[key]
            else:
                dst = os.path.join(args.out, base)
                shutil.copy2(src, dst)
                seen[key] = dst
            state = "元ファイル"
        else:
            dst, state = None, "元ファイルが無い"
            missing.append(base)
        manifest.append({"name": im["name"], "source": src,
                         "file": os.path.basename(dst) if dst else None,
                         "state": state, "box": im["box"]})

    with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"images": manifest,
                   "extracted": [os.path.basename(p) for p in pool]},
                  f, ensure_ascii=False, indent=1)

    ok = sum(1 for m in manifest if m["file"])
    print("画像 %d 箇所 / %d 件を %s に取り出しました" % (len(manifest), ok, args.out))
    for m in manifest:
        b = m["box"] or {}
        print("  %-22s %-12s %s"
              % (m["name"][:22], m["state"],
                 m["file"] or "→ 抽出物から選ぶ (%.0fx%.0fpt)" % (b.get("w", 0), b.get("h", 0))))

    if missing:
        print("\n元ファイルが見つからないもの: %s" % ", ".join(sorted(set(missing))))
        if pool:
            print(".ai から抽出したものが %d 件あります（%s）。"
                  "箱の寸法と見比べて手で割り当ててください:" % (len(pool), args.extracted))
            for p in pool:
                print("    %s" % os.path.basename(p))
        else:
            print("次で .ai から取り出せます:")
            print("    cp design.ai design.pdf && pdfimages -all design.pdf 出力先/img")
            print("    python3 assets.py spec.json -o assets --extracted 出力先")
    return 0


if __name__ == "__main__":
    sys.exit(main())
