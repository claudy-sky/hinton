/* Document viewer: PDF via pdf.js, text fallback otherwise (spec §8.2, §14.4). */
window.OpenLM = window.OpenLM || {};
(function (O) {
  function fileUrl(path) {
    if (window.pywebview) return "file:///" + String(path).replace(/\\/g, "/");
    return "/file?path=" + encodeURIComponent(path);
  }

  async function renderPdf(viewer, source) {
    if (window.pdfjsLib && window.pdfjsLib.GlobalWorkerOptions) {
      window.pdfjsLib.GlobalWorkerOptions.workerSrc = "vendor/pdfjs/pdf.worker.min.js";
    }
    const pdf = await window.pdfjsLib.getDocument(fileUrl(source.path)).promise;
    const n = Math.min(pdf.numPages, 12);
    for (let i = 1; i <= n; i++) {
      const page = await pdf.getPage(i);
      const vp = page.getViewport({ scale: 1.3 });
      const canvas = document.createElement("canvas");
      canvas.width = vp.width; canvas.height = vp.height;
      viewer.appendChild(canvas);
      await page.render({ canvasContext: canvas.getContext("2d"), viewport: vp }).promise;
    }
    const nav = document.createElement("div");
    nav.className = "doc-nav";
    nav.textContent = `${source.name} · ${pdf.numPages} pages`;
    viewer.appendChild(nav);
  }

  async function renderText(viewer, source) {
    const { text } = await O.call("get_source_text", source.id);
    const div = document.createElement("div");
    div.className = "doc-text";
    div.textContent = text || "(No extracted text — check the indexing status.)";
    viewer.appendChild(div);
  }

  O.docViewer = {
    async show(viewer, source) {
      viewer.innerHTML = "";
      if (!source) { viewer.innerHTML = '<div class="empty">Select a source.</div>'; return; }
      if (source.kind === "pdf" && window.pdfjsLib) {
        try { await renderPdf(viewer, source); return; } catch (e) { /* fall back */ }
      }
      try { await renderText(viewer, source); }
      catch (e) { viewer.innerHTML = '<div class="empty">Failed to open: ' + O.escapeHtml(e.message) + "</div>"; }
    },
  };
})(window.OpenLM);
