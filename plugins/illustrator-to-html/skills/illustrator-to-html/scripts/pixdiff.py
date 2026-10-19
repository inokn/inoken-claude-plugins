#!/usr/bin/env python3
"""カンプPNGと実装のレンダリングを画素で突き合わせ、テキスト以外のズレを出す。

  python3 pixdiff.py <comp.spec.json> <impl.png> [--html-json <check.json>]
                     [--threshold 28] [--top 12] [--out <overlay.png>]

compare.py はテキストのベースラインしか見ない。罫線・斜線・矢印・図形・写真の
トリミングは Δy/Δx にまったく現れないため、そこは画素で見るしかない。

出るもの:
  残差   … 実装を ±2px ずらして最も一致したときに残る差分画素数。**これで並べる**
           1px の置きズレや丸めは 0 付近に落ちるので、形そのものが違うものだけ残る
  差分   … ずらさずに数えた差分画素数（参考）
  overlay.png … 赤=カンプにしか無いインク / 青=実装にしか無いインク
           斜線の向き違い（/ と \\）は赤と青が交差して見えるので一目で分かる

テキストの箱は両側から白で塗り潰してから比べる（そこは compare.py の担当。
残すとアンチエイリアスの差でノイズに埋もれる）。
"""
import argparse
import json
import os
import sys
from collections import deque

# Windows で .sh を通さず直接実行しても、日本語や © を cp932 で出そうとして落ちないように
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

try:
    from PIL import Image, ImageChops
except ImportError:
    print("Pillow が必要です: python3 -m pip install --user Pillow（Windows: py -3 -m pip install --user Pillow）", file=sys.stderr)
    sys.exit(2)

CELL = 4          # 画素をこの正方形にまとめてからクラスタリングする
PAD = 2.0         # テキスト箱を膨らませる量（アンチエイリアスのはみ出し分）
SHIFT = 2         # 残差を測るときにずらす範囲（±px）


def walk(items):
    for it in items:
        yield it
        for k in ("items", "children"):
            v = it.get(k)
            if isinstance(v, list):
                for c in walk(v):
                    yield c


def comp_boxes(spec, types):
    out = []
    items = [i for L in spec.get("layers", []) for i in L.get("items", [])]
    for it in walk(items):
        if it.get("type") not in types:
            continue
        b = it.get("visibleBox") or it.get("box")
        if b:
            out.append((b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]))
    return out


def flatten(png):
    """カンプPNGは背景が透明なので白に合成する。"""
    im = Image.open(png)
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im)
    return im.convert("RGB")


def to_artboard(im, w, h):
    """アートボード座標(1x)へ。整数倍なら縮小、寸法が違えば重なる範囲だけ使う。"""
    if im.size == (w, h):
        return im, None
    if w and im.width % w == 0 and im.width // w > 1:
        k = im.width // w
        im = im.resize((im.width // k, im.height // k), Image.LANCZOS)
    note = None
    if im.size != (w, h):
        note = "レンダリングは %dx%d。アートボード %dx%d と重なる範囲だけ比較した" % (
            im.width, im.height, w, h)
        canvas = Image.new("RGB", (w, h), (255, 255, 255))
        canvas.paste(im.crop((0, 0, min(w, im.width), min(h, im.height))), (0, 0))
        im = canvas
    return im, note


def whiten(im, boxes, w, h):
    """boxes の内側を白で塗る（比較対象から外す）。"""
    white = Image.new(im.mode, (1, 1), 255 if im.mode == "L" else (255, 255, 255))
    for (x0, y0, x1, y1) in boxes:
        a = (max(0, int(x0 - PAD)), max(0, int(y0 - PAD)),
             min(w, int(x1 + PAD) + 1), min(h, int(y1 + PAD) + 1))
        if a[2] > a[0] and a[3] > a[1]:
            im.paste(white.resize((a[2] - a[0], a[3] - a[1])), a)


def binarize(a, b, thr):
    """a より b が暗い画素を 255 にする。"""
    return ImageChops.subtract(a, b).point(lambda v: 255 if v > thr else 0)


def clusters(mask, w, h, cell_min, min_px):
    """マスクを CELL 角のセルに落としてから隣接セルを繋ぐ。"""
    gw, gh = max(1, w // CELL), max(1, h // CELL)
    d = list(mask.resize((gw, gh), Image.BOX).getdata())   # セル内の平均 = 密度
    keepset = set(i for i, v in enumerate(d) if v >= cell_min)
    seen, out = set(), []
    for start in keepset:
        if start in seen:
            continue
        q = deque([start])
        seen.add(start)
        members = []
        while q:
            i = q.popleft()
            members.append(i)
            cx, cy = i % gw, i // gw
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < gw and 0 <= ny < gh:
                        j = ny * gw + nx
                        if j in keepset and j not in seen:
                            seen.add(j)
                            q.append(j)
        px = sum(d[i] for i in members) / 255.0 * (CELL * CELL)
        if px < min_px:
            continue
        xs = [i % gw for i in members]
        ys = [i // gw for i in members]
        out.append({"x": min(xs) * CELL, "y": min(ys) * CELL,
                    "w": (max(xs) - min(xs) + 1) * CELL,
                    "h": (max(ys) - min(ys) + 1) * CELL, "px": round(px)})
    return out


def residual(cl_pad, il_pad, c, thr, w, h):
    """実装を ±SHIFT ずらして最も一致したときに残る差分画素数。"""
    m = SHIFT + 1
    x0, y0 = max(0, c["x"] - m), max(0, c["y"] - m)
    x1, y1 = min(w, c["x"] + c["w"] + m), min(h, c["y"] + c["h"] + m)
    a = cl_pad.crop((x0 + SHIFT, y0 + SHIFT, x1 + SHIFT, y1 + SHIFT))
    best = None
    for dy in range(-SHIFT, SHIFT + 1):
        for dx in range(-SHIFT, SHIFT + 1):
            b = il_pad.crop((x0 + SHIFT + dx, y0 + SHIFT + dy,
                             x1 + SHIFT + dx, y1 + SHIFT + dy))
            d = ImageChops.difference(a, b).point(lambda v: 255 if v > thr else 0)
            n = d.histogram()[255]
            if best is None or n < best:
                best = n
                if best == 0:
                    return 0
    return best


def tag_of(c, rasters, paths):
    if any(_hit(c, b) for b in rasters):
        return "写真"
    if any(_hit(c, b) for b in paths):
        return "図形"
    return "?"


def _hit(c, b):
    return c["x"] < b[2] and c["x"] + c["w"] > b[0] and c["y"] < b[3] and c["y"] + c["h"] > b[1]


def main():
    ap = argparse.ArgumentParser(description="カンプと実装を画素で突き合わせる")
    ap.add_argument("spec")
    ap.add_argument("impl_png")
    ap.add_argument("--comp-png", help="既定は spec.json の隣の <name>_ab1@2x.png")
    ap.add_argument("--html-json", help="web2spec.js の出力。実装側のテキスト箱も除外する")
    ap.add_argument("--threshold", type=int, default=28,
                    help="画素差のしきい値。#ddd のヘアラインは白との差が34しかない")
    ap.add_argument("--cell-min", type=int, default=40)
    ap.add_argument("--min-px", type=int, default=14)
    ap.add_argument("--min-resid", type=int, default=12,
                    help="この残差未満は「置きズレ」として落とす")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--out", help="既定は impl_png の隣の <name>.pixdiff.png")
    args = ap.parse_args()

    spec = json.load(open(args.spec, encoding="utf-8"))
    ab = (spec.get("artboards") or [{}])[0]
    w, h = int(ab.get("w", 0)), int(ab.get("h", 0))
    if not w or not h:
        print("アートボード寸法が spec.json から読めません", file=sys.stderr)
        return 2

    comp_png = args.comp_png
    if not comp_png:
        base = os.path.splitext(args.spec)[0]
        if base.endswith(".spec"):
            base = base[:-5]
        for suffix in ("_ab1@2x.png", "_ab1.png"):
            if os.path.exists(base + suffix):
                comp_png = base + suffix
                break
    if not comp_png or not os.path.exists(comp_png):
        print("カンプPNGが見つかりません（--comp-png で指定してください）", file=sys.stderr)
        return 2

    comp, n1 = to_artboard(flatten(comp_png), w, h)
    impl, n2 = to_artboard(flatten(args.impl_png), w, h)

    # テキストは compare.py の担当。両側から消す。
    text = comp_boxes(spec, ("TextFrame",))
    if args.html_json:
        try:
            hj = json.load(open(args.html_json, encoding="utf-8"))
            for n in hj.get("nodes", []):
                if n.get("kind") == "text":
                    for ln in n.get("lines", []):
                        text.append((ln["x"], ln["y"], ln["x"] + ln["w"], ln["y"] + ln["h"]))
        except Exception:
            pass
    cl, il = comp.convert("L"), impl.convert("L")
    whiten(cl, text, w, h)
    whiten(il, text, w, h)

    only_comp = binarize(il, cl, args.threshold)   # カンプ側にだけインク
    only_impl = binarize(cl, il, args.threshold)   # 実装側にだけインク
    cs = clusters(ImageChops.lighter(only_comp, only_impl), w, h,
                  args.cell_min, args.min_px)

    cl_pad = Image.new("L", (w + SHIFT * 2, h + SHIFT * 2), 255); cl_pad.paste(cl, (SHIFT, SHIFT))
    il_pad = Image.new("L", (w + SHIFT * 2, h + SHIFT * 2), 255); il_pad.paste(il, (SHIFT, SHIFT))
    for c in cs:
        c["resid"] = residual(cl_pad, il_pad, c, args.threshold, w, h)

    rasters = comp_boxes(spec, ("Raster", "Placed"))
    paths = comp_boxes(spec, ("Path", "CompoundPath"))
    real = [c for c in cs if c["resid"] >= args.min_resid]
    real.sort(key=lambda c: -c["resid"])

    print("画素照合（テキスト除外 / しきい値 %d）: クラスタ %d 件 / 残差%dpx以上 %d 件"
          % (args.threshold, len(cs), args.min_resid, len(real)))
    if real:
        print("\n-- 残差の大きい順（±%dpx ずらしても消えない差） --" % SHIFT)
        for c in real[:args.top]:
            print("  y=%-7d x=%-7d %3dx%-3d  残差%5d px (差分%5d)  %s"
                  % (c["y"], c["x"], c["w"], c["h"], c["resid"], c["px"],
                     tag_of(c, rasters, paths)))
        if len(real) > args.top:
            print("  ... 他 %d 件" % (len(real) - args.top))
        print("\n  ※ overlay を等倍以上で見て、赤（カンプのみ）と青（実装のみ）の"
              "位置関係から原因を判断する。")
        print("  ※ 交差していれば向き違い、平行にずれていれば位置、"
              "片側だけなら要素の欠落・余分。")
    else:
        print("  テキスト以外に、置きズレを超える差はありません。")
    for n in (n1, n2):
        if n:
            print("\n  ※ " + n)

    out = args.out or (os.path.splitext(args.impl_png)[0] + ".pixdiff.png")
    base = Image.blend(comp, Image.new("RGB", (w, h), (255, 255, 255)), 0.8)
    base.paste(Image.new("RGB", (w, h), (206, 20, 20)), (0, 0), only_comp)
    base.paste(Image.new("RGB", (w, h), (20, 68, 214)), (0, 0), only_impl)
    base.save(out)
    print("\n  overlay: %s  （赤=カンプのみ / 青=実装のみ）" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
