/* Hinton front-end orchestrator: bridge, shared UI helpers, boot.
   (JS namespace stays window.OpenLM per the integration contract; only the
   user-facing brand is "Hinton".) */
window.OpenLM = window.OpenLM || {};
(function (O) {
  // activeFolderId is the shared "active project": "__all__" = all chats,
  // null = unfiled, or an int = a specific folder. New conversations in every
  // mode adopt the int value so project context is shared across views.
  O.state = { mode: "chat", status: {}, thinking: false, activeFolderId: "__all__" };

  // ---- Bridge: pywebview if present, else dev-server /api -------------- #
  O.call = async function (method, ...args) {
    const api = window.pywebview && window.pywebview.api;
    if (api && typeof api[method] === "function") {
      return await api[method](...args);
    }
    const r = await fetch("/api", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ method, args }),
    });
    const data = await r.json();
    if (data.error) throw new Error(data.error);
    return data.result;
  };

  // ---- Small utilities ------------------------------------------------ #
  O.toast = function (msg, ms = 2600) {
    const t = document.getElementById("toast");
    t.textContent = msg; t.classList.remove("hidden");
    clearTimeout(O._toastT);
    O._toastT = setTimeout(() => t.classList.add("hidden"), ms);
  };

  O.fmtTime = function (ts) {
    if (!ts) return "";
    const d = new Date(ts * 1000), now = Date.now() / 1000;
    const diff = now - ts;
    if (diff < 60) return "just now";
    if (diff < 3600) { const m = Math.floor(diff / 60); return m + (m === 1 ? " min ago" : " mins ago"); }
    if (diff < 86400) { const h = Math.floor(diff / 3600); return h + (h === 1 ? " hr ago" : " hrs ago"); }
    return `${d.getMonth() + 1}/${d.getDate()}`;
  };

  O.autoGrow = function (ta) {
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 200) + "px";
  };

  // ---- Theme (light/dark) --------------------------------------------- #
  O.applyTheme = function (theme) {
    const light = theme === "light";
    document.body.classList.toggle("theme-light", light);
    O.state.theme = light ? "light" : "dark";
    const btn = document.getElementById("theme-btn");
    if (btn) {
      const span = btn.querySelector("[data-icon], .ic");
      const name = light ? "sun" : "moon";
      if (span) { span.setAttribute("data-icon", name); span.innerHTML = O.icon(name, 18); }
      btn.title = light ? "Switch to dark mode" : "Switch to light mode";
    }
  };

  O.bindComposer = function (textarea, sendBtn, onSend) {
    O.autoGrow(textarea);
    textarea.addEventListener("input", () => O.autoGrow(textarea));
    textarea.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSend(); }
    });
    sendBtn.addEventListener("click", onSend);
  };

  // ---- Send <-> Stop toggle (Feature 1) ------------------------------- #
  // While a generation is in flight, a composer's SEND button morphs into a
  // STOP button whose click signals the backend to abort the connection
  // (llama-server stops the slot on client disconnect). The UI still batch-
  // renders; this only flips the button's icon/handler/state. `iconSize` keeps
  // the arrow/stop glyph consistent with the original send button.
  //
  //   const done = O.beginSend("chat-send");  // returns a revert function
  //   try { ...await send... } finally { done(); }
  O._sendState = O._sendState || {};
  O.beginSend = function (sendBtnId, iconSize) {
    const btn = document.getElementById(sendBtnId);
    if (!btn) return function () {};
    // Guard against double-begin on the same button.
    if (O._sendState[sendBtnId]) return O._sendState[sendBtnId].revert;

    const size = iconSize || (btn.classList.contains("sm") ? 16 : 18);
    const origHTML = btn.innerHTML;
    const origTitle = btn.getAttribute("title") || "";

    function stopClick(e) {
      e.preventDefault();
      e.stopPropagation();
      btn.disabled = true;             // visual feedback; reverts on completion
      O.call("stop_generation").catch(function () {});
    }

    btn.classList.add("is-stop");
    btn.disabled = false;
    btn.setAttribute("title", "Stop");
    btn.innerHTML = O.icon("stop", size);
    btn.addEventListener("click", stopClick, true); // capture: pre-empt onSend

    let reverted = false;
    function revert() {
      if (reverted) return;
      reverted = true;
      btn.removeEventListener("click", stopClick, true);
      btn.classList.remove("is-stop");
      btn.disabled = false;
      if (origTitle) btn.setAttribute("title", origTitle);
      btn.innerHTML = origHTML;
      delete O._sendState[sendBtnId];
    }
    O._sendState[sendBtnId] = { revert: revert };
    return revert;
  };

  // ---- Shared message rendering --------------------------------------- #
  O.appendMessage = function (thread, msg) {
    const wrap = document.createElement("div");
    wrap.className = "msg " + (msg.role === "user" ? "user" : "assistant");

    if (msg.role === "user") {
      const bubble = document.createElement("div");
      bubble.className = "bubble";
      bubble.textContent = msg.content || "";
      wrap.appendChild(bubble);
    } else {
      const who = document.createElement("div");
      who.className = "who";
      const av = document.createElement("div"); av.className = "avatar";
      const name = document.createElement("span"); name.className = "name"; name.textContent = "Hinton";
      who.append(av, name);
      const model = msg.model || (msg.meta && msg.meta.model);
      if (model) {
        const t = document.createElement("span"); t.className = "mtag";
        t.textContent = model === "12b" ? "12B" : "E4B"; who.appendChild(t);
      }
      if (msg.meta && msg.meta.escalated) {
        const e = document.createElement("span"); e.className = "mtag";
        e.textContent = "↑ escalated"; who.appendChild(e);
      }
      wrap.appendChild(who);

      const body = document.createElement("div"); body.className = "body";
      if (msg.reasoning) {
        const d = document.createElement("details"); d.className = "reasoning";
        const s = document.createElement("summary"); s.textContent = "Reasoning";
        const rb = document.createElement("div"); rb.className = "rbody"; rb.textContent = msg.reasoning;
        d.append(s, rb); body.appendChild(d);
      }
      const mdEl = document.createElement("div");
      O.renderMarkdown(mdEl, msg.content || "");
      // In Chat, add an "Open in Code" affordance to each fenced code block.
      if (O.state.mode === "chat") O.decorateCodeBlocks(mdEl);
      body.appendChild(mdEl);
      wrap.appendChild(body);

      if (msg.content) {
        const act = document.createElement("div"); act.className = "msg-actions";
        const copy = document.createElement("button");
        const setLabel = (icon, txt) => { copy.innerHTML = O.icon(icon, 14) + "<span>" + txt + "</span>"; };
        setLabel("copy", "Copy");
        copy.onclick = () => {
          if (navigator.clipboard) navigator.clipboard.writeText(msg.content);
          setLabel("check", "Copied");
          setTimeout(() => setLabel("copy", "Copy"), 1500);
        };
        act.appendChild(copy); wrap.appendChild(act);
      }
    }
    thread.appendChild(wrap);
    const sc = thread.closest(".thread-scroll") || thread;
    sc.scrollTop = sc.scrollHeight;
    return wrap;
  };

  // ---- Cross-view code handoff ---------------------------------------- #
  // Map highlight.js / fence language hints to the Code mode <select> values.
  const CODE_LANGS = ["python", "javascript", "c", "cpp", "html"];
  function normalizeLang(hint) {
    const h = (hint || "").toLowerCase();
    if (h === "py" || h === "python" || h === "python3") return "python";
    if (h === "js" || h === "javascript" || h === "node" || h === "jsx") return "javascript";
    if (h === "c") return "c";
    if (h === "cpp" || h === "c++" || h === "cc" || h === "cxx") return "cpp";
    if (h === "html" || h === "xml" || h === "htm") return "html";
    return CODE_LANGS.includes(h) ? h : null;
  }

  // Add an "Open in Code" button under each <pre><code> block in a rendered
  // markdown element. Language is inferred from the hljs class when present.
  O.decorateCodeBlocks = function (mdEl) {
    mdEl.querySelectorAll("pre").forEach((pre) => {
      const codeEl = pre.querySelector("code");
      if (!codeEl) return;
      const text = codeEl.textContent || "";
      if (!text.trim()) return;
      // Detect language from a "language-xxx" class on the <code>, else null.
      let lang = null;
      (codeEl.className || "").split(/\s+/).forEach((c) => {
        if (c.indexOf("language-") === 0) lang = normalizeLang(c.slice(9));
      });
      const bar = document.createElement("div");
      bar.className = "code-block-actions";
      const btn = document.createElement("button");
      btn.className = "code-open-btn";
      btn.innerHTML = O.icon("code", 13) + "<span>Open in Code</span>";
      btn.onclick = () => O.sendToCode(text, lang);
      bar.appendChild(btn);
      // Place the action bar right after the <pre>.
      if (pre.parentNode) pre.parentNode.insertBefore(bar, pre.nextSibling);
    });
  };

  // Switch to Code mode and load the editor with `code` (+ optional language).
  O.sendToCode = function (code, lang) {
    O.switchMode("code");
    if (O.code && O.code.loadEditor) O.code.loadEditor(code, lang);
    O.toast("Loaded into Code editor");
  };

  // Switch to Chat mode and prefill the composer with `text`.
  O.sendToChat = function (text) {
    O.switchMode("chat");
    const inp = document.getElementById("chat-input");
    if (inp) {
      inp.value = text || "";
      O.autoGrow(inp);
      inp.focus();
    }
  };

  // ---- Live generation events (pushed from the bridge) ---------------- #
  O.curStatusEl = null;
  O.setStatus = function (html) {
    if (O.curStatusEl) O.curStatusEl.innerHTML = html;
  };
  window.openlmEvent = function (ev) {
    if (!ev || !O.curStatusEl) return;
    const t = ev.type;
    if (t === "generating") {
      O.setStatus('<span class="spin-inline"></span>Generating… · ' +
        ((ev.model || "").toUpperCase()) + (ev.thinking ? " · thinking" : ""));
    } else if (t === "tool_call") {
      O.setStatus('<span class="spin-inline"></span>Running tool: ' + ev.name);
    } else if (t === "escalate") {
      O.toast("Escalating to 12B");
      O.setStatus('<span class="spin-inline"></span>Loading 12B…');
    } else if (t === "descalate") {
      O.toast("Back to E4B");
    } else if (t === "compact") {
      O.setStatus('<span class="spin-inline"></span>Compacting context…');
    }
  };

  // ---- Model status pill ---------------------------------------------- #
  function updatePill(s) {
    O.state.status = s || {};
    const pill = document.getElementById("model-pill");
    const label = document.getElementById("model-label");
    if (!s || !s.active) { label.textContent = "Loading…"; pill.classList.add("is-busy"); return; }
    let txt = s.label || "E4B";
    if (s.active === "12b" && s.thinking) txt = "12B · thinking";
    if (s.mock) txt += " · mock";
    label.textContent = txt;
    pill.classList.toggle("is-12b", s.active === "12b");
    pill.classList.toggle("is-busy", !!s.busy);
  }
  O.refreshStatus = async function () {
    try { updatePill(await O.call("get_status")); } catch (e) {}
  };

  // ---- Tabs ----------------------------------------------------------- #
  function switchMode(mode) {
    O.state.mode = mode;
    document.querySelectorAll(".tab").forEach(t =>
      t.classList.toggle("active", t.dataset.mode === mode));
    document.querySelectorAll(".mode").forEach(m =>
      m.classList.toggle("active", m.id === "mode-" + mode));
    if (O.initSplit) O.initSplit(mode);
    const ctl = O[mode];
    if (ctl && ctl.onShow) ctl.onShow();
  }
  O.switchMode = switchMode;

  // ---- Settings ------------------------------------------------------- #
  async function openSettings() {
    const body = document.getElementById("settings-body");
    const s = await O.call("get_settings");
    const mem = await O.call("list_memory");
    const gen = await O.call("list_generated");
    let prefs = { about: "", style: "", tone: "default" };
    try { prefs = await O.call("get_preferences"); } catch (e) {}
    body.innerHTML = "";

    // ---- Personalization (global preferences) ---- #
    const persTitle = document.createElement("div");
    persTitle.className = "rail-section-title";
    persTitle.textContent = "Personalization";
    body.appendChild(persTitle);

    const aboutWrap = prefField("About you", "What should Hinton know about you? (background, goals, preferences)");
    const aboutTa = document.createElement("textarea");
    aboutTa.className = "pref-textarea"; aboutTa.rows = 3;
    aboutTa.placeholder = "e.g. I'm an intermediate developer studying for a security career.";
    aboutTa.value = (prefs && prefs.about) || "";
    aboutWrap.appendChild(aboutTa); body.appendChild(aboutWrap);

    const styleWrap = prefField("How should Hinton respond", "Custom response style applied to every chat.");
    const styleTa = document.createElement("textarea");
    styleTa.className = "pref-textarea"; styleTa.rows = 3;
    styleTa.placeholder = "e.g. Use concrete examples and avoid jargon unless I ask.";
    styleTa.value = (prefs && prefs.style) || "";
    styleWrap.appendChild(styleTa); body.appendChild(styleWrap);

    const toneWrap = prefField("Tone", null);
    const toneSel = document.createElement("select");
    toneSel.className = "pref-select";
    const TONES = ["default", "friendly", "formal", "concise", "detailed", "socratic", "encouraging"];
    const TONE_LABEL = { default: "Default", friendly: "Friendly", formal: "Formal", concise: "Concise", detailed: "Detailed", socratic: "Socratic", encouraging: "Encouraging" };
    TONES.forEach(t => { const o = document.createElement("option"); o.value = t; o.textContent = TONE_LABEL[t]; toneSel.appendChild(o); });
    toneSel.value = TONES.includes(prefs && prefs.tone) ? prefs.tone : "default";
    toneWrap.appendChild(toneSel); body.appendChild(toneWrap);

    const prefSaveBar = document.createElement("div");
    prefSaveBar.className = "folder-save-bar";
    const prefSave = document.createElement("button");
    prefSave.className = "btn-primary";
    prefSave.innerHTML = O.icon("check", 16) + "<span>Save preferences</span>";
    prefSave.onclick = async () => {
      await O.call("set_preferences", aboutTa.value, styleTa.value, toneSel.value);
      O.toast("Preferences saved");
    };
    prefSaveBar.appendChild(prefSave); body.appendChild(prefSaveBar);

    const sep = document.createElement("div");
    sep.className = "rail-section-title"; sep.style.marginTop = "18px";
    sep.textContent = "App";
    body.appendChild(sep);

    body.appendChild(toggleRow("Default thinking mode", "default_thinking", s.default_thinking, async (v) => {
      await O.call("save_settings", { default_thinking: v });
    }));
    body.appendChild(toggleRow("Image generation plugin", "image_gen_enabled", s.image_gen_enabled, async (v) => {
      await O.call("save_settings", { image_gen_enabled: v });
      O.toast("Applies after restart");
    }));

    const memTitle = document.createElement("div");
    memTitle.className = "rail-section-title"; memTitle.style.marginTop = "16px";
    memTitle.textContent = "Memory (persists across sessions)";
    body.appendChild(memTitle);
    if (!mem.length) {
      const e = document.createElement("div"); e.className = "empty"; e.textContent = "No saved memory yet.";
      body.appendChild(e);
    }
    mem.forEach(m => {
      const row = document.createElement("div"); row.className = "mem-item";
      const span = document.createElement("span"); span.textContent = m.key + ": " + m.value;
      const del = document.createElement("button"); del.className = "icon-btn sm";
      del.innerHTML = O.icon("trash", 15);
      del.onclick = async () => { await O.call("delete_memory", m.key); openSettings(); };
      row.appendChild(span); row.appendChild(del); body.appendChild(row);
    });

    const genTitle = document.createElement("div");
    genTitle.className = "rail-section-title"; genTitle.style.marginTop = "16px";
    genTitle.textContent = "Generated files";
    body.appendChild(genTitle);
    if (!gen.length) {
      const e = document.createElement("div"); e.className = "empty"; e.textContent = "Nothing yet.";
      body.appendChild(e);
    }
    gen.forEach(g => {
      const row = document.createElement("div"); row.className = "mem-item";
      const a = document.createElement("a"); a.href = "#"; a.textContent = g.name;
      a.onclick = (e) => { e.preventDefault(); O.call("open_path", g.path); };
      const sz = document.createElement("span"); sz.style.color = "var(--on-variant)";
      sz.textContent = Math.round(g.size / 1024) + " KB";
      row.appendChild(a); row.appendChild(sz); body.appendChild(row);
    });

    document.getElementById("settings-modal").classList.remove("hidden");
  }
  function toggleRow(label, key, val, onChange) {
    const row = document.createElement("div"); row.className = "setting-row";
    const l = document.createElement("label"); l.textContent = label;
    const cb = document.createElement("input"); cb.type = "checkbox"; cb.checked = !!val;
    cb.onchange = () => onChange(cb.checked);
    row.appendChild(l); row.appendChild(cb); return row;
  }
  // Labelled field wrapper for the personalization textareas / selects.
  function prefField(label, hint) {
    const w = document.createElement("div"); w.className = "pref-field";
    const lbl = document.createElement("div"); lbl.className = "pref-field-label";
    const t = document.createElement("div"); t.className = "pref-label-text"; t.textContent = label;
    lbl.appendChild(t);
    if (hint) { const h = document.createElement("div"); h.className = "pref-label-hint"; h.textContent = hint; lbl.appendChild(h); }
    w.appendChild(lbl);
    return w;
  }

  // ---- In-app update banner (Feature 2, spec §23.3) ------------------- #
  // Build a dismissible banner directly under the top bar announcing a new
  // release. Styled with the theme CSS vars so it reads in light and dark.
  O.showUpdateBanner = function (info) {
    if (document.getElementById("update-banner")) return; // idempotent
    const topbar = document.getElementById("topbar");
    if (!topbar || !topbar.parentNode) return;

    const latest = (info && info.latest) || "";
    const url = (info && info.url) || "";
    const notes = (info && info.notes) || "";

    const bar = document.createElement("div");
    bar.id = "update-banner";
    bar.className = "update-banner";
    bar.setAttribute("role", "status");

    const dot = document.createElement("span");
    dot.className = "update-banner-dot";

    const msg = document.createElement("span");
    msg.className = "update-banner-msg";
    msg.textContent = "Hinton " + latest + " is available";
    if (notes) msg.title = notes;

    const dl = document.createElement("button");
    dl.className = "update-banner-dl";
    dl.innerHTML = O.icon("download", 15) + "<span>Download</span>";
    dl.onclick = function () {
      if (url) O.call("open_path", url).catch(function () {});
    };

    const x = document.createElement("button");
    x.className = "update-banner-x icon-btn sm";
    x.title = "Dismiss";
    x.innerHTML = O.icon("x", 16);
    x.onclick = function () { bar.remove(); };

    bar.append(dot, msg, dl, x);
    // Insert immediately after the top bar.
    topbar.parentNode.insertBefore(bar, topbar.nextSibling);
  };
  O.checkUpdate = async function () {
    try {
      const info = await O.call("check_update");
      if (info && info.update_available) O.showUpdateBanner(info);
    } catch (e) { /* never block boot on update check */ }
  };

  // ---- Boot ----------------------------------------------------------- #
  O.start = async function () {
    // Apply the saved theme BEFORE icons hydrate / overlay hides (no flash).
    let theme = "dark";
    try { const s = await O.call("get_settings"); theme = (s && s.theme) === "light" ? "light" : "dark"; } catch (e) {}
    O.applyTheme(theme);

    // Replace all static [data-icon] placeholders with SVG.
    if (O.hydrateIcons) O.hydrateIcons(document);

    // Theme toggle (sun/moon)
    const themeBtn = document.getElementById("theme-btn");
    if (themeBtn) themeBtn.addEventListener("click", async () => {
      const next = O.state.theme === "light" ? "dark" : "light";
      O.applyTheme(next);
      try { await O.call("save_settings", { theme: next }); } catch (e) {}
    });

    // Tabs
    document.querySelectorAll(".tab").forEach(t =>
      t.addEventListener("click", () => switchMode(t.dataset.mode)));
    // Collapsible panels (artifact panel etc.)
    document.querySelectorAll("[data-collapse]").forEach(btn =>
      btn.addEventListener("click", () => {
        const p = document.getElementById(btn.dataset.collapse);
        if (p) p.classList.toggle("collapsed");
      }));
    // Model pill toggles escalate/descalate
    document.getElementById("model-pill").addEventListener("click", async () => {
      const s = O.state.status;
      const target = s.active === "12b" ? "e4b" : "12b";
      O.toast(target === "12b" ? "Switching to 12B…" : "Switching to E4B…");
      try { updatePill(await O.call("set_model", target)); } catch (e) { O.toast("Switch failed: " + e.message); }
    });
    // Settings
    document.getElementById("settings-btn").addEventListener("click", openSettings);
    document.getElementById("settings-close").addEventListener("click", () =>
      document.getElementById("settings-modal").classList.add("hidden"));

    if (O.initSplit) O.initSplit("chat");
    // Init the projects / folder tree before the chat list so the active
    // project filter is established when chat.load() first runs.
    if (O.folderTree && O.folderTree.init) { try { await O.folderTree.init(); } catch (e) { console.error("folderTree", e); } }
    // Init mode controllers
    for (const m of ["chat", "notebook", "code"]) {
      if (O[m] && O[m].init) { try { await O[m].init(); } catch (e) { console.error(m, e); } }
    }

    await O.refreshStatus();
    setInterval(O.refreshStatus, 3000);

    // Hide loading overlay once everything is wired.
    setTimeout(() => document.getElementById("loading").classList.add("hidden"), 250);

    // Check for an available update and show a dismissible banner (non-blocking).
    O.checkUpdate();
  };
})(window.OpenLM);
