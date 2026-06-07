// Hinton — Tauri shell. Spawns the Python harness ("--serve") as a sidecar and
// loads its URL in a native WebView2 window (replaces pywebview/PyInstaller GUI).
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

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
    cmd.env("OPENLM_E4B_MODEL", root.join("models").join("gemma-4-E4B_q4_0-it.gguf"));
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
        .invoke_handler(tauri::generate_handler![backend_url])
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
