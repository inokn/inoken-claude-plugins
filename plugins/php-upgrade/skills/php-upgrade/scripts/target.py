"""移行先のPHPを決める（run.sh target <今のPHP版> [--target 8.3]）。

方針: 脆弱性の修正が入った版（references/targets.json）のうち、今の版から一番近いものへ上げる。
最低ラインは minimum_branch（8.2）。8.2 未満は 8.2 の修正版へ。
"""
import argparse

from common import OUT, branch, die, ensure_out, save_json, targets, vtuple

ap = argparse.ArgumentParser()
ap.add_argument("current", help="今のPHPのバージョン（例: 8.2.32 / 7.4）。棚卸し表の「PHP Ver.」の値")
ap.add_argument("--target", help="移行先のブランチを指定して上書きする（例: 8.3）")
a = ap.parse_args()

T = targets()
cur = vtuple(a.current)
if len(cur) < 2:
    die(f"バージョンが読めません: {a.current}（例: 8.2.32 / 7.4）")
cur_branch = f"{cur[0]}.{cur[1]}"
branches = sorted(T["targets"], key=vtuple)
minimum = T["minimum_branch"]

if a.target:
    tb = branch(a.target)
    if tb not in T["targets"]:
        die(f"移行先 {tb} は対象外です。選べるのは {', '.join(branches)}")
    if vtuple(tb) < vtuple(cur_branch):
        die(f"移行先 {tb} は今の版 {cur_branch} より古いので選べません")
else:
    want = max(vtuple(cur_branch), vtuple(minimum))
    cand = [b for b in branches if vtuple(b) >= want]
    if not cand:
        die(f"今の版 {a.current} より新しい修正版が targets.json にありません。targets.json を更新してください")
    tb = cand[0]

tv = T["targets"][tb]
if cur_branch == tb:
    mode = "none" if cur >= vtuple(tv) else "patch"
else:
    mode = "branch"

res = {
    "current": a.current.strip(),
    "current_branch": cur_branch,
    "target": a.current.strip() if mode == "none" else tv,
    "target_branch": tb,
    "mode": mode,
    "overridden": bool(a.target),
    "security_support_until": T["security_support_until"].get(tb),
    "wordpress_min": T["wordpress_min_for_php"].get(tb),
    "reason": T["reason"],
    "targets_updated": T["updated"],
}
ensure_out()
save_json(OUT / "target.json", res)

label = {
    "none": "すでに修正版です（作業不要）",
    "patch": "同じ系列内のパッチ更新です（互換性の点検は不要）",
    "branch": f"{cur_branch} → {tb} へ系列をまたぐので、互換性を点検します",
}[mode]
print(f"今の版: {a.current} → 移行先: " + ("そのまま" if mode == "none" else tv))
print(label)
if tb == "8.2":
    print(f"⚠️ 8.2 のセキュリティ修正は {res['security_support_until']} で終わります。今回は応急処置として、次は 8.3 以上を計画してください。")
