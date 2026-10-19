/*
 * ai2json.jsx - Illustrator ドキュメントをコーディング用の仕様JSONに書き出す
 *
 * 直接叩かず ai2spec.sh 経由で実行する想定。
 * 呼び出し側は事前にグローバル変数 A2J にオプションを入れておく:
 *   A2J = { outDir, png, pngScale, maxItems, includeHidden, round }
 *
 * 座標系: アートボード左上を原点とし、Y は下方向が正（= Web と同じ向き）に正規化する。
 * 単位: pt。Web用(RGB/72ppi)ドキュメントなら 1pt = 1px でそのまま使える。
 */
(function () {
  var OPT = (typeof A2J !== "undefined" && A2J) ? A2J : {};
  var opt = {
    outDir:        OPT.outDir || null,
    png:           OPT.png !== false,
    pngScale:      OPT.pngScale || 2,
    maxItems:      OPT.maxItems || 5000,
    includeHidden: OPT.includeHidden === true,
    round:         (OPT.round === undefined || OPT.round === null) ? 2 : OPT.round
  };

  if (app.documents.length === 0) return "ERR\t開いているドキュメントがありません";

  /* ---------- 数値・JSON シリアライザ (ExtendScript は ES3 で JSON 非搭載) ---------- */

  function r(n) {
    if (n === null || n === undefined) return null;
    n = Number(n);
    if (isNaN(n) || !isFinite(n)) return null;
    var p = Math.pow(10, opt.round);
    return Math.round(n * p) / p;
  }

  function pad4(h) { while (h.length < 4) h = "0" + h; return h; }

  function esc(s) {
    s = String(s);
    var out = "", i, c, code;
    for (i = 0; i < s.length; i++) {
      c = s.charAt(i);
      code = s.charCodeAt(i);
      if (c === '"') out += '\\"';
      else if (c === "\\") out += "\\\\";
      else if (code === 10) out += "\\n";
      else if (code === 13) out += "\\n";      // AI の段落区切り CR も \n に寄せる
      else if (code === 9) out += "\\t";
      else if (code === 3) out += "\\n";       // ETX = テキストフレーム内の改行
      else if (code < 32 || code === 0x2028 || code === 0x2029) out += "\\u" + pad4(code.toString(16));
      else out += c;
    }
    return '"' + out + '"';
  }

  function ser(v, pad) {
    var pad2 = pad + "  ", i, k, parts;
    if (v === null || v === undefined) return "null";
    var t = typeof v;
    if (t === "number") return isFinite(v) ? String(v) : "null";
    if (t === "boolean") return v ? "true" : "false";
    if (t === "string") return esc(v);
    if (v instanceof Array) {
      if (v.length === 0) return "[]";
      parts = [];
      for (i = 0; i < v.length; i++) parts.push(pad2 + ser(v[i], pad2));
      return "[\n" + parts.join(",\n") + "\n" + pad + "]";
    }
    parts = [];
    for (k in v) {
      if (!v.hasOwnProperty(k)) continue;
      if (v[k] === undefined) continue;
      parts.push(pad2 + esc(k) + ": " + ser(v[k], pad2));
    }
    if (parts.length === 0) return "{}";
    return "{\n" + parts.join(",\n") + "\n" + pad + "}";
  }

  function enumName(v) { return String(v).replace(/^[A-Za-z]+\./, ""); }

  /* ---------- 色 ---------- */

  function hex2(n) {
    var v = Math.round(Number(n));
    if (isNaN(v) || v < 0) v = 0;
    if (v > 255) v = 255;
    var s = v.toString(16);
    return s.length < 2 ? "0" + s : s;
  }

  var sawGradient = false;

  function colorOf(c) {
    if (!c) return null;
    var tn;
    try { tn = c.typename; } catch (e) { return null; }
    if (tn === "NoColor") return null;

    if (tn === "RGBColor") {
      return { type: "rgb", hex: "#" + hex2(c.red) + hex2(c.green) + hex2(c.blue) };
    }
    if (tn === "GrayColor") {
      var g = Math.round(255 * (1 - Number(c.gray) / 100));
      return { type: "gray", gray: r(c.gray), hex: "#" + hex2(g) + hex2(g) + hex2(g) };
    }
    if (tn === "CMYKColor") {
      var o = { type: "cmyk", c: r(c.cyan), m: r(c.magenta), y: r(c.yellow), k: r(c.black) };
      try {
        var rgb = app.convertSampleColor(
          ImageColorSpace.CMYK, [c.cyan, c.magenta, c.yellow, c.black],
          ImageColorSpace.RGB, ColorConvertPurpose.defaultpurpose);
        o.hex = "#" + hex2(rgb[0]) + hex2(rgb[1]) + hex2(rgb[2]);
        o.hexIsApprox = true;   // CMYK->RGB 変換なので参考値
      } catch (e) {}
      return o;
    }
    if (tn === "SpotColor") {
      var s = { type: "spot" };
      try { s.name = c.spot.name; } catch (e) {}
      try { s.tint = r(c.tint); } catch (e) {}
      try {
        var inner = colorOf(c.spot.color);
        if (inner && inner.hex) s.hex = inner.hex;
      } catch (e) {}
      return s;
    }
    if (tn === "GradientColor") {
      // 角度は出さない。GradientColor.angle は Illustrator の DOM 上で機能しておらず、
      // 実際の向きに関わらず常に 0 を返すため、載せると嘘になる。
      sawGradient = true;
      var gr = { type: "gradient", stops: [] };
      try { gr.kind = enumName(c.gradient.type); } catch (e) {}
      try {
        var st = c.gradient.gradientStops;
        for (var i = 0; i < st.length; i++) {
          gr.stops.push({
            at: r(st[i].rampPoint),
            opacity: r(st[i].opacity),
            color: colorOf(st[i].color)
          });
        }
      } catch (e) {}
      return gr;
    }
    if (tn === "PatternColor") {
      var p = { type: "pattern" };
      try { p.name = c.pattern.name; } catch (e) {}
      return p;
    }
    return { type: String(tn) };
  }

  /* ---------- デザイントークン集計 ---------- */

  var tokColor = {}, tokColorOrder = [];
  var tokFont = {},  tokFontOrder = [];

  function noteColor(c, role) {
    if (!c || !c.hex) return;
    var k = c.hex;
    if (!tokColor[k]) { tokColor[k] = { hex: k, count: 0, roles: {} }; tokColorOrder.push(k); }
    tokColor[k].count++;
    tokColor[k].roles[role] = (tokColor[k].roles[role] || 0) + 1;
  }

  function noteFont(run) {
    if (!run || !run.font) return;
    var k = run.font + "|" + (run.size === null || run.size === undefined ? "?" : run.size);
    if (!tokFont[k]) {
      tokFont[k] = { font: run.font, size: run.size, count: 0 };
      tokFontOrder.push(k);
    }
    tokFont[k].count++;
  }

  function byCountDesc(map, order) {
    var arr = [], i;
    for (i = 0; i < order.length; i++) arr.push(map[order[i]]);
    arr.sort(function (a, b) { return b.count - a.count; });
    return arr;
  }

  /* ---------- 角丸の推定 (ライブシェイプの角丸は DOM から直接読めないため) ---------- */

  function cornerRadius(p) {
    try {
      if (!p.closed) return null;
      var pts = p.pathPoints;
      if (pts.length !== 8) return null;
      var xs = [], ys = [], i;
      for (i = 0; i < 8; i++) { xs.push(pts[i].anchor[0]); ys.push(pts[i].anchor[1]); }
      var minX = Math.min.apply(null, xs), maxX = Math.max.apply(null, xs);
      var maxY = Math.max.apply(null, ys);
      var top = [];
      for (i = 0; i < 8; i++) if (Math.abs(ys[i] - maxY) < 0.01) top.push(xs[i]);
      if (top.length !== 2) return null;
      var rad = ((maxX - minX) - Math.abs(top[0] - top[1])) / 2;
      if (rad <= 0.05) return null;
      return r(rad);
    } catch (e) { return null; }
  }

  /* ---------- 図形の種類判定 (rect / ellipse / roundedRect の区別は DOM に無い) ---------- */

  function classifyShape(p, rad) {
    try {
      if (!p.closed) return null;
      var pts = p.pathPoints, n = pts.length, i, curved = 0;
      for (i = 0; i < n; i++) {
        var a = pts[i].anchor, ld = pts[i].leftDirection, rd = pts[i].rightDirection;
        if (Math.abs(a[0] - ld[0]) > 0.01 || Math.abs(a[1] - ld[1]) > 0.01 ||
            Math.abs(a[0] - rd[0]) > 0.01 || Math.abs(a[1] - rd[1]) > 0.01) curved++;
      }
      if (n === 8 && rad !== null) return "roundedRect";
      if (n === 4 && curved === 0) return "rect";
      if (n === 4 && curved === 4) return "ellipse";
      if (curved === 0) return "polygon";
      return null;
    } catch (e) { return null; }
  }

  /* ---------- テキスト ---------- */

  function textInfo(tf, ab) {
    var t = {}, i;
    try { t.text = tf.contents; } catch (e) {}
    try { t.kind = enumName(tf.kind); } catch (e) {}
    // box は字形の実インク範囲。行頭ベースラインの位置も別に出す（CSS に起こすときはこちらが基準）。
    try {
      var an = tf.anchor;
      t.baseline = { x: r(an[0] - ab[0]), y: r(ab[1] - an[1]) };
    } catch (e) {}
    try { if (String(tf.orientation).indexOf("HORIZONTAL") < 0) t.orientation = enumName(tf.orientation); } catch (e) {}

    var runs = [];
    try {
      var ps = tf.paragraphs;
      for (i = 0; i < ps.length; i++) {
        var p = ps[i], run = {}, ca = null;
        try { run.text = p.contents; } catch (e) {}
        try { ca = (p.characters.length > 0) ? p.characters[0].characterAttributes : p.characterAttributes; } catch (e) {}
        if (ca) {
          try { run.font = ca.textFont.name; } catch (e) {}
          try { run.fontFamily = ca.textFont.family; } catch (e) {}
          try { run.fontStyle = ca.textFont.style; } catch (e) {}
          try { run.size = r(ca.size); } catch (e) {}
          try {
            if (ca.autoLeading) run.autoLeading = true;
            run.leading = r(ca.leading);
          } catch (e) {}
          try { if (ca.tracking) run.tracking = r(ca.tracking); } catch (e) {}
          try { run.color = colorOf(ca.fillColor); } catch (e) {}
          try { if (Math.abs(ca.horizontalScale - 100) > 0.01) run.hScale = r(ca.horizontalScale); } catch (e) {}
          try { if (Math.abs(ca.verticalScale - 100) > 0.01) run.vScale = r(ca.verticalScale); } catch (e) {}
        }
        try { run.align = enumName(p.paragraphAttributes.justification); } catch (e) {}
        noteFont(run);
        noteColor(run.color, "text");
        runs.push(run);
      }
    } catch (e) {}
    if (runs.length) t.runs = runs;
    return t;
  }

  /* ---------- アイテム走査 ---------- */

  var itemCount = 0, truncated = false, seen = {}, uidSeq = 0;

  function uidOf(it) {
    var u = null;
    try { u = it.uuid; } catch (e) {}
    if (!u) u = "seq:" + (++uidSeq);
    return u;
  }

  function itemOf(it, ab, layerName) {
    if (itemCount >= opt.maxItems) { truncated = true; return null; }

    var uid = uidOf(it);
    if (seen[uid]) return null;      // コレクションがフラットに返る場合の重複よけ
    seen[uid] = true;

    var hidden = false, locked = false;
    try { hidden = it.hidden; } catch (e) {}
    try { locked = it.locked; } catch (e) {}
    if (hidden && !opt.includeHidden) return null;

    itemCount++;

    var tn = "";
    try { tn = it.typename; } catch (e) { return null; }

    var o = { type: tn.replace(/Item$/, ""), id: uid };
    try { if (it.name) o.name = it.name; } catch (e) {}
    if (layerName) o.layer = layerName;

    try {
      var gb = it.geometricBounds;
      o.box = { x: r(gb[0] - ab[0]), y: r(ab[1] - gb[1]), w: r(gb[2] - gb[0]), h: r(gb[1] - gb[3]) };
    } catch (e) {}
    try {
      var vb = it.visibleBounds;
      var vx = r(vb[0] - ab[0]), vy = r(ab[1] - vb[1]), vw = r(vb[2] - vb[0]), vh = r(vb[1] - vb[3]);
      if (!o.box || vx !== o.box.x || vy !== o.box.y || vw !== o.box.w || vh !== o.box.h) {
        o.visibleBox = { x: vx, y: vy, w: vw, h: vh };   // 線幅・効果込みの見た目の箱
      }
    } catch (e) {}

    try { if (Math.abs(it.opacity - 100) > 0.01) o.opacity = r(it.opacity); } catch (e) {}
    try { var bm = enumName(it.blendingMode); if (bm !== "NORMAL") o.blend = bm; } catch (e) {}
    if (hidden) o.hidden = true;
    if (locked) o.locked = true;

    if (tn === "PathItem" || tn === "CompoundPathItem") {
      var shape = (tn === "PathItem") ? it : null;
      if (!shape) { try { shape = it.pathItems[0]; } catch (e) {} }
      if (shape) {
        try {
          if (shape.filled) { o.fill = colorOf(shape.fillColor); noteColor(o.fill, "fill"); }
        } catch (e) {}
        try {
          if (shape.stroked) {
            o.stroke = colorOf(shape.strokeColor);
            noteColor(o.stroke, "stroke");
            o.strokeWidth = r(shape.strokeWidth);
            try { if (shape.strokeDashes && shape.strokeDashes.length) o.strokeDashes = shape.strokeDashes; } catch (e2) {}
          }
        } catch (e) {}
        if (tn === "PathItem") {
          var rad = cornerRadius(shape);
          if (rad !== null) o.cornerRadius = rad;
          var sh = classifyShape(shape, rad);
          if (sh) o.shape = sh;
          try { o.points = shape.pathPoints.length; } catch (e) {}
          try { if (!shape.closed) o.closed = false; } catch (e) {}
          // 単純なパスは端点そのものを出す。箱だけでは / と \\ が区別できず、
          // 斜線・矢羽・チェックなどの「向き」が復元できないため。
          try {
            var pp = shape.pathPoints;
            if (pp.length <= 6) {
              var an = [], j;
              for (j = 0; j < pp.length; j++) {
                an.push([r(pp[j].anchor[0] - ab[0]), r(ab[1] - pp[j].anchor[1])]);
              }
              o.anchors = an;
            }
          } catch (e) {}
        }
      }
      if (tn === "CompoundPathItem") { try { o.subPaths = it.pathItems.length; } catch (e) {} }
      return o;
    }

    if (tn === "TextFrame") {
      var ti = textInfo(it, ab);
      for (var k in ti) if (ti.hasOwnProperty(k)) o[k] = ti[k];
      return o;
    }

    if (tn === "GroupItem") {
      try { if (it.clipped) o.clipped = true; } catch (e) {}
      var kids = [];
      try {
        var ch = it.pageItems;
        for (var i = 0; i < ch.length; i++) {
          var c = itemOf(ch[i], ab, null);   // 子は所属レイヤーが自明なので layer を省く
          if (c) kids.push(c);
        }
      } catch (e) {}
      if (kids.length) o.children = kids;
      return o;
    }

    if (tn === "PlacedItem" || tn === "RasterItem") {
      try { o.file = it.file.fsName; } catch (e) {}
      try { if (it.embedded) o.embedded = true; } catch (e) {}
      return o;
    }

    if (tn === "SymbolItem") {
      try { o.symbol = it.symbol.name; } catch (e) {}
      return o;
    }

    return o;
  }

  function walkLayer(layer, ab) {
    var visible = true;
    try { visible = layer.visible; } catch (e) {}
    if (!visible && !opt.includeHidden) return null;

    var name = "";
    try { name = layer.name; } catch (e) {}

    var node = { layer: name, items: [] };
    if (!visible) node.hidden = true;
    try { if (Math.abs(layer.opacity - 100) > 0.01) node.opacity = r(layer.opacity); } catch (e) {}

    var i;
    try {
      var its = layer.pageItems;
      for (i = 0; i < its.length; i++) {
        var pt = "";
        try { pt = its[i].parent.typename; } catch (e) {}
        if (pt === "GroupItem" || pt === "CompoundPathItem") continue;  // 親側から辿る
        var o = itemOf(its[i], ab, name);
        if (o) node.items.push(o);
      }
    } catch (e) {}

    var subs = [];
    try {
      for (i = 0; i < layer.layers.length; i++) {
        var s = walkLayer(layer.layers[i], ab);
        if (s) subs.push(s);
      }
    } catch (e) {}
    if (subs.length) node.sublayers = subs;

    return node;
  }

  /* ---------- PNG 書き出し（見た目の突き合わせ用） ---------- */

  function exportPNG(doc, dir, base, scale) {
    var out = [];
    try {
      var o = new ExportOptionsPNG24();
      o.antiAliasing = true;
      o.transparency = true;
      o.artBoardClipping = true;
      o.horizontalScale = scale * 100;
      o.verticalScale = scale * 100;
      var savedIdx = doc.artboards.getActiveArtboardIndex();
      for (var i = 0; i < doc.artboards.length; i++) {
        doc.artboards.setActiveArtboardIndex(i);
        var f = new File(dir + "/" + base + "_ab" + (i + 1) + "@" + scale + "x.png");
        doc.exportFile(f, ExportType.PNG24, o);
        out.push(f.fsName);
      }
      doc.artboards.setActiveArtboardIndex(savedIdx);
    } catch (e) {}
    return out;
  }

  /* ---------- 本体 ---------- */

  var prevCoord = null;
  try { prevCoord = app.coordinateSystem; app.coordinateSystem = CoordinateSystem.DOCUMENTCOORDINATESYSTEM; } catch (e) {}

  try {
    var doc = app.activeDocument;

    var docPath = null;
    try { docPath = doc.fullName.fsName; } catch (e) {}

    var base = String(doc.name).replace(/\.[^.]+$/, "");
    var outDir = opt.outDir;
    if (!outDir) {
      var parent = null;
      try { parent = doc.fullName.parent.fsName; } catch (e) {}
      outDir = (parent || Folder.desktop.fsName) + "/" + base + "_spec";
    }
    var dirObj = new Folder(outDir);
    if (!dirObj.exists) dirObj.create();

    var colorSpace = "";
    try { colorSpace = enumName(doc.documentColorSpace); } catch (e) {}

    var spec = {
      meta: {
        document: doc.name,
        path: docPath,
        colorSpace: colorSpace,
        rulerUnits: null,
        units: "pt (Web用RGBドキュメントなら 1pt = 1px)",
        origin: "各アートボードの左上。x は右、y は下が正（Webと同じ）",
        generatedAt: new Date().toString(),
        illustrator: null
      },
      warnings: [],
      artboards: [],
      tokens: {},
      layers: []
    };
    try { spec.meta.rulerUnits = enumName(doc.rulerUnits); } catch (e) {}
    try { spec.meta.illustrator = app.version; } catch (e) {}

    if (colorSpace !== "RGB") {
      spec.warnings.push("ドキュメントカラーモードが " + colorSpace + " です。hex は CMYK からの近似変換値なので、Web用途では RGB ドキュメントに変換してから書き出してください。");
    }

    var i;
    for (i = 0; i < doc.artboards.length; i++) {
      var a = doc.artboards[i];
      var ar = a.artboardRect;
      spec.artboards.push({
        index: i + 1,
        name: a.name,
        w: r(ar[2] - ar[0]),
        h: r(ar[1] - ar[3])
      });
    }

    // レイヤーの座標基準はアートボード1。複数アートボードがある場合は下で補足を出す。
    var ab0 = doc.artboards[0].artboardRect;
    if (doc.artboards.length > 1) {
      spec.warnings.push("アートボードが " + doc.artboards.length + " 枚あります。items の座標はすべてアートボード1の左上が原点です（各アートボード内のローカル座標ではありません）。");
    }

    for (i = 0; i < doc.layers.length; i++) {
      var ln = walkLayer(doc.layers[i], ab0);
      if (ln) spec.layers.push(ln);
    }

    if (truncated) {
      spec.warnings.push("アイテム数が maxItems(" + opt.maxItems + ") に達したため途中で打ち切りました。--max で増やせます。");
    }
    if (sawGradient) {
      spec.warnings.push("グラデーションの「角度」はIllustratorのDOMから取得できないため出力に含めていません。CSSに起こす際はPNGを見て向きを判断してください。");
    }

    spec.tokens.colors = byCountDesc(tokColor, tokColorOrder);
    spec.tokens.fonts = byCountDesc(tokFont, tokFontOrder);
    spec.meta.itemCount = itemCount;

    var jsonPath = outDir + "/" + base + ".spec.json";
    var jf = new File(jsonPath);
    jf.encoding = "UTF-8";
    jf.lineFeed = "Unix";
    jf.open("w");
    jf.write(ser(spec, ""));
    jf.close();

    var pngs = opt.png ? exportPNG(doc, outDir, base, opt.pngScale) : [];

    return "OK\t" + jf.fsName + "\t" + pngs.join("|");
  } catch (err) {
    return "ERR\t" + (err && err.message ? err.message : String(err)) + (err && err.line ? " (line " + err.line + ")" : "");
  } finally {
    try { if (prevCoord !== null) app.coordinateSystem = prevCoord; } catch (e) {}
  }
})();
