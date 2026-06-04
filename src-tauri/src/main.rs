// src-tauri/src/main.rs
// Vani OS — P4 Edition

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::{Arc, Mutex};
use std::path::PathBuf;
use std::fs;
use serde::{Deserialize, Serialize};
use tauri::{
    AppHandle, Emitter, Manager, State,
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
};
use tauri_plugin_opener::OpenerExt;

// ── Persistent Tray State ─────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
struct PersistedState {
    window_x: i32,
    window_y: i32,
    window_visible: bool,
    last_mode: String,
    notifications_enabled: bool,
    wake_word_enabled: bool,
    session_count: u32,
    streaming_enabled: bool,
}

impl Default for PersistedState {
    fn default() -> Self {
        Self {
            window_x: -1,
            window_y: -1,
            window_visible: true,
            last_mode: "voice".into(),
            notifications_enabled: true,
            wake_word_enabled: true,
            session_count: 0,
            streaming_enabled: true,
        }
    }
}

fn state_path() -> PathBuf {
    dirs_next::home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("vani_tray_state.json")
}

fn load_persisted() -> PersistedState {
    let path = state_path();
    if let Ok(raw) = fs::read_to_string(&path) {
        if let Ok(mut s) = serde_json::from_str::<PersistedState>(&raw) {
            s.session_count += 1;
            return s;
        }
    }
    let mut s = PersistedState::default();
    s.session_count = 1;
    s
}

fn save_persisted(s: &PersistedState) {
    if let Ok(json) = serde_json::to_string_pretty(s) {
        let _ = fs::write(state_path(), json);
    }
}

// ── App State ─────────────────────────────────────────────────────────────────

#[allow(dead_code)]
struct VaniState {
    python_port: u16,
    is_listening: bool,
    is_speaking: bool,
    wake_word_active: bool,
    persisted: PersistedState,
}

type AppState = Arc<Mutex<VaniState>>;

// ── IPC Commands ──────────────────────────────────────────────────────────────

#[tauri::command]
async fn send_query(
    query: String,
    state: State<'_, AppState>,
) -> Result<String, String> {
    let port = state.lock().unwrap().python_port;
    let client = reqwest::Client::new();
    let resp = client
        .post(format!("http://127.0.0.1:{}/query", port))
        .json(&serde_json::json!({ "text": query }))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    let body: serde_json::Value = resp.json().await.map_err(|e| e.to_string())?;
    Ok(body.to_string())
}

#[tauri::command]
async fn send_query_stream(
    query: String,
    state: State<'_, AppState>,
    app: AppHandle,
) -> Result<(), String> {
    let port = state.lock().unwrap().python_port;
    let url = format!(
        "http://127.0.0.1:{}/stream?text={}",
        port,
        urlencoding::encode(&query)
    );
    let client = reqwest::Client::new();
    let response = client
        .get(&url)
        .header("Accept", "text/event-stream")
        .send()
        .await
        .map_err(|e| format!("stream connect error: {e}"))?;

    use futures_util::StreamExt;
    let mut stream = response.bytes_stream();
    let mut buffer = String::new();

    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|e| e.to_string())?;
        buffer.push_str(&String::from_utf8_lossy(&chunk));
        while let Some(pos) = buffer.find("\n\n") {
            let msg = buffer[..pos].trim().to_string();
            buffer = buffer[pos + 2..].to_string();
            if let Some(data) = msg.strip_prefix("data: ") {
                if let Ok(obj) = serde_json::from_str::<serde_json::Value>(data) {
                    let _ = app.emit("stream-token", &obj);
                    if obj.get("done").and_then(|v| v.as_bool()).unwrap_or(false) {
                        return Ok(());
                    }
                }
            }
        }
    }
    Ok(())
}

#[tauri::command]
fn toggle_listening(state: State<'_, AppState>) -> bool {
    let mut s = state.lock().unwrap();
    s.is_listening = !s.is_listening;
    s.is_listening
}

#[tauri::command]
async fn get_memory_stats(state: State<'_, AppState>) -> Result<String, String> {
    let port = state.lock().unwrap().python_port;
    let resp = reqwest::Client::new()
        .get(format!("http://127.0.0.1:{}/memory/stats", port))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    Ok(resp.text().await.map_err(|e| e.to_string())?)
}

#[tauri::command]
async fn search_memory(
    query: String,
    state: State<'_, AppState>,
) -> Result<String, String> {
    let port = state.lock().unwrap().python_port;
    let resp = reqwest::Client::new()
        .post(format!("http://127.0.0.1:{}/memory/search", port))
        .json(&serde_json::json!({ "query": query, "top_k": 10 }))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    Ok(resp.text().await.map_err(|e| e.to_string())?)
}

#[tauri::command]
async fn get_tool_history(
    tool_name: Option<String>,
    state: State<'_, AppState>,
) -> Result<String, String> {
    let port = state.lock().unwrap().python_port;
    let url = match tool_name {
        Some(name) => format!("http://127.0.0.1:{}/tools/history?tool={}", port, name),
        None => format!("http://127.0.0.1:{}/tools/history", port),
    };
    let resp = reqwest::Client::new()
        .get(url)
        .send()
        .await
        .map_err(|e| e.to_string())?;
    Ok(resp.text().await.map_err(|e| e.to_string())?)
}

#[tauri::command]
async fn get_model_status(state: State<'_, AppState>) -> Result<String, String> {
    let port = state.lock().unwrap().python_port;
    let resp = reqwest::Client::new()
        .get(format!("http://127.0.0.1:{}/models/status", port))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    Ok(resp.text().await.map_err(|e| e.to_string())?)
}

#[tauri::command]
async fn open_url(url: String, app: AppHandle) -> Result<(), String> {
    app.opener().open_url(url, None::<&str>).map_err(|e| e.to_string())
}

#[tauri::command]
fn hide_to_tray(app: AppHandle, state: State<'_, AppState>) {
    if let Some(window) = app.get_webview_window("main") {
        if let Ok(pos) = window.outer_position() {
            let mut s = state.lock().unwrap();
            s.persisted.window_x = pos.x;
            s.persisted.window_y = pos.y;
            s.persisted.window_visible = false;
            save_persisted(&s.persisted);
        }
        let _ = window.hide();
    }
}

#[tauri::command]
fn minimize_window(app: AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.minimize();
    }
}

#[tauri::command]
fn expand_to_full_ui(app: AppHandle, state: State<'_, AppState>) {
    if let Some(main_win) = app.get_webview_window("main") {
        let _ = main_win.show();
        let _ = main_win.unminimize();
        let _ = main_win.set_focus();
        
        let mut s = state.lock().unwrap();
        s.persisted.window_visible = true;
        save_persisted(&s.persisted);
    }
    if let Some(overlay_win) = app.get_webview_window("overlay") {
        let _ = overlay_win.hide();
    }
}

#[tauri::command]
fn collapse_to_overlay(app: AppHandle, state: State<'_, AppState>) {
    if let Some(overlay_win) = app.get_webview_window("overlay") {
        if let Some(monitor) = overlay_win.current_monitor().ok().flatten() {
            let size = monitor.size();
            let x = (size.width as i32 - 420) / 2;
            let y = 20;
            let _ = overlay_win.set_position(tauri::PhysicalPosition::new(x, y));
        }
        let _ = overlay_win.show();
        let _ = overlay_win.set_focus();
    }
    if let Some(main_win) = app.get_webview_window("main") {
        let _ = main_win.hide();
        let mut s = state.lock().unwrap();
        s.persisted.window_visible = false;
        save_persisted(&s.persisted);
    }
}

#[tauri::command]
fn set_overlay_visible(visible: bool, app: AppHandle) {
    if let Some(overlay_win) = app.get_webview_window("overlay") {
        if visible {
            if let Some(monitor) = overlay_win.current_monitor().ok().flatten() {
                let size = monitor.size();
                let x = (size.width as i32 - 420) / 2;
                let y = 20;
                let _ = overlay_win.set_position(tauri::PhysicalPosition::new(x, y));
            }
            let _ = overlay_win.show();
            let _ = overlay_win.set_focus();
        } else {
            let _ = overlay_win.hide();
        }
    }
}

#[tauri::command]
fn quit_app(app: AppHandle, state: State<'_, AppState>) {
    {
        let s = state.lock().unwrap();
        save_persisted(&s.persisted);
    }
    kill_python_backend();
    app.exit(0);
}

#[tauri::command]
fn get_persisted_state(state: State<'_, AppState>) -> Result<String, String> {
    let s = state.lock().unwrap();
    serde_json::to_string(&s.persisted).map_err(|e| e.to_string())
}

#[tauri::command]
fn update_persisted_state(
    key: String,
    value: serde_json::Value,
    state: State<'_, AppState>,
) -> Result<(), String> {
    let mut s = state.lock().unwrap();
    match key.as_str() {
        "wake_word_enabled"     => { if let Some(b) = value.as_bool() { s.persisted.wake_word_enabled = b; } }
        "streaming_enabled"     => { if let Some(b) = value.as_bool() { s.persisted.streaming_enabled = b; } }
        "notifications_enabled" => { if let Some(b) = value.as_bool() { s.persisted.notifications_enabled = b; } }
        "last_mode"             => { if let Some(v) = value.as_str()  { s.persisted.last_mode = v.into(); } }
        _ => {}
    }
    save_persisted(&s.persisted);
    Ok(())
}

#[tauri::command]
async fn get_wake_status(state: State<'_, AppState>) -> Result<String, String> {
    let port = state.lock().unwrap().python_port;
    let resp = reqwest::Client::new()
        .get(format!("http://127.0.0.1:{}/wake/status", port))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    Ok(resp.text().await.map_err(|e| e.to_string())?)
}

// ── Wake Word Listener ────────────────────────────────────────────────────────
// Spawns its own OS thread with a dedicated Tokio runtime so it never
// conflicts with macOS's did_finish_launching (which has no reactor).

fn start_wake_word_listener(python_port: u16, app: AppHandle) {
    std::thread::spawn(move || {
        let rt = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("wake word runtime build failed");

        rt.block_on(async move {
            let client = reqwest::Client::new();
            loop {
                tokio::time::sleep(tokio::time::Duration::from_millis(250)).await;
                if let Ok(resp) = client
                    .get(format!("http://127.0.0.1:{}/state", python_port))
                    .timeout(std::time::Duration::from_secs(1))
                    .send()
                    .await
                {
                    if let Ok(body) = resp.text().await {
                        if let Ok(state_val) =
                            serde_json::from_str::<serde_json::Value>(&body)
                        {
                            let _ = app.emit("vani-state", &state_val);
                        }
                    }
                }
            }
        });
    });
}

// ── System Tray ───────────────────────────────────────────────────────────────

fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    let show   = MenuItem::with_id(app, "show",   "Show Vani",        true, None::<&str>)?;
    let wake   = MenuItem::with_id(app, "wake",   "Toggle Wake Word", true, None::<&str>)?;
    let stream = MenuItem::with_id(app, "stream", "Toggle Streaming", true, None::<&str>)?;
    let sep    = tauri::menu::PredefinedMenuItem::separator(app)?;
    let quit   = MenuItem::with_id(app, "quit",   "Quit Vani",        true, None::<&str>)?;
    let menu   = Menu::with_items(app, &[&show, &wake, &stream, &sep, &quit])?;

    TrayIconBuilder::new()
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                let app = tray.app_handle();
                let main_visible = app.get_webview_window("main")
                    .and_then(|w| w.is_visible().ok())
                    .unwrap_or(false);

                if main_visible {
                    // Hide main window (and overlay)
                    if let Some(m_win) = app.get_webview_window("main") {
                        let _ = m_win.hide();
                        let state: State<AppState> = app.state();
                        let mut s = state.lock().unwrap();
                        s.persisted.window_visible = false;
                        save_persisted(&s.persisted);
                    }
                    if let Some(o_win) = app.get_webview_window("overlay") {
                        let _ = o_win.hide();
                    }
                } else {
                    // Show main window and hide overlay
                    if let Some(m_win) = app.get_webview_window("main") {
                        let _ = m_win.show();
                        let _ = m_win.unminimize();
                        let _ = m_win.set_focus();
                        let state: State<AppState> = app.state();
                        let mut s = state.lock().unwrap();
                        s.persisted.window_visible = true;
                        save_persisted(&s.persisted);
                    }
                    if let Some(o_win) = app.get_webview_window("overlay") {
                        let _ = o_win.hide();
                    }
                }
            }
        })
        .on_menu_event(|app, event| match event.id.as_ref() {
            "show" => {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.unminimize();
                    let _ = window.set_focus();
                }
                if let Some(overlay_win) = app.get_webview_window("overlay") {
                    let _ = overlay_win.hide();
                }
            }
            "wake" => {
                let app2 = app.clone();
                tokio::spawn(async move {
                    let state: State<AppState> = app2.state();
                    let (port, enabled) = {
                        let mut s = state.lock().unwrap();
                        s.persisted.wake_word_enabled = !s.persisted.wake_word_enabled;
                        save_persisted(&s.persisted);
                        (s.python_port, s.persisted.wake_word_enabled)
                    };
                    let _ = reqwest::Client::new()
                        .post(format!("http://127.0.0.1:{}/wake/set_enabled", port))
                        .json(&serde_json::json!({ "enabled": enabled }))
                        .send()
                        .await;
                });
            }
            "stream" => {
                let app2 = app.clone();
                tokio::spawn(async move {
                    let state: State<AppState> = app2.state();
                    let mut s = state.lock().unwrap();
                    s.persisted.streaming_enabled = !s.persisted.streaming_enabled;
                    save_persisted(&s.persisted);
                });
            }
            "quit" => {
                let state: State<AppState> = app.state();
                let s = state.lock().unwrap();
                save_persisted(&s.persisted);
                kill_python_backend();
                app.exit(0);
            }
            _ => {}
        })
        .build(app)?;
    Ok(())
}

// ── Python Backend Spawner ────────────────────────────────────────────────────
//
// Finds the venv Python next to the .app bundle (or dev project root) and
// launches `python -m vani.launcher` exactly like start.sh does.

static BACKEND_PID: std::sync::OnceLock<std::sync::Mutex<Option<u32>>> =
    std::sync::OnceLock::new();

fn project_root() -> std::path::PathBuf {
    let exe = std::env::current_exe().unwrap_or_default();

    // ── Bundled .app: read path hint written by build_dmg.sh ─────────────────
    // Vani.app/Contents/MacOS/vani  (exe)
    //          Contents/Resources/vani_backend_path.txt  -> absolute path to backend/
    //          Contents/Resources/backend/               (fallback if hint missing)
    if let Some(macos_dir) = exe.parent() {
        if let Some(contents_dir) = macos_dir.parent() {
            // Try hint file first (most reliable)
            let hint = contents_dir.join("Resources").join("vani_backend_path.txt");
            if hint.exists() {
                if let Ok(path_str) = std::fs::read_to_string(&hint) {
                    let p = std::path::PathBuf::from(path_str.trim());
                    if p.join("src").join("vani").exists() {
                        eprintln!("[vani] project_root (hint): {}", p.display());
                        return p;
                    }
                }
            }
            // Direct embedded path fallback
            let embedded = contents_dir.join("Resources").join("backend");
            if embedded.join("src").join("vani").exists() {
                eprintln!("[vani] project_root (embedded): {}", embedded.display());
                return embedded;
            }
        }
    }

    // ── Dev mode (cargo run): climb up from exe until src/vani found ─────────
    let mut dir = exe.parent().unwrap_or(&exe).to_path_buf();
    for _ in 0..10 {
        if dir.join("src").join("vani").exists() {
            eprintln!("[vani] project_root (dev): {}", dir.display());
            return dir;
        }
        if let Some(p) = dir.parent() { dir = p.to_path_buf(); } else { break; }
    }

    let cwd = std::env::current_dir().unwrap_or_default();
    eprintln!("[vani] project_root (cwd fallback): {}", cwd.display());
    cwd
}

fn find_venv_python(root: &std::path::Path) -> Option<std::path::PathBuf> {
    for candidate in &["venv311_new/bin/python", "venv311/bin/python", ".venv/bin/python"] {
        let p = root.join(candidate);
        if p.exists() { return Some(p); }
    }
    None
}

fn spawn_python_backend() {
    BACKEND_PID.get_or_init(|| std::sync::Mutex::new(None));
    std::thread::spawn(|| {
        let root   = project_root();
        let python = match find_venv_python(&root) {
            Some(p) => p,
            None => {
                eprintln!("[vani] No Python venv found. Expected venv311_new/, venv311/ or .venv/ beside Vani.app");
                return;
            }
        };

        let src_path = root.join("src");
        let mut pypath = src_path.to_string_lossy().to_string();
        if let Ok(existing) = std::env::var("PYTHONPATH") {
            pypath = format!("{}:{}", pypath, existing);
        }

        let mut cmd = std::process::Command::new(&python);
        cmd.args(["-m", "vani.launcher"])
           .current_dir(&root)
           .env("PYTHONPATH", &pypath)
           .env("PYTHONUNBUFFERED", "1");

        // Inline-parse .env so API keys reach the subprocess
        let dotenv_path = root.join(".env");
        if dotenv_path.exists() {
            if let Ok(contents) = std::fs::read_to_string(&dotenv_path) {
                for line in contents.lines() {
                    let line = line.trim();
                    if line.is_empty() || line.starts_with('#') { continue; }
                    if let Some((k, v)) = line.split_once('=') {
                        let k = k.trim();
                        let v = v.trim().trim_matches('"').trim_matches('\'');
                        if !k.is_empty() { cmd.env(k, v); }
                    }
                }
            }
        }

        // Write stdout + stderr to ~/Library/Logs/vani_backend.log
        let log_path = dirs_next::home_dir()
            .unwrap_or_default()
            .join("Library/Logs/vani_backend.log");
        if let Ok(log) = std::fs::OpenOptions::new().create(true).append(true).open(&log_path) {
            use std::os::unix::io::IntoRawFd;
            let fd = log.into_raw_fd();
            unsafe {
                use std::os::unix::io::FromRawFd;
                cmd.stdout(std::process::Stdio::from_raw_fd(fd));
                cmd.stderr(std::process::Stdio::from_raw_fd(libc::dup(fd)));
            }
        }

        match cmd.spawn() {
            Ok(child) => {
                let pid = child.id();
                if let Some(lock) = BACKEND_PID.get() {
                    *lock.lock().unwrap() = Some(pid);
                }
                eprintln!("[vani] Python backend started (PID {}). Logs: {:?}", pid, log_path);
            }
            Err(e) => eprintln!("[vani] Failed to start Python backend: {}", e),
        }
    });
}

fn kill_python_backend() {
    if let Some(lock) = BACKEND_PID.get() {
        if let Some(pid) = *lock.lock().unwrap() {
            #[cfg(unix)]
            unsafe { libc::kill(pid as libc::pid_t, libc::SIGTERM); }
            eprintln!("[vani] Python backend stopped (PID {}).", pid);
        }
    }
}

// ── Entry point ───────────────────────────────────────────────────────────────

fn main() {
    let persisted = load_persisted();
    let wake_word_on = persisted.wake_word_enabled;

    let app_state: AppState = Arc::new(Mutex::new(VaniState {
        python_port: 8765,
        is_listening: false,
        is_speaking: false,
        wake_word_active: wake_word_on,
        persisted,
    }));

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_fs::init())
        .manage(app_state)
        .setup(move |app| {
            // ── Boot Python backend (same as start.sh) ────────────────────
            spawn_python_backend();

            build_tray(app.handle())?;

            // ── Keep window hidden until Python backend is ready on port 5500.
            // devUrl is http://127.0.0.1:5500/ui — Tauri loads it directly.
            // We hide the window so the user never sees a blank webview while
            // Python boots. Once 5500/ui returns HTTP 200 we reload and show.
            // IMPORTANT: no window.location.href — that breaks CSP and mic perms.
            let main_win = app.get_webview_window("main");
            let overlay_win = app.get_webview_window("overlay");

            if let Some(ref w) = main_win {
                let _ = w.hide();
                // Restore saved position while still hidden
                {
                    let state: State<AppState> = app.handle().state();
                    let s = state.lock().unwrap();
                    if s.persisted.window_x >= 0 && s.persisted.window_y >= 0 {
                        let _ = w.set_position(tauri::PhysicalPosition::new(
                            s.persisted.window_x,
                            s.persisted.window_y,
                        ));
                    }
                }
            }
            if let Some(ref w) = overlay_win {
                let _ = w.hide();
            }

            let app_handle = app.handle().clone();
            std::thread::spawn(move || {
                let rt = tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .expect("wait-for-backend runtime");

                rt.block_on(async move {
                    let client = reqwest::Client::builder()
                        .timeout(std::time::Duration::from_secs(2))
                        .build()
                        .unwrap();

                    let mut attempts = 0u32;
                    loop {
                        tokio::time::sleep(tokio::time::Duration::from_millis(600)).await;
                        attempts += 1;

                        if let Ok(resp) = client.get("http://127.0.0.1:5500/ui").send().await {
                            if resp.status().is_success() {
                                eprintln!("[vani] Backend ready after {} attempts — reloading and showing windows", attempts);
                                
                                let window_visible = {
                                    let state: State<AppState> = app_handle.state();
                                    let s = state.lock().unwrap();
                                    s.persisted.window_visible
                                };

                                if let Some(m_win) = app_handle.get_webview_window("main") {
                                    let _ = m_win.eval("window.location.reload();");
                                    if window_visible {
                                        tokio::time::sleep(tokio::time::Duration::from_millis(500)).await;
                                        let _ = m_win.show();
                                        let _ = m_win.unminimize();
                                        let _ = m_win.set_focus();
                                    }
                                }
                                if let Some(o_win) = app_handle.get_webview_window("overlay") {
                                    let _ = o_win.eval("window.location.reload();");
                                    if !window_visible {
                                        if let Some(monitor) = o_win.current_monitor().ok().flatten() {
                                            let size = monitor.size();
                                            let x = (size.width as i32 - 420) / 2;
                                            let y = 20;
                                            let _ = o_win.set_position(tauri::PhysicalPosition::new(x, y));
                                        }
                                        tokio::time::sleep(tokio::time::Duration::from_millis(500)).await;
                                        let _ = o_win.show();
                                        let _ = o_win.set_focus();
                                    } else {
                                        let _ = o_win.hide();
                                    }
                                }
                                return;
                            }
                        }

                        if attempts >= 150 {
                            eprintln!("[vani] Backend did not start in 90s — showing overlay anyway");
                            if let Some(o_win) = app_handle.get_webview_window("overlay") {
                                let _ = o_win.show();
                            }
                            return;
                        }
                    }
                });
            });

            // Start wake word listener in its own thread+runtime
            if wake_word_on {
                start_wake_word_listener(8765, app.handle().clone());
            }

            // Global hotkey: Cmd+Shift+K
            #[cfg(desktop)]
            {
                use tauri_plugin_global_shortcut::{
                    Code, GlobalShortcutExt, Modifiers, Shortcut,
                };
                let shortcut = Shortcut::new(
                    Some(Modifiers::META | Modifiers::SHIFT),
                    Code::KeyK,
                );
                app.handle().plugin(
                    tauri_plugin_global_shortcut::Builder::new()
                        .with_handler(move |app, s, _event| {
                            if s == &shortcut {
                                let main_visible = app.get_webview_window("main")
                                    .and_then(|w| w.is_visible().ok())
                                    .unwrap_or(false);
                                
                                if main_visible {
                                    // Collapse to overlay
                                    if let Some(o_win) = app.get_webview_window("overlay") {
                                        if let Some(monitor) = o_win.current_monitor().ok().flatten() {
                                            let size = monitor.size();
                                            let x = (size.width as i32 - 420) / 2;
                                            let y = 20;
                                            let _ = o_win.set_position(tauri::PhysicalPosition::new(x, y));
                                        }
                                        let _ = o_win.show();
                                        let _ = o_win.set_focus();
                                    }
                                    if let Some(m_win) = app.get_webview_window("main") {
                                        let _ = m_win.hide();
                                        let state: State<AppState> = app.state();
                                        let mut s = state.lock().unwrap();
                                        s.persisted.window_visible = false;
                                        save_persisted(&s.persisted);
                                    }
                                } else {
                                    // Check overlay visibility
                                    let overlay_visible = app.get_webview_window("overlay")
                                        .and_then(|w| w.is_visible().ok())
                                        .unwrap_or(false);

                                    if overlay_visible {
                                        // Expand overlay to main
                                        if let Some(m_win) = app.get_webview_window("main") {
                                            let _ = m_win.show();
                                            let _ = m_win.unminimize();
                                            let _ = m_win.set_focus();
                                            let state: State<AppState> = app.state();
                                            let mut s = state.lock().unwrap();
                                            s.persisted.window_visible = true;
                                            save_persisted(&s.persisted);
                                        }
                                        if let Some(o_win) = app.get_webview_window("overlay") {
                                            let _ = o_win.hide();
                                        }
                                    } else {
                                        // Both hidden: show main
                                        if let Some(m_win) = app.get_webview_window("main") {
                                            let _ = m_win.show();
                                            let _ = m_win.unminimize();
                                            let _ = m_win.set_focus();
                                            let state: State<AppState> = app.state();
                                            let mut s = state.lock().unwrap();
                                            s.persisted.window_visible = true;
                                            save_persisted(&s.persisted);
                                        }
                                    }
                                }
                            }
                        })
                        .build(),
                )?;
                app.global_shortcut().register(shortcut)?;
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            send_query,
            send_query_stream,
            toggle_listening,
            get_memory_stats,
            search_memory,
            get_tool_history,
            get_model_status,
            open_url,
            hide_to_tray,
            quit_app,
            get_persisted_state,
            update_persisted_state,
            get_wake_status,
            minimize_window,
            expand_to_full_ui,
            collapse_to_overlay,
            set_overlay_visible,
        ])
        .run(tauri::generate_context!())
        .expect("error running Vani");
}