#!/usr/bin/env python3
"""実装が「何を基準に横位置を決めているか」を、2つの幅で描いた実測値から判定する。

  python3 anchors.py <狭い幅.json> <広い幅.json> [comp.spec.json]

カンプ幅でしか描かないと、左端基準・中央基準・右端基準の実装はすべて同じ座標になり、
Δxはどれも0になる。区別がつくのは幅を変えたときだけ。

幅を D だけ広げたときの x の移動量から:
    移動 0      → 左アンカー
    移動 D/2    → 中央アンカー（ページ中央、または中央寄せした固定幅カラムの中）
    移動 D      → 右アンカー
    それ以外    → 流動（幅に応じて伸縮している）

comp.spec.json を渡すと、**カンプ側で中心がアートボード中心と一致している要素**が
実装で中央アンカーになっているかを照合し、食い違いを警告する。
"""
import json
import os
import re
import sys

# Windows で .sh を通さず直接実行しても、日本語や © を cp932 で出そうとして落ちないように
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

def norm(t):
    return re.sub(r"\s+", "", t or "")

def load_html(path):
    d = json.load(open(path, encoding="utf-8"))
    out = {}
    for n in d.get("nodes", []):
        if n.get("kind") != "text":
            continue
        if "visually-hidden" in (n.get("cls") or ""):
            continue
        t = norm(n.get("text"))
        if not t:
            continue
        ln = n["lines"][0]
        out.setdefault(t, []).append((ln["y"], ln["x"], n.get("cls") or ""))
    for v in out.values():
        v.sort()
    return d, out

def classify(ratio):
    if ratio < 0.15:
        return "左"
    if 0.35 <= ratio <= 0.65:
        return "中央"
    if ratio > 0.85:
        return "右"
    return "流動"

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        print(__doc__)
        return 2
    d1, H1 = load_html(args[0])
    d2, H2 = load_html(args[1])
    W1, W2 = d1.get("pageWidth"), d2.get("pageWidth")
    if not W1 or not W2 or W2 <= W1:
        print("2つ目のJSONは1つ目より広い幅で描いてください", file=sys.stderr)
        return 1
    D = W2 - W1

    rows = []
    for t, a in H1.items():
        b = H2.get(t)
        if not b:
            continue
        for (y1, x1, cls), (y2, x2, _c) in zip(a, b):
            rows.append((y1, t, cls, classify((x2 - x1) / D), round(x2 - x1, 1)))
    if not rows:
        print("照合できるテキストがありません")
        return 1
    rows.sort()

    # カンプ側で「ページ中央」と確定している要素
    comp_centered = {}
    if len(args) >= 3:
        comp = json.load(open(args[2], encoding="utf-8"))
        al = comp.get("alignment")
        if not al:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from alignment import analyze
            al = analyze(comp) or {}
        for r in al.get("pageCentered", []):
            if r.get("label"):
                comp_centered[norm(r["label"])[:20]] = r

    print("横アンカー判定（幅 %d → %d、移動量から分類）" % (W1, W2))
    order = ["左", "中央", "右", "流動"]
    for k in order:
        got = [r for r in rows if r[3] == k]
        if not got:
            continue
        ys = "y %.0f〜%.0f" % (got[0][0], got[-1][0])
        names = " / ".join(r[1][:14] for r in got[:4])
        more = " ほか%d件" % (len(got) - 4) if len(got) > 4 else ""
        mark = "   ← 意図した右基準か確認" if k == "右" else ""
        print("  %-4s %3d件  %-22s %s%s%s" % (k, len(got), ys, names, more, mark))

    warn = []
    for y, t, cls, kind, dx in rows:
        for lab, r in comp_centered.items():
            if t.startswith(lab[:12]) and kind != "中央":
                warn.append((y, t, kind, r))
                break
    if warn:
        print()
        print("!! カンプでページ中央揃えの要素が、実装では中央アンカーになっていない")
        for y, t, kind, r in warn:
            print("   y=%-8.1f 実装=%-4s  カンプ中心 %s (ずれ %+.2f)  %s"
                  % (y, kind, r["center"], r["delta"], t[:30]))
        print("   → 幅を変えると中央から外れる。アンカーを中央に直すこと。")
    elif comp_centered:
        print()
        print("カンプでページ中央揃えの %d 要素は、実装でも中央アンカー。" % len(comp_centered))
    return 0

if __name__ == "__main__":
    sys.exit(main())
