#!/usr/bin/env python3
"""カンプの仕様JSONに「何に対して揃っているか」の手がかりを足す。

  python3 alignment.py <spec.json> [--tol 3] [--stdout]

カンプ幅でしかレンダリングしないと、右端基準・中央基準・左端基準の実装は
どれも同じ座標になり、Δxでは区別がつかない。ズレていないのに設計が違う、
という事故を防ぐため、**カンプ側の座標から先にアンカーを確定させる**ための材料を出す。

spec.json に次を追記する（既にあれば作り直す）:

  "alignment": {
    "artboardCenter": 650,
    "pageCentered": [...],   # 中心がアートボード中心と一致する要素 = ページ中央揃え確定
    "leftEdges":    [...],   # 頻出する左端 = 本文カラムの左
    "rightEdges":   [...]    # 頻出する右端 = 本文カラムの右
  }
"""
import json
import sys
from collections import Counter

# Windows で .sh を通さず直接実行しても、日本語や © を cp932 で出そうとして落ちないように
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


def walk(it):
    yield it
    for c in it.get("children", []):
        yield from walk(c)


def label(it):
    t = (it.get("text") or "").strip().replace("\n", " ")
    if t:
        return t[:28]
    return "%s %s" % (it.get("type"), it.get("shape") or "")


def analyze(doc, tol=3.0, min_w=40.0, edge_min_w=120.0):
    ab = (doc.get("artboards") or [{}])[0]
    W = ab.get("w") or 0
    if not W:
        return None
    center = round(W / 2.0, 2)

    items = [i for L in doc.get("layers", []) for top in L.get("items", []) for i in walk(top)]

    centered, lefts, rights = [], Counter(), Counter()
    seen = set()
    for it in items:
        b = it.get("box") or {}
        w = b.get("w") or 0
        x = b.get("x")
        y = b.get("y")
        if x is None or w < min_w:
            continue
        # クリップ矩形とその中のラスタはほぼ同じ箱なので、片方だけ数える
        key = (round(x), round(y or 0), round(w))
        if key in seen:
            continue
        seen.add(key)
        c = x + w / 2.0
        # 全幅の帯は「中央揃え」ではなく「全幅」。手がかりにならないので除く
        if w <= W - 20 and abs(c - center) <= tol:
            centered.append({
                "id": it.get("id"), "type": it.get("type"), "y": b.get("y"),
                "x": round(x, 2), "w": round(w, 2),
                "center": round(c, 2), "delta": round(c - center, 2),
                "label": label(it),
            })
        if w >= edge_min_w and w <= W - 20:        # 全幅の帯は本文カラムの手がかりにならない
            lefts[round(x)] += 1
            rights[round(x + w)] += 1

    centered.sort(key=lambda r: r["y"] if r["y"] is not None else 0)
    top = lambda c: [{"x": k, "count": n} for k, n in c.most_common(6) if n >= 2]
    return {
        "artboardCenter": center,
        "tolerance": tol,
        "pageCentered": centered,
        "leftEdges": top(lefts),
        "rightEdges": top(rights),
    }


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    tol = 3.0
    if "--tol" in sys.argv:
        tol = float(sys.argv[sys.argv.index("--tol") + 1])
    path = args[0]
    doc = json.load(open(path, encoding="utf-8"))
    a = analyze(doc, tol=tol)
    if a is None:
        print("アートボード情報が無いため判定できません", file=sys.stderr)
        return 1

    if "--stdout" not in sys.argv:
        doc["alignment"] = a
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)

    print("アートボード中心 %s" % a["artboardCenter"])
    if a["pageCentered"]:
        print("ページ中央揃え（中心が±%gpx以内）: %d件 — この要素は必ず中央アンカーで実装する"
              % (tol, len(a["pageCentered"])))
        for r in a["pageCentered"][:20]:
            print("  y=%-8s x=%-8s w=%-7s 中心%-8s (%+.2f)  %s"
                  % (r["y"], r["x"], r["w"], r["center"], r["delta"], r["label"]))
        if len(a["pageCentered"]) > 20:
            print("  ... 他 %d 件" % (len(a["pageCentered"]) - 20))
    else:
        print("ページ中央揃えの要素は見つかりませんでした")
    if a["leftEdges"]:
        print("頻出する左端: " + ", ".join("%s(%d)" % (e["x"], e["count"]) for e in a["leftEdges"]))
    if a["rightEdges"]:
        print("頻出する右端: " + ", ".join("%s(%d)" % (e["x"], e["count"]) for e in a["rightEdges"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
