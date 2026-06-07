/* Code mode controller (spec §8.3). */
window.OpenLM = window.OpenLM || {};
(function (O) {
  const S = { convId: null, cm: null, lang: "python" };
  const SAMPLES = {
    python: "import matplotlib.pyplot as plt\nimport numpy as np\n\nx = np.linspace(0, 2*np.pi, 200)\nplt.plot(x, np.sin(x))\nplt.title('sin(x)')\nplt.show()\nprint('done')",
    javascript: "for (let i = 1; i <= 5; i++) {\n  console.log('count', i);\n}",
    c: '#include <stdio.h>\nint main(){ printf("Hello, Hinton!\\n"); return 0; }',
    cpp: '#include <iostream>\nint main(){ std::cout << "Hello, Hinton!" << std::endl; }',
    html: "<h1 style='font-family:sans-serif'>Hello, Hinton</h1>\n<button onclick=\"document.body.style.background='#7c8cff'\">Change color</button>",
  };
  const EXT = { python: "py", javascript: "js", c: "c", cpp: "cpp", html: "html" };

  function el(id) { return document.getElementById(id); }

  async function load() {
    const items = await O.call("list_conversations", "code");
    const list = el("code-list"); list.innerHTML = "";
    items.forEach(c => {
      const it = document.createElement("div");
      it.className = "list-item" + (c.id === S.convId ? " active" : "");
      const t = document.createElement("div"); t.className = "title"; t.textContent = c.title || "New session";
      const m = document.createElement("div"); m.className = "meta"; m.textContent = O.fmtTime(c.updated_at);
      const del = document.createElement("button"); del.className = "del"; del.innerHTML = O.icon("trash", 15);
      del.onclick = async (e) => { e.stopPropagation(); await O.call("delete_conversation", c.id); if (S.convId === c.id) { S.convId = null; el("code-thread").innerHTML = ""; } load(); };
      it.onclick = () => open(c.id);
      it.append(t, m, del); list.appendChild(it);
    });
  }

  async function open(convId) {
    S.convId = convId;
    const { messages } = await O.call("get_conversation", convId);
    const thread = el("code-thread"); thread.innerHTML = "";
    messages.filter(m => m.role === "user" || m.role === "assistant")
      .forEach(m => O.appendMessage(thread, m));
    load();
  }

  async function ensureConv() {
    if (S.convId) return S.convId;
    // Code sessions inherit the shared active project (folder) too.
    const folderId = O.activeFolderIdForNew ? O.activeFolderIdForNew() : null;
    const c = await O.call("new_conversation", "code", "New session", null, folderId);
    S.convId = c.id; return c.id;
  }

  function extractCode(text) {
    const m = (text || "").match(/```[a-zA-Z+]*\n([\s\S]*?)```/);
    return m ? m[1].trim() : null;
  }

  async function send() {
    const input = el("code-input");
    const text = input.value.trim();
    if (!text) return;
    const convId = await ensureConv();
    const thread = el("code-thread");
    O.appendMessage(thread, { role: "user", content: text });
    input.value = ""; O.autoGrow(input);
    O.curStatusEl = el("code-status");
    O.setStatus('<span class="spin-inline"></span>Generating…');
    const revertSend = O.beginSend("code-send");
    const stopPoll = O.beginProgressPoll();
    try {
      const res = await O.call("send_message", convId, text, "code", false);
      O.appendMessage(thread, res.message);
      if (res.stopped) O.toast("Stopped");
      const code = extractCode(res.message.content);
      if (code && S.cm) S.cm.setValue(code);
    } catch (e) {
      O.appendMessage(thread, { role: "assistant", content: "Error: " + e.message });
    } finally {
      stopPoll();
      O.setStatus(""); revertSend();
      O.refreshStatus(); load();
    }
  }

  function ensureEditor() {
    if (S.cm) { S.cm.refresh(); return; }
    const ta = el("code-editor");
    ta.value = SAMPLES[S.lang];
    S.cm = O.editor.create(ta, S.lang);
  }

  // Cross-view handoff target: load `code` (+ optional language) into the
  // editor. Called by O.sendToCode after switching to Code mode.
  function loadEditor(code, lang) {
    ensureEditor();
    if (lang && SAMPLES.hasOwnProperty(lang)) {
      S.lang = lang;
      const sel = el("code-lang");
      if (sel) sel.value = lang;
      if (S.cm) O.editor.setMode(S.cm, lang);
    }
    if (S.cm) {
      S.cm.setValue(code || "");
      S.cm.refresh();
    }
  }

  function run() {
    if (!S.cm) return;
    O.editor.run(S.lang, S.cm.getValue(), el("code-output"));
  }

  function save() {
    if (!S.cm) return;
    const blob = new Blob([S.cm.getValue()], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "hinton_code." + (EXT[S.lang] || "txt");
    a.click(); URL.revokeObjectURL(a.href);
  }

  function init() {
    O.bindComposer(el("code-input"), el("code-send"), send);
    el("code-run").onclick = run;
    el("code-save").onclick = save;
    el("code-lang").onchange = (e) => {
      S.lang = e.target.value;
      if (S.cm) {
        O.editor.setMode(S.cm, S.lang);
        if (!S.cm.getValue().trim()) S.cm.setValue(SAMPLES[S.lang] || "");
      }
    };
    document.querySelector('[data-new="code"]').onclick = async () => {
      const folderId = O.activeFolderIdForNew ? O.activeFolderIdForNew() : null;
      const c = await O.call("new_conversation", "code", "New session", null, folderId);
      S.convId = c.id; el("code-thread").innerHTML = ""; load();
    };
    const discuss = el("code-discuss");
    if (discuss) discuss.onclick = () => {
      ensureEditor();
      const code = S.cm ? S.cm.getValue() : "";
      if (!code.trim()) { O.toast("Editor is empty"); return; }
      if (O.sendToChat) O.sendToChat("Let's discuss this " + S.lang + " code:\n\n```" + S.lang + "\n" + code + "\n```\n\n");
    };
    return load();
  }

  O.code = { init, loadEditor, onShow() { O.curStatusEl = el("code-status"); ensureEditor(); } };
})(window.OpenLM);
