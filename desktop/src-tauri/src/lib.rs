mod bridge;
mod commands;
mod errors;
mod paths;

use bridge::BridgeManager;
use commands::{bridge_request, bridge_start, bridge_status, bridge_stop};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(BridgeManager::default())
        .invoke_handler(tauri::generate_handler![
            bridge_start,
            bridge_status,
            bridge_request,
            bridge_stop
        ])
        .run(tauri::generate_context!())
        .expect("failed to run Continuity AI desktop application");
}
