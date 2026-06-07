// Hinton — Tauri shell. Spawns the Python harness ("--serve") as a sidecar and
// loads its URL in a native WebView2 window (replaces pywebview/PyInstaller GUI).
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{Read, Write};
use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use tauri::{Manager, State};

struct Backend {
    child: Mutex<Option<Child>>,
    url: Mutex<Option<String>>,
}

/// Returns the backend URL once the sidecar's dev server is accepting
/// connections; null while it is still starting. Polled by ui/loading.html.
#[tauri::command]
fn backend_url(state: State<Backend>) -> Option<String> {
    state.url.lock().unwrap().clone()
}

/// Minimal blocking HTTP POST (stdlib only) used to proxy backend calls from the
/// loading window via IPC, so it never has to fetch cross-origin from the
/// webview (which the WebView2 sandbox blocks: CORS / private-network).
fn http_post(base: &str, path: &str, body: &str) -> Option<String> {
    let addr = base.trim_start_matches("http://").trim_start_matches("https://");
    let mut stream = TcpStream::connect(addr).ok()?;
    let _ = stream.set_read_timeout(Some(Duration::from_secs(5)));
    let req = format!(
        "POST {path} HTTP/1.1\r\nHost: {addr}\r\nContent-Type: application/json\r\n\
         Content-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    );
    stream.write_all(req.as_bytes()).ok()?;
    let mut resp = Vec::new();
    stream.read_to_end(&mut resp).ok()?;
    let text = String::from_utf8_lossy(&resp);
    text.find("\r\n\r\n").map(|i| text[i + 4..].to_string())
}

/// First-run boot/download status as a JSON string, proxied from the backend so
/// the loading window can show real progress without a cross-origin fetch.
#[tauri::command]
fn boot_status(state: State<Backend>) -> Option<String> {
    let url = state.url.lock().unwrap().clone()?;
    http_post(&url, "/api", "{\"method\":\"get_boot_status\",\"args\":[]}")
}

fn free_port() -> u16 {
    std::net::TcpListener::bind("127.0.0.1:0")
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .unwrap_or(8090)
}

/// Locate the project root that contains the Python harness + bundled runtime.
/// In an installed app this is the Tauri resource dir (where `bundle.resources`
/// places `harness/`, `python-embed/`, `bin/`, ...); in dev it's the repo root.
fn repo_root(app: &tauri::AppHandle) -> PathBuf {
    if let Ok(p) = std::env::var("HINTON_ROOT") {
        return PathBuf::from(p);
    }
    // Installed/bundled: resources live under the resource dir.
    if let Ok(res) = app.path().resource_dir() {
        if res.join("harness").join("main.py").exists() {
            return res;
        }
    }
    if let Ok(exe) = std::env::current_exe() {
        // target/{debug,release}/hinton.exe -> ../../../../  == project root
        if let Some(root) = exe.ancestors().nth(5) {
            if root.join("harness").join("main.py").exists() {
                return root.to_path_buf();
            }
        }
        // Bundled layout: model/harness shipped next to the exe under resources.
        if let Some(dir) = exe.parent() {
            if dir.join("harness").join("main.py").exists() {
                return dir.to_path_buf();
            }
        }
    }
    PathBuf::from(r"C:\Users\_maX\openlm")
}

/// The Python interpreter to run the backend with. Prefer the bundled embeddable
/// Python (`python-embed/python.exe`, a sibling of `harness/`) so the app is a
/// self-contained native app with NO system-Python dependency; fall back to a
/// `python` on PATH only if the bundle is missing (e.g. a bare source clone).
fn python_exe(root: &PathBuf) -> PathBuf {
    let bundled = root.join("python-embed").join("python.exe");
    if bundled.exists() {
        bundled
    } else {
        PathBuf::from("python")
    }
}

fn spawn_backend(root: &PathBuf, port: u16) -> std::io::Result<Child> {
    let mut cmd = Command::new(python_exe(root));
    cmd.args(["-m", "harness.main", "--serve", "--port", &port.to_string()]);
    cmd.current_dir(root);
    // The embeddable Python resolves `harness` via its `python312._pth` (which
    // adds `..`); PYTHONPATH is ignored by an embeddable build but set anyway so
    // the system-Python fallback also works.
    cmd.env("PYTHONPATH", root);
    // Run the real model out of the box: portable profile + bundled binaries.
    cmd.env("OPENLM_MODEL_PROFILE", "generic");
    cmd.env("OPENLM_LLAMA_SERVER", root.join("bin").join("llama-server.exe"));
    // Writable data/model dirs. The install dir (resource_dir) is read-only, so
    // when the weights aren't shipped next to the app we point at
    // %LOCALAPPDATA%\OpenLM — that's where the backend downloads the model on
    // first run (with progress shown in the loading window). In dev / when the
    // model is already beside the app, use that so we don't re-download.
    let e4b = root.join("models").join("gemma-4-E4B_q4_0-it.gguf");
    let (data_dir, models_dir) = if e4b.exists() {
        (root.join("data"), root.join("models"))
    } else {
        let base = std::env::var("LOCALAPPDATA")
            .or_else(|_| std::env::var("USERPROFILE"))
            .unwrap_or_default();
        let u = PathBuf::from(base).join("OpenLM");
        (u.join("data"), u.join("models"))
    };
    cmd.env("OPENLM_DATA_DIR", &data_dir);
    cmd.env("OPENLM_MODELS_DIR", &models_dir);
    // Capture the sidecar's stdout/stderr so startup issues are diagnosable
    // (otherwise CREATE_NO_WINDOW discards them).
    let _ = std::fs::create_dir_all(&data_dir);
    if let Ok(f) = std::fs::File::create(data_dir.join("backend.log")) {
        if let Ok(f2) = f.try_clone() {
            cmd.stdout(std::process::Stdio::from(f));
            cmd.stderr(std::process::Stdio::from(f2));
        }
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }
    cmd.spawn()
}

fn main() {
    tauri::Builder::default()
        .manage(Backend {
            child: Mutex::new(None),
            url: Mutex::new(None),
        })
        .invoke_handler(tauri::generate_handler![backend_url, boot_status])
        .setup(|app| {
            let root = repo_root(app.handle());
            let port = free_port();
            let url = format!("http://127.0.0.1:{}", port);

            match spawn_backend(&root, port) {
                Ok(child) => {
                    app.state::<Backend>().child.lock().unwrap().replace(child);
                }
                Err(e) => {
                    eprintln!("failed to start Hinton backend: {e}");
                }
            }

            // Publish the URL once the dev server accepts connections.
            let handle = app.handle().clone();
            thread::spawn(move || {
                let addr = format!("127.0.0.1:{}", port);
                for _ in 0..1500 {
                    if let Ok(sa) = addr.parse() {
                        if TcpStream::connect_timeout(&sa, Duration::from_millis(300)).is_ok() {
                            *handle.state::<Backend>().url.lock().unwrap() = Some(url.clone());
                            return;
                        }
                    }
                    thread::sleep(Duration::from_millis(400));
                }
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(state) = window.app_handle().try_state::<Backend>() {
                    if let Some(mut child) = state.child.lock().unwrap().take() {
                        let _ = child.kill();
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Hinton");
}
