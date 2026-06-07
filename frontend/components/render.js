/* Markdown + math + code + diagram + plot rendering (spec §9, §10). */
window.OpenLM = window.OpenLM || {};
(function (O) {
  let md = null, mermaidReady = false;

  function escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  function getMd() {
    if (md) return md;
    md = window.markdownit({
      html: false, linkify: true, breaks: false,
      highlight: (str, lang) => {
        if (lang === "mermaid") return '<div class="mermaid">' + escapeHtml(str) + "</div>";
        if (lang && window.hljs && window.hljs.getLanguage(lang)) {
          try { return '<pre class="hljs"><code>' + window.hljs.highlight(str, { language: lang }).value + "</code></pre>"; }
          catch (e) { /* fall through */ }
        }
        return '<pre class="hljs"><code>' + escapeHtml(str) + "</code></pre>";
      },
    });
    return md;
  }

  O.escapeHtml = escapeHtml;

  // Render markdown text into an element, then enrich math/diagrams/plots.
  O.renderMarkdown = function (el, text) {
    text = text || "";
    const plots = [];
    text = text.replace(/\[PLOT:\s*([^\]]+)\]/g, (m, expr) => {
      plots.push(expr.trim());
      return "\n\nPLOTHOLDER_" + (plots.length - 1) + "\n\n";
    });

    let html = getMd().render(text);
    html = html.replace(/<p>PLOTHOLDER_(\d+)<\/p>/g, (m, i) =>
      '<div class="plot-box"><canvas data-expr="' +
      escapeHtml(plots[+i] || "") + '" width="520" height="280"></canvas></div>');

    el.classList.add("md");
    el.innerHTML = html;

    if (window.renderMathInElement) {
      try {
        window.renderMathInElement(el, {
          delimiters: [
            { left: "$$", right: "$$", display: true },
            { left: "$", right: "$", display: false },
            { left: "\\(", right: "\\)", display: false },
            { left: "\\[", right: "\\]", display: true },
          ],
          throwOnError: false,
        });
      } catch (e) { /* ignore */ }
    }

    const nodes = el.querySelectorAll(".mermaid");
    if (nodes.length && window.mermaid) {
      const wantTheme = document.body.classList.contains("theme-light") ? "default" : "dark";
      if (!mermaidReady || mermaidReady !== wantTheme) {
        try { window.mermaid.initialize({ startOnLoad: false, theme: wantTheme, securityLevel: "loose" }); } catch (e) {}
        mermaidReady = wantTheme;
      }
      try { window.mermaid.run({ nodes }); } catch (e) {}
    }

    el.querySelectorAll("canvas[data-expr]").forEach(drawPlot);
  };

  // Allowlist of identifiers the plot expression may reference: the variable
  // `x` plus a fixed set of Math members. Anything else is rejected, so a model
  // emitting [PLOT: alert(1)] or similar cannot reach globals via new Function.
  const ALLOWED_IDENTS = new Set([
    "x", "PI", "E", "abs", "acos", "acosh", "asin", "asinh", "atan", "atan2",
    "atanh", "cbrt", "ceil", "cos", "cosh", "exp", "expm1", "floor", "hypot",
    "log", "log2", "log10", "log1p", "max", "min", "pow", "round", "sign",
    "sin", "sinh", "sqrt", "tan", "tanh", "trunc",
  ]);

  function safeExpr(expr) {
    // Only math characters allowed (no quotes, brackets, semicolons, etc.).
    if (!/^[-+*/%.,()\s0-9a-zA-Z_]+$/.test(expr)) return null;
    // Every identifier must be in the allowlist.
    const idents = expr.match(/[a-zA-Z_][a-zA-Z0-9_]*/g) || [];
    for (const id of idents) if (!ALLOWED_IDENTS.has(id)) return null;
    return expr;
  }

  function drawPlot(cv) {
    const raw = cv.getAttribute("data-expr");
    const expr = safeExpr(raw);
    if (expr === null) {
      cv.replaceWith(document.createTextNode("[PLOT rejected: disallowed expression '" + raw + "']"));
      return;
    }
    let f;
    // expr is validated against a char + identifier allowlist above.
    try { f = new Function("x", "with(Math){return (" + expr + ");}"); f(0); }
    catch (e) { cv.replaceWith(document.createTextNode("[PLOT error: " + raw + "]")); return; }

    const css = getComputedStyle(document.body);
    const colBg = (css.getPropertyValue("--plot-bg") || "#0e0e0e").trim();
    const colGrid = (css.getPropertyValue("--plot-grid") || "#333").trim();
    const colLine = (css.getPropertyValue("--accent-2") || "#8e9cff").trim();
    const ctx = cv.getContext("2d"), W = cv.width, H = cv.height;
    const x0 = -10, x1 = 10;
    let y0 = Infinity, y1 = -Infinity; const pts = [];
    for (let i = 0; i <= W; i++) {
      const x = x0 + (x1 - x0) * i / W;
      let y; try { y = f(x); } catch (e) { y = NaN; }
      pts.push([x, y]);
      if (isFinite(y)) { if (y < y0) y0 = y; if (y > y1) y1 = y; }
    }
    if (!isFinite(y0) || !isFinite(y1)) { y0 = -1; y1 = 1; }
    if (y0 === y1) { y0 -= 1; y1 += 1; }
    const pad = (y1 - y0) * 0.1; y0 -= pad; y1 += pad;

    ctx.fillStyle = colBg; ctx.fillRect(0, 0, W, H);
    const X = x => (x - x0) / (x1 - x0) * W;
    const Y = y => H - (y - y0) / (y1 - y0) * H;

    ctx.strokeStyle = colGrid; ctx.lineWidth = 1; ctx.beginPath();
    if (y0 < 0 && y1 > 0) { ctx.moveTo(0, Y(0)); ctx.lineTo(W, Y(0)); }
    if (x0 < 0 && x1 > 0) { ctx.moveTo(X(0), 0); ctx.lineTo(X(0), H); }
    ctx.stroke();

    ctx.strokeStyle = colLine; ctx.lineWidth = 2; ctx.beginPath();
    let started = false;
    for (const [x, y] of pts) {
      if (!isFinite(y)) { started = false; continue; }
      const px = X(x), py = Y(y);
      if (!started) { ctx.moveTo(px, py); started = true; } else ctx.lineTo(px, py);
    }
    ctx.stroke();
  }
})(window.OpenLM);
