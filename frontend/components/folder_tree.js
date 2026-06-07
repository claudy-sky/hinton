/* Projects / nested folder tree for the Chat rail (Hinton).
   Renders folders as an expandable nested tree above the conversation list,
   provides create / subfolder / rename / delete / move affordances, and a
   per-folder settings modal (instructions + tone + context files).

   Selecting a folder sets OpenLM.state.activeFolderId (the shared "active
   project"), which is consumed by every mode controller when creating new
   conversations so project context is shared across Chat / Notebook / Code. */
window.OpenLM = window.OpenLM || {};
(function (O) {
  // Tone enum values must match the backend contract EXACTLY.
  const TONES = ["default", "friendly", "formal", "concise", "detailed", "socratic", "encouraging"];
  const TONE_LABEL = {
    default: "Default", friendly: "Friendly", formal: "Formal", concise: "Concise",
    detailed: "Detailed", socratic: "Socratic", encouraging: "Encouraging",
  };

  // Module state: cached folder list + the set of expanded folder ids.
  const S = { folders: [], expanded: new Set(), modalFolderId: null };

  function el(id) { return document.getElementById(id); }

  // Build a parent_id -> children[] map from the flat folder list.
  function childrenOf(parentId) {
    return S.folders
      .filter(f => (f.parent_id == null ? null : f.parent_id) === (parentId == null ? null : parentId))
      .sort((a, b) => (a.name || "").localeCompare(b.name || ""));
  }

  // True if `maybeDescId` is `folderId` or a descendant of it (for move guard).
  function isSelfOrDescendant(folderId, maybeDescId) {
    if (maybeDescId == null) return false;
    if (maybeDescId === folderId) return true;
    let cur = S.folders.find(f => f.id === maybeDescId);
    const guard = new Set();
    while (cur && cur.parent_id != null) {
      if (guard.has(cur.id)) break;
      guard.add(cur.id);
      if (cur.parent_id === folderId) return true;
      cur = S.folders.find(f => f.id === cur.parent_id);
    }
    return false;
  }

  // ---- Public: (re)load folders and render the tree --------------------- #
  async function load() {
    try {
      S.folders = await O.call("list_folders");
    } catch (e) {
      S.folders = [];
    }
    render();
  }

  function render() {
    const root = el("chat-folders");
    if (!root) return;
    root.innerHTML = "";

    // "All" + "Unfiled" pseudo-entries.
    root.appendChild(rootEntry("__all__", "All chats", "layers"));
    root.appendChild(rootEntry(null, "Unfiled", "message"));

    const tops = childrenOf(null);
    tops.forEach(f => root.appendChild(folderNode(f, 0)));
  }

  function rootEntry(folderId, label, icon) {
    const active = sameFolder(O.state.activeFolderId, folderId);
    const row = document.createElement("div");
    row.className = "folder-row" + (active ? " active" : "");
    row.style.paddingLeft = "8px";
    const sp = document.createElement("span"); sp.className = "folder-spacer";
    const ic = document.createElement("span"); ic.className = "ic folder-ic"; ic.innerHTML = O.icon(icon, 15);
    const name = document.createElement("span"); name.className = "folder-name"; name.textContent = label;
    row.append(sp, ic, name);
    row.onclick = () => selectFolder(folderId);
    return row;
  }

  function sameFolder(active, entry) {
    // `active` is O.state.activeFolderId ("__all__" | null | int); treat an
    // unset value as "__all__". `entry` is the row's folder id ("__all__"|null|int).
    if (active === undefined) active = "__all__";
    if (entry == null && active == null) return true; // both = unfiled (null)
    return active === entry;
  }

  function folderNode(f, depth) {
    const wrap = document.createElement("div");
    wrap.className = "folder-node";

    const kids = childrenOf(f.id);
    const hasKids = kids.length > 0;
    const isOpen = S.expanded.has(f.id);
    const active = O.state.activeFolderId === f.id;

    const row = document.createElement("div");
    row.className = "folder-row" + (active ? " active" : "");
    row.style.paddingLeft = (8 + depth * 14) + "px";

    // Chevron (or spacer to keep alignment).
    const chev = document.createElement("button");
    chev.className = "folder-chevron";
    if (hasKids) {
      chev.innerHTML = O.icon(isOpen ? "chevron-down" : "chevron-right", 14);
      chev.onclick = (e) => {
        e.stopPropagation();
        if (S.expanded.has(f.id)) S.expanded.delete(f.id); else S.expanded.add(f.id);
        render();
      };
    } else {
      chev.classList.add("invisible");
      chev.innerHTML = O.icon("chevron-right", 14);
    }

    const ic = document.createElement("span");
    ic.className = "ic folder-ic";
    ic.innerHTML = O.icon(isOpen && hasKids ? "folder-open" : "folder", 15);

    const name = document.createElement("span");
    name.className = "folder-name";
    name.textContent = f.name || "Folder";

    const count = document.createElement("span");
    count.className = "folder-count";
    if (f.conv_count) count.textContent = f.conv_count;

    // Per-folder action menu (settings/subfolder/rename/move/delete).
    const menuBtn = document.createElement("button");
    menuBtn.className = "folder-menu-btn";
    menuBtn.title = "Folder actions";
    menuBtn.innerHTML = O.icon("settings", 14);
    menuBtn.onclick = (e) => { e.stopPropagation(); openFolderMenu(f, menuBtn); };

    row.append(chev, ic, name, count, menuBtn);
    row.onclick = () => selectFolder(f.id);
    wrap.appendChild(row);

    if (hasKids && isOpen) {
      const childWrap = document.createElement("div");
      childWrap.className = "folder-children";
      kids.forEach(k => childWrap.appendChild(folderNode(k, depth + 1)));
      wrap.appendChild(childWrap);
    }
    return wrap;
  }

  // ---- Selection -> sets the shared active project ---------------------- #
  function selectFolder(folderId) {
    // folderId: "__all__" (all), null (unfiled), or int (a folder).
    O.state.activeFolderId = folderId;
    render();
    // Re-filter the chat list to this folder and let chat mode react.
    if (O.chat && O.chat.load) O.chat.load();
  }
  O.selectFolder = selectFolder;

  // The folder_id value to persist on NEW conversations: only a real int counts
  // as a project. "__all__" and null both mean "not in a project".
  O.activeFolderIdForNew = function () {
    const a = O.state.activeFolderId;
    return (typeof a === "number") ? a : null;
  };

  // ---- Lightweight popover action menu --------------------------------- #
  let curMenu = null;
  function closeMenu() { if (curMenu) { curMenu.remove(); curMenu = null; } }
  document.addEventListener("click", (e) => {
    if (curMenu && !e.target.closest(".folder-popover")) closeMenu();
  });

  function openFolderMenu(f, anchor) {
    closeMenu();
    const menu = document.createElement("div");
    menu.className = "folder-popover";
    const r = anchor.getBoundingClientRect();
    menu.style.left = Math.min(r.left, window.innerWidth - 210) + "px";
    menu.style.top = (r.bottom + 4) + "px";

    menu.appendChild(menuItem("settings", "Settings & context", () => { closeMenu(); openFolderModal(f.id); }));
    menu.appendChild(menuItem("folder-plus", "New subfolder", async () => {
      closeMenu();
      const name = window.prompt("New subfolder name:");
      if (!name) return;
      await O.call("create_folder", name, f.id);
      S.expanded.add(f.id);
      load();
    }));
    menu.appendChild(menuItem("edit", "Rename", async () => {
      closeMenu();
      const name = window.prompt("Rename folder:", f.name || "");
      if (!name) return;
      await O.call("rename_folder", f.id, name);
      load();
    }));
    menu.appendChild(menuItem("move", "Move to…", () => { closeMenu(); openMovePicker(f); }));
    const del = menuItem("trash", "Delete", async () => {
      closeMenu();
      if (!window.confirm('Delete folder "' + (f.name || "") + '"? Subfolders and their context are removed; chats become unfiled.')) return;
      await O.call("delete_folder", f.id);
      if (O.state.activeFolderId === f.id) selectFolder("__all__");
      else load();
    });
    del.classList.add("danger");
    menu.appendChild(del);

    document.body.appendChild(menu);
    curMenu = menu;
  }

  function menuItem(icon, label, onClick) {
    const b = document.createElement("button");
    b.className = "folder-popover-item";
    b.innerHTML = '<span class="ic">' + O.icon(icon, 15) + "</span><span>" + O.escapeHtml(label) + "</span>";
    b.onclick = onClick;
    return b;
  }

  // ---- Move picker: list of valid destinations ------------------------- #
  function openMovePicker(f, anchor) {
    closeMenu();
    const menu = document.createElement("div");
    menu.className = "folder-popover wide";
    // Center-ish placement near the rail.
    menu.style.left = "16px";
    menu.style.top = "120px";

    const head = document.createElement("div");
    head.className = "folder-popover-head";
    head.textContent = 'Move "' + (f.name || "Folder") + '" to:';
    menu.appendChild(head);

    // Root option.
    if (f.parent_id != null) {
      menu.appendChild(menuItem("layers", "Top level (no parent)", () => doMove(f, null)));
    }
    S.folders.forEach(dest => {
      if (isSelfOrDescendant(f.id, dest.id)) return; // can't move into self/descendant
      if (dest.id === f.parent_id) return;            // already there
      menu.appendChild(menuItem("folder", dest.name || "Folder", () => doMove(f, dest.id)));
    });

    document.body.appendChild(menu);
    curMenu = menu;
  }

  async function doMove(f, parentId) {
    closeMenu();
    const res = await O.call("move_folder", f.id, parentId);
    if (res && res.ok === false) { O.toast(res.error || "Move rejected"); return; }
    if (parentId != null) S.expanded.add(parentId);
    load();
  }

  // ===================== Folder settings modal ========================== #
  async function openFolderModal(folderId) {
    S.modalFolderId = folderId;
    const modal = el("folder-modal");
    const body = el("folder-modal-body");
    const titleEl = el("folder-modal-title");
    if (!modal || !body) return;

    body.innerHTML = '<div class="empty"><span class="spin-inline"></span>Loading…</div>';
    modal.classList.remove("hidden");

    let info, ctx;
    try {
      info = await O.call("get_folder", folderId);
      ctx = await O.call("list_folder_context", folderId);
    } catch (e) {
      body.innerHTML = '<div class="empty">Could not load folder: ' + O.escapeHtml(e.message) + "</div>";
      return;
    }
    const folder = (info && info.folder) || {};
    if (titleEl) titleEl.textContent = folder.name || "Folder";

    body.innerHTML = "";

    // Breadcrumb of ancestors (root-first), if any.
    if (info && info.ancestors && info.ancestors.length) {
      const crumb = document.createElement("div");
      crumb.className = "folder-crumb";
      crumb.textContent = info.ancestors.map(a => a.name).join("  ›  ") + "  ›  " + (folder.name || "");
      body.appendChild(crumb);
    }

    // Instructions textarea.
    body.appendChild(fieldLabel("Custom instructions", "Applied to every chat in this project (and inherited by subfolders)."));
    const insta = document.createElement("textarea");
    insta.className = "pref-textarea";
    insta.id = "folder-instructions";
    insta.rows = 5;
    insta.placeholder = "e.g. This project is about quantum computing. Prefer precise, math-friendly explanations.";
    insta.value = folder.instructions || "";
    body.appendChild(insta);

    // Tone select.
    body.appendChild(fieldLabel("Tone", null));
    const sel = document.createElement("select");
    sel.className = "pref-select";
    sel.id = "folder-tone";
    TONES.forEach(t => {
      const o = document.createElement("option"); o.value = t; o.textContent = TONE_LABEL[t]; sel.appendChild(o);
    });
    sel.value = TONES.includes(folder.tone) ? folder.tone : "default";
    body.appendChild(sel);

    // Save button.
    const saveBar = document.createElement("div");
    saveBar.className = "folder-save-bar";
    const saveBtn = document.createElement("button");
    saveBtn.className = "btn-primary";
    saveBtn.innerHTML = O.icon("check", 16) + "<span>Save instructions & tone</span>";
    saveBtn.onclick = async () => {
      await O.call("set_folder_prefs", folderId, insta.value, sel.value);
      O.toast("Folder preferences saved");
    };
    saveBar.appendChild(saveBtn);
    body.appendChild(saveBar);

    // Context files section.
    const ctxTitle = document.createElement("div");
    ctxTitle.className = "rail-section-title"; ctxTitle.style.marginTop = "18px";
    ctxTitle.textContent = "Project knowledge (context files)";
    body.appendChild(ctxTitle);

    const ctxList = document.createElement("div");
    ctxList.id = "folder-context-list";
    body.appendChild(ctxList);
    renderContextList(ctxList, ctx, folderId);

    const addBtn = document.createElement("button");
    addBtn.className = "newbtn ghost";
    addBtn.style.marginTop = "8px";
    addBtn.innerHTML = O.icon("plus", 16) + "<span>Add context file</span>";
    addBtn.onclick = async () => {
      const path = window.prompt("Full path of a file to add (PDF/DOCX/XLSX/TXT/MD):");
      if (!path) return;
      O.toast("Extracting…");
      const res = await O.call("add_folder_context", folderId, path);
      if (res && res.ok) {
        O.toast("Added: " + res.name + " (" + (res.char_count || 0) + " chars)");
        const fresh = await O.call("list_folder_context", folderId);
        renderContextList(ctxList, fresh, folderId);
      } else {
        O.toast("Failed: " + ((res && res.error) || "unknown error"));
      }
    };
    body.appendChild(addBtn);
  }

  function renderContextList(container, items, folderId) {
    container.innerHTML = "";
    if (!items || !items.length) {
      const e = document.createElement("div"); e.className = "empty"; e.textContent = "No context files yet.";
      container.appendChild(e);
      return;
    }
    items.forEach(it => {
      const row = document.createElement("div");
      row.className = "ctx-item";
      const ic = document.createElement("span"); ic.className = "ic";
      ic.innerHTML = O.icon(ctxIcon(it.kind), 16);
      const info = document.createElement("div"); info.className = "ctx-info";
      const nm = document.createElement("div"); nm.className = "ctx-name"; nm.textContent = it.name || "File";
      const meta = document.createElement("div"); meta.className = "ctx-meta";
      meta.textContent = (it.kind || "file") + " · " + (it.char_count || 0).toLocaleString() + " chars";
      info.append(nm, meta);
      const del = document.createElement("button"); del.className = "icon-btn sm";
      del.innerHTML = O.icon("trash", 15);
      del.onclick = async () => {
        await O.call("delete_folder_context", it.id);
        const fresh = await O.call("list_folder_context", folderId);
        renderContextList(container, fresh, folderId);
      };
      row.append(ic, info, del);
      container.appendChild(row);
    });
  }

  function ctxIcon(kind) {
    if (kind === "xlsx") return "sheet";
    if (kind === "pdf" || kind === "docx") return "file-text";
    return "file";
  }

  function fieldLabel(text, hint) {
    const w = document.createElement("div");
    w.className = "pref-field-label";
    const t = document.createElement("div"); t.className = "pref-label-text"; t.textContent = text;
    w.appendChild(t);
    if (hint) { const h = document.createElement("div"); h.className = "pref-label-hint"; h.textContent = hint; w.appendChild(h); }
    return w;
  }

  function closeModal() {
    const modal = el("folder-modal");
    if (modal) modal.classList.add("hidden");
    // Refresh tree (counts / names may have changed) and chat list.
    load();
  }

  function init() {
    // New top-level folder button.
    const newBtn = el("chat-new-folder");
    if (newBtn) newBtn.onclick = async () => {
      const name = window.prompt("New project / folder name:");
      if (!name) return;
      await O.call("create_folder", name);
      load();
    };
    const close = el("folder-modal-close");
    if (close) close.onclick = closeModal;
    const modal = el("folder-modal");
    if (modal) modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });

    // Default the active project to "All chats" so chat.load shows everything.
    if (O.state.activeFolderId === undefined) O.state.activeFolderId = "__all__";
    return load();
  }

  O.folderTree = { init, load, render, openFolderModal };
})(window.OpenLM);
