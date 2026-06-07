/* Notebook (study hub) mode controller (spec §8.2, §14, §15, §16). */
window.OpenLM = window.OpenLM || {};
(function (O) {
  const S = { nbId: null, sourceId: null, convId: null, sourceName: null };
  const ICON = { pdf: "file-text", docx: "file-text", xlsx: "sheet", image: "image",
                 audio: "mic", txt: "file", md: "file" };

  function el(id) { return document.getElementById(id); }

  async function loadNotebooks() {
    const nbs = await O.call("list_notebooks");
    const sel = el("nb-select"); sel.innerHTML = "";
    if (!nbs.length) {
      const o = document.createElement("option"); o.value = ""; o.textContent = "No notebooks — create one";
      sel.appendChild(o); S.nbId = null; el("nb-sources").innerHTML = ""; return;
    }
    nbs.forEach(nb => {
      const o = document.createElement("option"); o.value = nb.id; o.textContent = nb.name;
      sel.appendChild(o);
    });
    if (!S.nbId || !nbs.find(n => n.id === S.nbId)) S.nbId = nbs[0].id;
    sel.value = S.nbId;
    await loadSources();
  }

  async function loadSources() {
    if (!S.nbId) return;
    const sources = await O.call("list_sources", S.nbId);
    const list = el("nb-sources"); list.innerHTML = "";
    if (!sources.length) {
      const e = document.createElement("div"); e.className = "empty"; e.textContent = "Add a source.";
      list.appendChild(e); return;
    }
    sources.forEach(s => {
      const it = document.createElement("div");
      it.className = "list-item" + (s.id === S.sourceId ? " active" : "");
      const t = document.createElement("div"); t.className = "title";
      t.innerHTML = '<span class="ic">' + O.icon(ICON[s.kind] || "file", 16) + "</span>";
      t.appendChild(document.createTextNode(s.name || "Source"));
      const m = document.createElement("div"); m.className = "meta";
      const badge = s.status === "indexed" ? `${s.n_chunks} chunks`
        : s.status === "error" ? "error" : "processing…";
      m.innerHTML = '<span class="badge ' + (s.status === "indexed" ? "" : s.status === "error" ? "error" : "pending") + '">' + badge + "</span>";
      it.append(t, m);
      it.onclick = () => openSource(s);
      list.appendChild(it);
    });
  }

  async function openSource(s) {
    S.sourceId = s.id;
    S.sourceName = s.name || "this source";
    await O.docViewer.show(el("nb-viewer"), s);
    attachSelectionPopover(el("nb-viewer"));
    loadSources();
  }

  // Floating popover on text selection (spec §14.4): "Explain this" keeps the
  // discussion grounded in the notebook; "Discuss in Chat" hands the selection
  // (or the current source name) off to the main Chat view.
  let popover = null;
  function attachSelectionPopover(viewer) {
    if (viewer.dataset.sel) return;
    viewer.dataset.sel = "1";
    viewer.addEventListener("mouseup", () => {
      const sel = window.getSelection();
      const text = sel ? sel.toString().trim() : "";
      removePopover();
      if (text.length < 4) return;
      const range = sel.getRangeAt(0).getBoundingClientRect();
      popover = document.createElement("div");
      popover.className = "nb-sel-popover";
      popover.style.cssText = "position:fixed;z-index:60;display:flex;gap:6px;";
      popover.style.left = range.left + "px";
      popover.style.top = (range.bottom + 6) + "px";

      const explain = document.createElement("button");
      explain.className = "btn-primary"; explain.style.cssText = "font-size:12px;padding:6px 10px;";
      explain.innerHTML = O.icon("message", 15) + "<span>Explain this</span>";
      explain.onclick = () => {
        const inp = el("nb-input");
        inp.value = "Explain the following:\n\"" + text + "\"";
        O.autoGrow(inp); inp.focus(); removePopover();
      };

      const discuss = document.createElement("button");
      discuss.className = "btn-secondary"; discuss.style.cssText = "font-size:12px;padding:6px 10px;";
      discuss.innerHTML = O.icon("message", 15) + "<span>Discuss in Chat</span>";
      discuss.onclick = () => {
        removePopover();
        const src = S.sourceName ? (' (from "' + S.sourceName + '")') : "";
        if (O.sendToChat) O.sendToChat("Regarding this excerpt" + src + ":\n\n> " + text + "\n\n");
      };

      popover.append(explain, discuss);
      document.body.appendChild(popover);
    });
  }
  function removePopover() { if (popover) { popover.remove(); popover = null; } }

  async function ensureConv() {
    if (S.convId) return S.convId;
    // Notebook chats inherit the shared active project (folder) too.
    const folderId = O.activeFolderIdForNew ? O.activeFolderIdForNew() : null;
    const c = await O.call("new_conversation", "notebook", "Notebook chat", S.nbId, folderId);
    S.convId = c.id; return c.id;
  }

  async function send() {
    if (!S.nbId) { O.toast("Select or create a notebook first."); return; }
    const input = el("nb-input");
    const text = input.value.trim();
    if (!text) return;
    const convId = await ensureConv();
    const thread = el("nb-thread");
    O.appendMessage(thread, { role: "user", content: text });
    input.value = ""; O.autoGrow(input);
    O.curStatusEl = el("nb-status");
    O.setStatus('<span class="spin-inline"></span>Generating from sources…');
    const revertSend = O.beginSend("nb-send");
    try {
      const res = await O.call("send_message", convId, text, "notebook", false, S.nbId);
      O.appendMessage(thread, res.message);
      if (res.stopped) O.toast("Stopped");
    } catch (e) {
      O.appendMessage(thread, { role: "assistant", content: "⚠️ Error: " + e.message });
    } finally {
      O.setStatus(""); revertSend(); O.refreshStatus();
    }
  }

  async function generate(kind) {
    if (!S.nbId) { O.toast("Select or create a notebook first."); return; }
    const out = el("nb-gen-out");
    out.innerHTML = '<div class="empty"><span class="spin-inline"></span>Generating…</div>';
    try {
      const res = await O.call("notebook_generate", S.nbId, kind);
      if (!res.ok) { out.innerHTML = '<div class="empty">' + O.escapeHtml(res.error || "Failed") + "</div>"; return; }
      out.innerHTML = "";
      if (kind === "quiz") {
        const items = O.quiz.parse(res.content);
        if (items) { O.quiz.render(out, items, S.nbId); return; }
      }
      const div = document.createElement("div");
      O.renderMarkdown(div, res.content || "(no content)");
      out.appendChild(div);
    } catch (e) {
      out.innerHTML = '<div class="empty">Error: ' + O.escapeHtml(e.message) + "</div>";
    }
  }

  async function addSource() {
    if (!S.nbId) { O.toast("Create a notebook first."); return; }
    const path = window.prompt("Enter the full path of the file to add (PDF/DOCX/XLSX/TXT/image/audio):");
    if (!path) return;
    O.toast("Indexing source…");
    const res = await O.call("add_source", S.nbId, path);
    if (res.ok) O.toast(`Indexed: ${res.n_chunks} chunks`);
    else O.toast("Failed: " + (res.error || ""));
    loadSources();
  }

  function init() {
    O.bindComposer(el("nb-input"), el("nb-send"), send);
    el("nb-new").onclick = async () => {
      const name = window.prompt("New notebook name (e.g. Physics 1):");
      if (!name) return;
      const nb = await O.call("create_notebook", name);
      S.nbId = nb.id; S.convId = null; loadNotebooks();
    };
    el("nb-select").onchange = (e) => {
      S.nbId = parseInt(e.target.value, 10) || null;
      S.convId = null; S.sourceId = null;
      el("nb-thread").innerHTML = "";
      el("nb-viewer").innerHTML = '<div class="empty">Select a source to view it here.</div>';
      loadSources();
    };
    el("nb-add-source").onclick = addSource;
    document.querySelectorAll("#nb-gen .gen-chips .chip").forEach(c =>
      c.onclick = () => generate(c.dataset.gen));
    el("nb-gen-pdf").onclick = () => generate("pdf");
    return loadNotebooks();
  }

  O.notebook = { init, onShow() { O.curStatusEl = el("nb-status"); loadNotebooks(); } };
})(window.OpenLM);
