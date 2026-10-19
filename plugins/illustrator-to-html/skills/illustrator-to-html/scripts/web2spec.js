// 実ブラウザでレンダリングした結果から、要素ごとの座標・色・タイポグラフィを抜き出す。
//
//   node web2spec.js <URL / file:// / ローカルのHTMLパス> [幅] [出力.json]
//
// Chrome / Edge の場所は環境変数 CHROME_PATH で上書きできる。
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');
const puppeteer = require('puppeteer-core');

// ローカルパスは file:// URL にする（Windows の C:\… / C:/… もここで正しく変換される）
const ARG = process.argv[2];
const URL = ARG && !/^(https?|file):\/\//i.test(ARG) ? pathToFileURL(path.resolve(ARG)).href : ARG;
const WIDTH = parseInt(process.argv[3] || '1440', 10);
const OUT = process.argv[4] || 'dom.json';

if (!URL) {
  console.error('使い方: node web2spec.js <URL / file:// / HTMLのパス> [幅] [出力.json]');
  process.exit(2);
}

function findChrome() {
  const pf = process.env['PROGRAMFILES'] || 'C:\\Program Files';
  const pf86 = process.env['PROGRAMFILES(X86)'] || 'C:\\Program Files (x86)';
  const local = process.env['LOCALAPPDATA'] || '';
  const candidates = [
    process.env.CHROME_PATH,
    // Windows: Chrome → Edge（Edge は Windows に標準で入っている）
    path.join(pf, 'Google\\Chrome\\Application\\chrome.exe'),
    path.join(pf86, 'Google\\Chrome\\Application\\chrome.exe'),
    local && path.join(local, 'Google\\Chrome\\Application\\chrome.exe'),
    path.join(pf86, 'Microsoft\\Edge\\Application\\msedge.exe'),
    path.join(pf, 'Microsoft\\Edge\\Application\\msedge.exe'),
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
  ].filter(Boolean);
  for (const p of candidates) {
    if (fs.existsSync(p)) return p;
  }
  console.error('Chrome / Edge が見つかりません。CHROME_PATH に実行ファイルのパスを指定してください。');
  process.exit(1);
}

(async () => {
  const browser = await puppeteer.launch({
    executablePath: findChrome(),
    headless: 'new',
    args: ['--no-sandbox', '--font-render-hinting=none', '--hide-scrollbars'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: WIDTH, height: 1000, deviceScaleFactor: 2 });
  // networkidle0 は GA が居座って終わらないので domcontentloaded + 明示待ちにする
  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 90000 });
  await page.evaluate(() => document.fonts.ready).catch(() => {});
  // 遅延読み込みを起こすため一度最下部までスクロールしてから戻す
  await page.evaluate(async () => {
    const h = document.documentElement.scrollHeight;
    for (let y = 0; y < h; y += 600) { window.scrollTo(0, y); await new Promise(r => setTimeout(r, 60)); }
    window.scrollTo(0, 0);
  });
  await new Promise(r => setTimeout(r, 3000));

  const data = await page.evaluate(() => {
    const px = v => Math.round(parseFloat(v) * 100) / 100 || 0;
    const rgb = s => {
      if (!s) return null;
      const m = s.match(/rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)/);
      if (!m) return null;
      const a = m[4] === undefined ? 1 : parseFloat(m[4]);
      if (a === 0) return null;
      const h = n => Math.round(parseFloat(n)).toString(16).padStart(2, '0');
      return { hex: '#' + h(m[1]) + h(m[2]) + h(m[3]), alpha: a };
    };

    const out = [];
    const seenText = new Set();

    const walk = (el, depth) => {
      if (depth > 30) return;
      const cs = getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) return;
      const r = el.getBoundingClientRect();
      const top = r.top + window.scrollY;

      if (r.width > 0 && r.height > 0 && r.width < 4000) {
        const bg = rgb(cs.backgroundColor);
        const bi = cs.backgroundImage && cs.backgroundImage !== 'none' ? cs.backgroundImage.slice(0, 120) : null;
        // 辺ごとに持つ。border-top だけ、のような指定を四方の枠線にしてしまわないため。
        const borders = {};
        let anyBorder = false;
        for (const side of ['Top', 'Right', 'Bottom', 'Left']) {
          const w = px(cs['border' + side + 'Width']);
          const c = rgb(cs['border' + side + 'Color']);
          const st = cs['border' + side + 'Style'];
          if (w > 0 && c && st !== 'none') { borders[side.toLowerCase()] = { w, hex: c.hex }; anyBorder = true; }
        }
        const rad = px(cs.borderTopLeftRadius);
        const isImg = el.tagName === 'IMG';

        if (bg || bi || anyBorder || isImg) {
          out.push({
            kind: isImg ? 'img' : 'box',
            tag: el.tagName.toLowerCase(),
            cls: (el.className && typeof el.className === 'string' ? el.className : '').trim().slice(0, 60),
            x: px(r.left), y: px(top), w: px(r.width), h: px(r.height),
            bg, bgImage: bi, borders, radius: rad,
            opacity: px(cs.opacity),
            alt: isImg ? (el.getAttribute('alt') || '') : undefined,
          });
        }
      }

      // 直下のテキストノードだけを拾う（親子で重複させない）
      for (const node of el.childNodes) {
        if (node.nodeType !== 3) continue;
        const t = node.textContent.replace(/\s+/g, ' ').trim();
        if (!t) continue;
        const range = document.createRange();
        range.selectNodeContents(node);
        const rects = Array.from(range.getClientRects()).filter(q => q.width > 0 && q.height > 0);
        if (!rects.length) continue;
        const cs2 = getComputedStyle(el);
        const key = t + '@' + Math.round(rects[0].left) + ',' + Math.round(rects[0].top + window.scrollY);
        if (seenText.has(key)) continue;
        seenText.add(key);

        // 行ごとに分割して、行頭ベースライン座標で持つ。
        // ベースラインは高さ0の inline-block を差し込んで実測する（フォント依存の推定を避ける）。
        const fs = px(cs2.fontSize);
        const lh = cs2.lineHeight === 'normal' ? fs * 1.5 : px(cs2.lineHeight);
        // Range の client rect の上端はフォントのコンテンツ枠上端なので、
        // baseline = rect.top + ascent。ascent は canvas のフォントメトリクスから取る。
        // （高さ0の inline-block を差し込む方法は line-height が大きいと行ボックス上端を返して外す）
        let baseOff = fs * 0.88;
        try {
          const cv = window.__probeCanvas || (window.__probeCanvas = document.createElement('canvas').getContext('2d'));
          cv.font = `${cs2.fontStyle} ${cs2.fontWeight} ${cs2.fontSize} ${cs2.fontFamily}`;
          const m = cv.measureText('あAg');
          if (m.fontBoundingBoxAscent) baseOff = m.fontBoundingBoxAscent;
        } catch (e) {}

        const lines = [];
        for (const q of rects) {
          lines.push({
            x: px(q.left), y: px(q.top + window.scrollY),
            w: px(q.width), h: px(q.height),
            baseline: px(q.top + window.scrollY + baseOff),
          });
        }
        out.push({
          kind: 'text',
          tag: el.tagName.toLowerCase(),
          cls: (el.className && typeof el.className === 'string' ? el.className : '').trim().slice(0, 60),
          text: t,
          lines,
          fontSize: fs,
          lineHeight: lh,
          fontFamily: cs2.fontFamily,
          fontWeight: cs2.fontWeight,
          letterSpacing: cs2.letterSpacing === 'normal' ? 0 : px(cs2.letterSpacing),
          align: cs2.textAlign,
          color: rgb(cs2.color),
        });
      }

      for (const c of el.children) walk(c, depth + 1);
    };

    walk(document.body, 0);
    return {
      title: document.title,
      pageWidth: document.documentElement.scrollWidth,
      // scrollHeight はビューポートより小さくならない（内容が 900px でも 1000 と出る）ので、
      // body と全要素の下端から内容の実寸を出す
      pageHeight: (() => {
        let bottom = document.body.getBoundingClientRect().bottom;
        for (const el of document.body.querySelectorAll('*')) {
          const r = el.getBoundingClientRect();
          if (r.height > 0 && r.bottom > bottom) bottom = r.bottom;
        }
        return Math.round((bottom + window.scrollY) * 100) / 100;
      })(),
      bodyBg: rgb(getComputedStyle(document.body).backgroundColor),
      nodes: out,
    };
  });

  require('fs').writeFileSync(OUT, JSON.stringify(data, null, 1));
  // 内容がビューポートより短いときは、余白の帯が写らないよう内容の高さで切る
  const shotPath = OUT.replace(/\.json$/, '.png');
  if (data.pageHeight < page.viewport().height) {
    await page.screenshot({ path: shotPath, clip: { x: 0, y: 0, width: data.pageWidth, height: Math.ceil(data.pageHeight) } });
  } else {
    await page.screenshot({ path: shotPath, fullPage: true });
  }
  console.log(`${data.title} / ${data.pageWidth}x${data.pageHeight} / nodes=${data.nodes.length}`);
  await browser.close();
})();
