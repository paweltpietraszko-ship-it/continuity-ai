use crate::bridge::{BridgeManager, BridgeStatus};
use crate::errors::DesktopError;
use serde_json::Value;
use tauri::State;

#[tauri::command]
pub fn bridge_start(manager: State<'_, BridgeManager>) -> Result<BridgeStatus, DesktopError> {
    manager.start()
}

#[tauri::command]
pub fn bridge_status(manager: State<'_, BridgeManager>) -> Result<BridgeStatus, DesktopError> {
    manager.status()
}

#[tauri::command]
pub fn bridge_request(
    manager: State<'_, BridgeManager>,
    command: Value,
) -> Result<Value, DesktopError> {
    manager.request(command)
}

#[tauri::command]
pub fn bridge_stop(manager: State<'_, BridgeManager>) -> Result<BridgeStatus, DesktopError> {
    manager.stop()
}
