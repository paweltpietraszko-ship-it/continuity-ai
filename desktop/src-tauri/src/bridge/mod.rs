mod process;
mod protocol;

use crate::errors::DesktopError;
use crate::paths::BridgeLaunchConfig;
use process::BridgeProcess;
use serde::Serialize;
use serde_json::Value;
use std::sync::Mutex;

#[derive(Default)]
pub struct BridgeManager {
    process: Mutex<Option<BridgeProcess>>,
}

#[derive(Debug, Serialize)]
pub struct BridgeStatus {
    pub running: bool,
    pub process_id: Option<u32>,
}

impl BridgeManager {
    pub fn start(&self) -> Result<BridgeStatus, DesktopError> {
        let mut guard = self
            .process
            .lock()
            .map_err(|_| DesktopError::internal_state_error())?;
        if guard.is_some() {
            return Err(DesktopError::bridge_already_running());
        }

        let process = BridgeProcess::spawn(BridgeLaunchConfig::resolve()?)?;
        let status = BridgeStatus {
            running: true,
            process_id: Some(process.process_id()),
        };
        *guard = Some(process);
        Ok(status)
    }

    pub fn status(&self) -> Result<BridgeStatus, DesktopError> {
        let mut guard = self
            .process
            .lock()
            .map_err(|_| DesktopError::internal_state_error())?;
        let running = match guard.as_mut() {
            Some(process) => process.is_running()?,
            None => false,
        };
        if !running {
            guard.take();
        }
        Ok(BridgeStatus {
            running,
            process_id: guard.as_ref().map(BridgeProcess::process_id),
        })
    }

    pub fn request(&self, command: Value) -> Result<Value, DesktopError> {
        let mut guard = self
            .process
            .lock()
            .map_err(|_| DesktopError::internal_state_error())?;
        let response = match guard.as_mut() {
            Some(process) => process.request(&command),
            None => return Err(DesktopError::bridge_not_running()),
        };
        match response {
            Ok(response) => Ok(response),
            Err(error) => {
                if matches!(
                    error.code,
                    "bridge_stopped"
                        | "bridge_write_failed"
                        | "bridge_read_failed"
                        | "bridge_protocol_error"
                        | "bridge_response_too_large"
                ) {
                    guard.take();
                }
                Err(error)
            }
        }
    }

    pub fn stop(&self) -> Result<BridgeStatus, DesktopError> {
        let mut guard = self
            .process
            .lock()
            .map_err(|_| DesktopError::internal_state_error())?;
        if let Some(mut process) = guard.take() {
            process.stop();
        }
        Ok(BridgeStatus {
            running: false,
            process_id: None,
        })
    }
}
