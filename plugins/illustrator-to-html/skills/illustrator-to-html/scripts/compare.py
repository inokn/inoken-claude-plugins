#!/usr/bin/env python3
"""カンプ(.aiのspec.json)と実装HTMLの実測値を突き合わせ、ズレを一覧にする。

  python3 compare.py <comp.spec.json> <html.json> [--threshold 4]

comp.spec.json : ai2spec.sh が出力したカンプの仕様JSON
html.json      : web2spec.js が実装HTMLをレンダリングして出力した実測JSON

テキストの「行頭ベースライン座標」で照合する。同一文言が複数ある場合は
y が近いものどうしで対にする。

比較する座標はカンプ側の組み方に合わせて選ぶ（ここを揃えないと、
実装は正しいのに数十〜数百pxのズレが出て、本物の外れ値が埋もれる）:

  横組み・左揃え      Δy=ベースライン        Δx=ベースラインx
  横組み・中央/右揃え  Δy=ベースライン        Δx=箱の左端    ※baseline.x はアンカー位置なので使えない
  縦組み             Δy=箱の上端            Δx=1列目の中心  ※縦組みにベースラインの概念が無い。
                                                    1列目は箱の右端側にあるので箱の左端では合わない
"""
import json
import re
import sys
import statistics

# Windows で .sh を通さず直接実行しても、日本語や © を cp932 で出そうとして落ちないように
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

def norm(t):
    return re.sub(r"\s+", "", t or "")

def walk(it):
    yield it
    for c in it.get("children", []):
        yield from walk(c)

def load_comp(path):
    """カンプ側: {正規化テキスト: [(y, x, mode), ...]}"""
    d = json.load(open(path, encoding="utf-8"))
    out = {}
    for layer in d.get("layers", []):
        for top in layer.get("items", []):
            for it in walk(top):
                if it.get("type") != "TextFrame":
                    continue
                # エリアテキストは箱の上端しか無くベースラインが取れないので比較対象外
                if it.get("kind") == "AREATEXT":
                    continue
                t = norm(it.get("text"))
                if not t or t.startswith("[画像]"):
                    continue
                b = it.get("baseline")
                box = it.get("box") or {}
                if not b:
                    continue
                if it.get("orientation") == "VERTICAL":
                    # 縦組みの baseline は「1列目の中心x / 文字列先頭のy」を指す
                    out.setdefault(t, []).append((box.get("y"), b["x"], "縦組み"))
                    continue
                align = ((it.get("runs") or [{}])[0].get("align") or "LEFT").upper()
                if align in ("CENTER", "RIGHT"):
                    out.setdefault(t, []).append((b["y"], box.get("x"), align.lower()))
                else:
                    out.setdefault(t, []).append((b["y"], b["x"], ""))
    return out, d

def load_html(path):
    """実装側: {正規化テキスト: [(baseline, x, top), ...]}"""
    d = json.load(open(path, encoding="utf-8"))
    out = {}
    for n in d.get("nodes", []):
        if n.get("kind") != "text":
            continue
        cls = n.get("cls") or ""
        # スクリーンリーダー専用テキストはカンプに存在しない
        if "visually-hidden" in cls or "sr-only" in cls or "screen-reader" in cls:
            continue
        t = norm(n.get("text"))
        if not t:
            continue
        line = n["lines"][0]
        out.setdefault(t, []).append((line["baseline"], line["x"], line["y"], n.get("fontSize") or 0))
    return out, d

def pair(cs, hs):
    """y が近いものどうしで対にする。数が食い違っても（カンプ側の重複配置など）壊れない。"""
    used, res = set(), []
    for c in sorted(cs):
        cy, cx, mode = c
        best, bd = None, None
        for i, h in enumerate(hs):
            if i in used:
                continue
            hy = h[2] if mode == "縦組み" else h[0]
            dist = abs(hy - cy)
            if bd is None or dist < bd:
                best, bd = i, dist
        if best is None or bd > 500:
            continue
        used.add(best)
        res.append((c, hs[best]))
    return res

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        print(__doc__)
        return 2
    thr = 4.0
    if "--threshold" in sys.argv:
        thr = float(sys.argv[sys.argv.index("--threshold") + 1])

    C, compdoc = load_comp(args[0])
    H, htmldoc = load_html(args[1])

    rows, unmatched = [], []
    for t, cs in C.items():
        if t not in H:
            unmatched.append(t)
            continue
        for (cy, cx, mode), (hb, hx, ht, hfs) in pair(cs, list(H[t])):
            if mode == "縦組み":
                # Chrome は縦組みの矩形を列ごとに返す。lines[0] は1列目（右端）の箱。
                hy, hx = ht, hx + hfs / 2.0
            else:
                hy = hb
            rows.append((cy, t, hy - cy, hx - cx, mode))

    if not rows:
        print("照合できたテキストがありません。文言が一致しているか確認してください。")
        return 1

    ab = compdoc.get("artboards", [{}])[0]
    dy = [r[2] for r in rows]
    dx = [r[3] for r in rows]
    bad = sorted([r for r in rows if abs(r[2]) > thr or abs(r[3]) > thr])

    print("照合 %d 件 / しきい値%gpx超 %d 件 / 未照合 %d 件"
          % (len(rows), thr, len(bad), len(unmatched)))
    print("Δy 中央 %+.1f 最大 %+.1f   |   Δx 中央 %+.1f 最大 %+.1f"
          % (statistics.median(dy), max(dy, key=abs),
             statistics.median(dx), max(dx, key=abs)))
    print("総高さ %s (カンプ %s) / 幅 %s (カンプ %s)"
          % (htmldoc.get("pageHeight"), ab.get("h"),
             htmldoc.get("pageWidth"), ab.get("w")))

    if bad:
        print("\n-- ズレの大きい順（カンプy昇順） --")
        for cy, t, ddy, ddx, mode in bad:
            print("  y=%-8.1f Δy=%+6.1f Δx=%+6.1f  %-30s %s" % (cy, ddy, ddx, t[:30], mode))

    if unmatched:
        print("\n-- カンプにあるがHTMLで見つからない文言 --")
        for t in unmatched[:15]:
            print("  %s" % t[:50])
        if len(unmatched) > 15:
            print("  ... 他 %d 件" % (len(unmatched) - 15))
        print("  ※カンプ側で1行ずつ別テキストに分かれている場合は正常（HTMLでは1要素に結合されるため）")

    print("\n※Δxはカンプの揃え方向に合わせて基準を変えている（縦組み・中央/右揃えは箱の左端どうし）。")
    print("※横位置が「何を基準に」決まっているかは Δ では分からない。anchors.py の判定を必ず見ること。")
    return 0

if __name__ == "__main__":
    sys.exit(main())
