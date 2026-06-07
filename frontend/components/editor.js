/* Code editor + sandboxed runners (spec §18). */
window.OpenLM = window.OpenLM || {};
(function (O) {
  const MODE = {
    python: "python", javascript: "javascript",
    c: "text/x-csrc", cpp: "text/x-c++src", html: "htmlmixed",
  };
  let pyodidePromise = null;

  function create(textarea, lang) {
    const cm = window.CodeMirror.fromTextArea(textarea, {
      mode: MODE[lang] || "python",
      theme: "material-darker",
      lineNumbers: true,
      indentUnit: 4,
      tabSize: 4,
      lineWrapping: true,
    });
    cm.setSize("100%", "100%");
    return cm;
  }

  function setMode(cm, lang) { cm.setOption("mode", MODE[lang] || "python"); }

  function appendOut(out, text, cls) {
    const span = document.createElement("span");
    if (cls) span.className = cls;
    span.textContent = text;
    out.appendChild(span);
    out.scrollTop = out.scrollHeight;
  }

  async function getPyodide(out) {
    if (pyodidePromise) return pyodidePromise;
    appendOut(out, "Loading Pyodide… (first time only, requires internet)\n");
    pyodidePromise = (async () => {
      if (!window.loadPyodide) {
        await new Promise((res, rej) => {
          const s = document.createElement("script");
          s.src = "https://cdn.jsdelivr.net/pyodide/v0.26.2/full/pyodide.js";
          s.onload = res; s.onerror = () => rej(new Error("Failed to load Pyodide"));
          document.head.appendChild(s);
        });
      }
      return await window.loadPyodide({ indexURL: "https://cdn.jsdelivr.net/pyodide/v0.26.2/full/" });
    })();
    return pyodidePromise;
  }

  async function runPython(code, out) {
    out.innerHTML = "";
    let py;
    try { py = await getPyodide(out); }
    catch (e) { appendOut(out, "Error: " + e.message + "\n", "err"); return; }
    py.setStdout({ batched: (s) => appendOut(out, s + "\n") });
    py.setStderr({ batched: (s) => appendOut(out, s + "\n", "err") });
    try {
      await py.loadPackagesFromImports(code);
      await py.runPythonAsync(code);
      renderMplFigures(py, out);
    } catch (e) {
      appendOut(out, String(e.message || e) + "\n", "err");
    }
  }

  function renderMplFigures(py, out) {
    try {
      const has = py.runPython("'matplotlib.pyplot' in __import__('sys').modules");
      if (!has) return;
      py.runPython(`
import io, base64
import matplotlib.pyplot as _plt
_openlm_imgs = []
for _n in _plt.get_fignums():
    _f = _plt.figure(_n); _b = io.BytesIO()
    _f.savefig(_b, format='png', bbox_inches='tight', dpi=110)
    _openlm_imgs.append(base64.b64encode(_b.getvalue()).decode())
_plt.close('all')
`);
      const imgs = py.globals.get("_openlm_imgs").toJs();
      imgs.forEach((b64) => {
        const img = document.createElement("img");
        img.src = "data:image/png;base64," + b64;
        out.appendChild(img);
      });
    } catch (e) { /* no figures */ }
  }

  // JS/HTML run inside a sandboxed (null-origin, no allow-same-origin) iframe.
  // Injecting user code into srcdoc IS the sandbox mechanism (spec §18.2): the
  // frame cannot touch the parent DOM, cookies, or storage; results return only
  // via postMessage.
  function runSandbox(code, out, asHtml) {
    out.innerHTML = "";
    const iframe = document.createElement("iframe");
    iframe.sandbox = "allow-scripts";
    if (asHtml) {
      iframe.srcdoc = code;
    } else {
      const pre = document.createElement("pre");
      out.appendChild(pre);
      const onMsg = (e) => {
        if (e.source !== iframe.contentWindow) return;
        const d = e.data || {};
        appendOut(pre, d.m + "\n", d.t === "err" ? "err" : null);
      };
      window.addEventListener("message", onMsg);
      iframe.style.display = "none";
      iframe.srcdoc =
        "<script>(function(){" +
        "var send=function(t,a){parent.postMessage({t:t,m:a.map(function(x){return (typeof x==='object')?JSON.stringify(x):String(x)}).join(' ')},'*')};" +
        "console.log=function(){send('log',[].slice.call(arguments))};" +
        "console.error=function(){send('err',[].slice.call(arguments))};" +
        "window.onerror=function(m){send('err',[m])};" +
        "try{\n" + code + "\n}catch(e){send('err',[String(e)])}" +
        "})();<\/script>";
    }
    out.appendChild(iframe);
  }

  async function runC(code, out, isCpp) {
    out.innerHTML = "";
    appendOut(out, "Compiling and running…\n");
    try {
      const res = await O.call(isCpp ? "run_cpp" : "run_c", code);
      out.innerHTML = "";
      appendOut(out, res);
    } catch (e) {
      out.innerHTML = "";
      appendOut(out, "Error: " + e.message + "\n", "err");
    }
  }

  O.editor = {
    create, setMode,
    async run(lang, code, out) {
      if (lang === "python") return runPython(code, out);
      if (lang === "javascript") return runSandbox(code, out, false);
      if (lang === "html") return runSandbox(code, out, true);
      if (lang === "c") return runC(code, out, false);
      if (lang === "cpp") return runC(code, out, true);
      appendOut(out, "Unsupported language: " + lang, "err");
    },
  };
})(window.OpenLM);
