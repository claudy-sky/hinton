/* Chat mode controller (spec §8.1). */
window.OpenLM = window.OpenLM || {};
(function (O) {
  const S = { convId: null, thinking: false, pendingTool: null };

  const PREFIX = {
    web: "[Use web search to answer] ",
    deep: "[Investigate with deep research and answer as a report] ",
    academic: "[Use academic search (arXiv/Semantic Scholar) to answer] ",
    image: "[Generate an image] ",
  };
  // Labels for the pending one-shot tool pill (shown next to the + button).
  const TOOL_LABEL = { web: "Web search", deep: "Deep research", academic: "Academic search", image: "Generate image" };
  const TOOL_ICON = { web: "globe", deep: "flask", academic: "academic", image: "image" };

  function el(id) { return document.getElementById(id); }

  async function load() {
    // Filter by the shared active project: "__all__" (all), null (unfiled),
    // or an int folder id.
    const folderId = O.state.activeFolderId === undefined ? "__all__" : O.state.activeFolderId;
    const items = await O.call("list_conversations", "chat", folderId);
    renderList(items);
  }

  function renderList(items) {
    const list = el("chat-list");
    list.innerHTML = "";
    items.forEach(c => {
      const it = document.createElement("div");
      it.className = "list-item" + (c.id === S.convId ? " active" : "");
      const t = document.createElement("div"); t.className = "title"; t.textContent = c.title || "New chat";
      const m = document.createElement("div"); m.className = "meta"; m.textContent = O.fmtTime(c.updated_at);
      const assign = document.createElement("button");
      assign.className = "del assign";
      assign.title = "Move to project";
      assign.innerHTML = O.icon("move", 15);
      assign.onclick = (e) => { e.stopPropagation(); openAssignPicker(c, assign); };
      const del = document.createElement("button"); del.className = "del"; del.innerHTML = O.icon("trash", 15);
      del.onclick = async (e) => {
        e.stopPropagation();
        await O.call("delete_conversation", c.id);
        if (S.convId === c.id) { S.convId = null; el("chat-thread").innerHTML = ""; }
        load();
        if (O.folderTree) O.folderTree.load();
      };
      it.onclick = () => open(c.id);
      it.appendChild(t); it.appendChild(m); it.appendChild(assign); it.appendChild(del);
      list.appendChild(it);
    });
  }

  // Popover to assign a conversation to a project (or unfile it).
  let assignMenu = null;
  function closeAssign() { if (assignMenu) { assignMenu.remove(); assignMenu = null; } }
  document.addEventListener("click", (e) => {
    if (assignMenu && !e.target.closest(".folder-popover")) closeAssign();
  });
  async function openAssignPicker(c, anchor) {
    closeAssign();
    let folders = [];
    try { folders = await O.call("list_folders"); } catch (e) {}
    const menu = document.createElement("div");
    menu.className = "folder-popover";
    const r = anchor.getBoundingClientRect();
    menu.style.left = Math.min(r.left - 150, window.innerWidth - 210) + "px";
    menu.style.top = (r.bottom + 4) + "px";

    const head = document.createElement("div");
    head.className = "folder-popover-head"; head.textContent = "Move chat to:";
    menu.appendChild(head);

    const mkItem = (icon, label, folderId) => {
      const b = document.createElement("button");
      b.className = "folder-popover-item";
      b.innerHTML = '<span class="ic">' + O.icon(icon, 15) + "</span><span>" + O.escapeHtml(label) + "</span>";
      b.onclick = async () => {
        closeAssign();
        await O.call("assign_conversation", c.id, folderId);
        O.toast(folderId == null ? "Unfiled" : "Moved to project");
        load();
        if (O.folderTree) O.folderTree.load();
      };
      return b;
    };
    menu.appendChild(mkItem("message", "Unfiled", null));
    folders.forEach(f => menu.appendChild(mkItem("folder", f.name || "Folder", f.id)));
    document.body.appendChild(menu);
    assignMenu = menu;
  }

  async function open(convId) {
    S.convId = convId;
    const { messages } = await O.call("get_conversation", convId);
    const thread = el("chat-thread"); thread.innerHTML = "";
    messages.filter(m => m.role === "user" || m.role === "assistant")
      .forEach(m => O.appendMessage(thread, m));
    load();
  }

  async function ensureConv() {
    if (S.convId) return S.convId;
    // New chats inherit the active project (folder) so context is shared.
    const folderId = O.activeFolderIdForNew ? O.activeFolderIdForNew() : null;
    const c = await O.call("new_conversation", "chat", "New chat", null, folderId);
    S.convId = c.id;
    if (O.folderTree) O.folderTree.load();
    return c.id;
  }

  async function send() {
    const input = el("chat-input");
    let text = input.value.trim();
    if (!text) return;
    if (S.pendingTool) { text = PREFIX[S.pendingTool] + text; clearPending(); }

    const convId = await ensureConv();
    const thread = el("chat-thread");
    O.appendMessage(thread, { role: "user", content: input.value.trim() });
    input.value = ""; O.autoGrow(input);
    O.curStatusEl = el("chat-status");
    O.setStatus('<span class="spin-inline"></span>Generating…');
    const revertSend = O.beginSend("chat-send");

    try {
      const res = await O.call("send_message", convId, text, "chat", S.thinking);
      O.appendMessage(thread, res.message);
      if (res.stopped) O.toast("Stopped");
    } catch (e) {
      O.appendMessage(thread, { role: "assistant", content: "⚠️ Error: " + e.message });
    } finally {
      O.setStatus(""); revertSend();
      O.refreshStatus(); load();
    }
  }

  // ---- Unified "+" tool menu --------------------------------------------
  function toggleMenu(force) {
    const menu = el("chat-tool-menu"), add = el("chat-tool-add");
    const openNow = force != null ? force : menu.classList.contains("hidden");
    menu.classList.toggle("hidden", !openNow);
    add.classList.toggle("open", openNow);
    add.setAttribute("aria-expanded", openNow ? "true" : "false");
  }

  function setThinking(on) {
    S.thinking = on;
    const item = document.querySelector('#chat-tool-menu [data-toggle="thinking"]');
    if (item) item.classList.toggle("on", on);
  }

  function setPending(tool) {
    S.pendingTool = tool;
    renderPendingPill();
  }
  function clearPending() {
    S.pendingTool = null;
    renderPendingPill();
  }

  function renderPendingPill() {
    const slot = el("chat-tool-pill");
    if (!slot) return;
    slot.innerHTML = "";
    if (!S.pendingTool) return;
    const tool = S.pendingTool;
    const pill = document.createElement("div");
    pill.className = "tool-pill";
    pill.innerHTML = '<span class="ic">' + O.icon(TOOL_ICON[tool] || "globe", 15) + "</span>" +
      "<span>" + (TOOL_LABEL[tool] || tool) + "</span>";
    const x = document.createElement("button");
    x.className = "pill-x"; x.title = "Remove"; x.innerHTML = O.icon("x", 13);
    x.onclick = () => clearPending();
    pill.appendChild(x);
    slot.appendChild(pill);
  }

  function init() {
    O.bindComposer(el("chat-input"), el("chat-send"), send);
    document.querySelector('[data-new="chat"]').onclick = async () => {
      const folderId = O.activeFolderIdForNew ? O.activeFolderIdForNew() : null;
      const c = await O.call("new_conversation", "chat", "New chat", null, folderId);
      S.convId = c.id; el("chat-thread").innerHTML = ""; load();
      if (O.folderTree) O.folderTree.load();
    };
    const search = document.querySelector('[data-search="chat"]');
    if (search) search.oninput = filter;

    // + button toggles the tool menu.
    el("chat-tool-add").onclick = (e) => { e.stopPropagation(); toggleMenu(); };

    // Menu items: reuse the existing data-tool / data-toggle / data-attach semantics.
    document.querySelectorAll("#chat-tool-menu .tool-item").forEach(item => {
      item.onclick = (e) => {
        e.stopPropagation();
        if (item.dataset.toggle === "thinking") {
          setThinking(!S.thinking);
          toggleMenu(false);
          return;
        }
        if (item.dataset.attach === "chat") {
          O.toast("You can attach files in the desktop app.");
          toggleMenu(false);
          return;
        }
        const tool = item.dataset.tool;
        if (tool) {
          setPending(S.pendingTool === tool ? null : tool);
          toggleMenu(false);
        }
      };
    });

    // Close the menu on any outside click.
    document.addEventListener("click", (e) => {
      const tools = el("chat-tool-menu");
      if (tools.classList.contains("hidden")) return;
      if (!e.target.closest("#chat-chips")) toggleMenu(false);
    });

    renderPendingPill();
    return load();
  }

  function filter() {
    const q = (document.querySelector('[data-search="chat"]').value || "").toLowerCase();
    document.querySelectorAll("#chat-list .list-item").forEach(it => {
      const t = it.querySelector(".title").textContent.toLowerCase();
      it.style.display = t.includes(q) ? "" : "none";
    });
  }

  O.chat = { init, load, onShow() { O.curStatusEl = el("chat-status"); } };
})(window.OpenLM);
