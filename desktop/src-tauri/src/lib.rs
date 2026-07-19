mod bridge;
mod commands;
mod errors;
mod paths;

use bridge::BridgeManager;
use commands::{bridge_request, bridge_start, bridge_status, bridge_stop};
use tauri::{Manager, RunEvent};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(BridgeManager::default())
        .invoke_handler(tauri::generate_handler![
            bridge_start,
            bridge_status,
            bridge_request,
            bridge_stop
        ])
        .build(tauri::generate_context!())
        .expect("failed to build Continuity AI desktop application");

    app.run(|app_handle, event| {
        if let RunEvent::Exit = event {
            let manager = app_handle.state::<BridgeManager>();
            let _ = manager.stop();
        }
    });
}
