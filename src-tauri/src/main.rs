// src-tauri/src/main.rs
// Vani OS — Tauri v2 backend
// Handles: window management, system tray, global hotkey, IPC to Python backend

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::Mutex;
use tauri::{
    AppHandle, Manager, State,
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},

};
use tauri_plugin_shell::ShellExt;

// ── App State ─────────────────────────────────────────────────────────────────

struct VaniState {
    python_port: u16,
    is_listening: bool,
}

type AppState = Mutex<VaniState>;

// ── IPC Commands (callable from React via invoke()) ───────────────────────────

/// Send a text query to the Python Vani backend
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

/// Toggle the listening state (push-to-talk or wake word)
#[tauri::command]
fn toggle_listening(state: State<'_, AppState>) -> bool {
    let mut s = state.lock().unwrap();
    s.is_listening = !s.is_listening;
    s.is_listening
}

/// Get current memory stats from Python backend
#[tauri::command]
async fn get_memory_stats(state: State<'_, AppState>) -> Result<String, String> {
    let port = state.lock().unwrap().python_port;
    let client = reqwest::Client::new();
    let resp = client
        .get(format!("http://127.0.0.1:{}/memory/stats", port))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    let body = resp.text().await.map_err(|e| e.to_string())?;
    Ok(body)
}

/// Search semantic memory
#[tauri::command]
async fn search_memory(
    query: String,
    state: State<'_, AppState>,
) -> Result<String, String> {
    let port = state.lock().unwrap().python_port;
    let client = reqwest::Client::new();
    let resp = client
        .post(format!("http://127.0.0.1:{}/memory/search", port))
        .json(&serde_json::json!({ "query": query, "top_k": 10 }))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    let body = resp.text().await.map_err(|e| e.to_string())?;
    Ok(body)
}

/// Get tool audit history
#[tauri::command]
async fn get_tool_history(
    tool_name: Option<String>,
    state: State<'_, AppState>,
) -> Result<String, String> {
    let port = state.lock().unwrap().python_port;
    let client = reqwest::Client::new();
    let url = match tool_name {
        Some(name) => format!("http://127.0.0.1:{}/tools/history?tool={}", port, name),
        None => format!("http://127.0.0.1:{}/tools/history", port),
    };
    let resp = client.get(url).send().await.map_err(|e| e.to_string())?;
    let body = resp.text().await.map_err(|e| e.to_string())?;
    Ok(body)
}

/// Get model router status
#[tauri::command]
async fn get_model_status(state: State<'_, AppState>) -> Result<String, String> {
    let port = state.lock().unwrap().python_port;
    let client = reqwest::Client::new();
    let resp = client
        .get(format!("http://127.0.0.1:{}/models/status", port))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    let body = resp.text().await.map_err(|e| e.to_string())?;
    Ok(body)
}

/// Open a URL in the system browser
#[tauri::command]
async fn open_url(url: String, app: AppHandle) -> Result<(), String> {
    app.shell().open(url, None).map_err(|e| e.to_string())
}

/// Minimise to tray
#[tauri::command]
fn hide_to_tray(app: AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.hide();
    }
}

/// Quit the app
#[tauri::command]
fn quit_app(app: AppHandle) {
    app.exit(0);
}

// ── System Tray ───────────────────────────────────────────────────────────────

fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    let show = MenuItem::with_id(app, "show", "Show Vani", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show, &quit])?;

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
                if let Some(window) = app.get_webview_window("main") {
                    if window.is_visible().unwrap_or(false) {
                        let _ = window.hide();
                    } else {
                        let _ = window.show();
                        let _ = window.set_focus();
                    }
                }
            }
        })
        .on_menu_event(|app, event| match event.id.as_ref() {
            "show" => {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            }
            "quit" => app.exit(0),
            _ => {}
        })
        .build(app)?;
    Ok(())
}

// ── Entry point ───────────────────────────────────────────────────────────────

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_fs::init())
        .manage(Mutex::new(VaniState {
            python_port: 8765,
            is_listening: false,
        }))
        .setup(|app| {
            build_tray(app.handle())?;

            // Register global hotkey: Cmd+Shift+Space
            #[cfg(desktop)]
            {
                use tauri_plugin_global_shortcut::{
                    Code, GlobalShortcutExt, Modifiers, Shortcut,
                };
                let shortcut = Shortcut::new(
                    Some(Modifiers::META | Modifiers::SHIFT),
                    Code::Space,
                );
                app.handle().plugin(
                    tauri_plugin_global_shortcut::Builder::new()
                        .with_handler(move |app, s, _event| {
                            if s == &shortcut {
                                if let Some(window) = app.get_webview_window("main") {
                                    if window.is_visible().unwrap_or(false) {
                                        let _ = window.hide();
                                    } else {
                                        let _ = window.show();
                                        let _ = window.set_focus();
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
            toggle_listening,
            get_memory_stats,
            search_memory,
            get_tool_history,
            get_model_status,
            open_url,
            hide_to_tray,
            quit_app,
        ])
        .run(tauri::generate_context!())
        .expect("error running Vani");
}
