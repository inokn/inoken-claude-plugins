# illustrator-to-html

Illustratorのカンプ（`.ai`）から実測値を取り出し、それを仕様書としてHTML/CSSを実装し、
**レンダリングして数値で照合する**ところまでを行う Claude Code スキル。

目分量で作って終わりにしないのが要点で、テキストの行頭ベースライン座標を
カンプと実装で突き合わせ、Δy/Δxが収束するまで直す。

## 導入

macOS と Windows に対応。

組織に配布された場合（inoken.ai のプラグインとして入っている場合）は、フォルダを置く作業は不要。
下の「依存パッケージを入れて、環境チェックを通す」から始める（Claude Code に「illustrator-to-html の環境チェックをして」と頼めばよい）。

手で入れる場合は、このフォルダごと、以下のどちらかに置く。

```bash
# 個人用（どのプロジェクトからも使える）
cp -R illustrator-to-html ~/.claude/skills/        # Windows なら C:\Users\<ユーザー名>\.claude\skills\

# プロジェクト用（そのリポジトリでのみ使える）
cp -R illustrator-to-html <repo>/.claude/skills/
```

依存パッケージを入れて、環境チェックを通す（Windows では Claude Code の Bash＝Git Bash で実行する）。

```bash
cd <このスキルのフォルダ>/scripts
npm install          # puppeteer-core のみ。ブラウザ本体は既存の Chrome / Edge を使う（約50MB）
./preflight.sh
```

`node_modules` はスキルのフォルダの中に入る。プラグインとして入れている場合、**プラグインが更新されると
新しい版のフォルダには `node_modules` が無い**ので、`npm install` をやり直す（`preflight.sh` が ✗ で教えてくれる）。

`preflight.sh` が全部 ✓ になれば準備完了。Claude Code に
「このカンプをHTMLにして」「イラレのデザインをコーディングして」等と頼むと起動する。

### Windows で足りないものを入れる

PowerShell で（入れたあとは Claude Code を再起動する）:

```powershell
winget install OpenJS.NodeJS.LTS
winget install Python.Python.3.12
```

`python3` と打つと Microsoft Store が開くことがあるが、それはスタブなので無視してよい。
スクリプトは `py -3` を自動で使う。

## 必要な環境

| | 用途 | 無いとどうなるか |
|---|---|---|
| macOS または Windows | Illustratorの操作（Mac: `osascript` / Windows: PowerShell + COM） | フェーズ1が動かない |
| Adobe Illustrator | `.ai` の読み取り（Mac 2022 / Windows 2026 で確認） | 同上 |
| Google Chrome または Microsoft Edge | 実装HTMLの実測 | フェーズ4の検証ができない |
| node / npm | `web2spec.js` の実行 | 同上 |
| Python 3.8+ | `compare.py` ほかの実行 | 同上 |
| Pillow（任意） | `pixdiff.py` の画素照合 | 画素照合だけ使えない |

ブラウザが標準の場所に無い場合は `CHROME_PATH` に実行ファイルのパスを入れる。
Windows で Illustrator が複数バージョン入っている場合は `AI_PROGID`（例: `Illustrator.Application.30`）で指定する。

### Windows での注意

- Illustrator が起動していなければ自動で起動する。ログインや更新案内のダイアログが出ていると失敗するので、
  先に Illustrator を手で起動してダイアログを閉じておくと確実
- Claude Code はデスクトップにログインした状態で使う（リモートのサービスなど画面の無いセッションからは Illustrator を起動できない）

`.ai` が無くPNGのカンプしか無い場合、フェーズ1と4は使えない。
その場合は数値照合ができないので、精度は目測相当に落ちる。

## 和文フォントについて

`references/pitfalls.md` の「PostScript名 → CSSフォントスタック」対応表は、
Mac（游ゴシック・游明朝・ヒラギノ）と Windows（游ゴシック・游明朝・メイリオ・BIZ UD）の両方を載せている。
Windows の游ゴシックは Regular が細いので、Medium を `"Yu Gothic Medium"` で指定するのを忘れない。

カンプのフォントが正しくCSSに落ちているかは `compare.py` のΔxで判別できる
（フォントが一致していれば字形の実寸も完全に一致する）。

## 単体で使う

スキルを介さず直接叩いてもいい。

```bash
SK=~/.claude/skills/illustrator-to-html

# カンプを読む → design_spec/design.spec.json と PNG
"$SK/scripts/ai2spec.sh" design.ai -o ./spec

# 実装を照合する（--threshold 0.5 で小さなズレも一覧に出す）
"$SK/scripts/check.sh" index.html ./spec/design.spec.json 1440

# Python を直接呼ぶとき（Windows は python3 ではなく py -3）
py -3 "$SK/scripts/compare.py" ./spec/design.spec.json index.check.json --threshold 0.5
```

## 含まれないもの

逆方向（仕様JSON → `.ai`、URL → `.ai`）はこのスキルには入っていない。
