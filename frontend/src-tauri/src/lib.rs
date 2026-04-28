use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandEvent;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            spawn_python_server(app.handle());
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running dialekt");
}

/// Compile-time signal that this build was produced with a Developer ID
/// certificate (CI release pipeline sets APPLE_SIGNING_IDENTITY before
/// invoking cargo). The Python sidecar reads `DIALEKT_SIGNED` to decide
/// whether to use the macOS Keychain (signed → stable Designated
/// Requirement → ACL persists across launches) or the encrypted-file
/// fallback (unsigned local builds — Keychain ACL is hash-pinned and
/// breaks on every PyInstaller rebuild).
const SIGNED_BUILD: &str = match option_env!("APPLE_SIGNING_IDENTITY") {
    Some(_) => "1",
    None => "0",
};

/// Spawn the bundled Python backend sidecar.
/// Fails gracefully in dev mode (sidecar not present — start server.py manually).
fn spawn_python_server(app: &tauri::AppHandle) {
    let shell = app.shell();

    let cmd = match shell.sidecar("dialekt-server") {
        Ok(c) => c.env("DIALEKT_SIGNED", SIGNED_BUILD),
        Err(_) => {
            eprintln!("[dialekt] Sidecar 'dialekt-server' not bundled. Start python/server.py manually.");
            // Dev mode: do NOT kill anything on :8765 — that's the user's
            // hand-started `python server.py`. Bundled mode below resets
            // the port before spawning to recover from leaked sidecars.
            return;
        }
    };

    // Reset port :8765 before spawning. Previous Tauri crashes / force-quits
    // leak the python child (start_new_session=True keeps it alive past
    // parent death), so the next launch hits EADDRINUSE on bind, the new
    // sidecar exits, and the FE talks to a stale daemon — or worse, no
    // daemon at all if it's also dead. Reaching for `lsof | kill -9` here
    // gives every cold start a clean port. Same uid as the user, no
    // privilege escalation involved.
    let _ = std::process::Command::new("/bin/sh")
        .arg("-c")
        .arg("PIDS=$(lsof -ti :8765 2>/dev/null); [ -n \"$PIDS\" ] && kill -9 $PIDS; sleep 0.3")
        .status();

    let (mut rx, child) = match cmd.spawn() {
        Ok(pair) => pair,
        Err(e) => {
            eprintln!("[dialekt] Could not spawn sidecar: {e}");
            return;
        }
    };

    // Forward server logs; keep child alive for the lifetime of this task.
    tauri::async_runtime::spawn(async move {
        let _child = child;
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    eprintln!("[server] {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Stderr(line) => {
                    eprintln!("[server] {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Error(e) => {
                    eprintln!("[server] process error: {e}");
                    break;
                }
                CommandEvent::Terminated(s) => {
                    eprintln!("[server] exited with code {:?}", s.code);
                    break;
                }
                _ => {}
            }
        }
    });
}
