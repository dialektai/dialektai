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

/// Spawn the bundled Python backend sidecar.
/// Fails gracefully in dev mode (sidecar not present — start server.py manually).
fn spawn_python_server(app: &tauri::AppHandle) {
    let shell = app.shell();

    let cmd = match shell.sidecar("dialekt-server") {
        Ok(c) => c,
        Err(_) => {
            eprintln!("[dialekt] Sidecar 'dialekt-server' not bundled. Start python/server.py manually.");
            return;
        }
    };

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
