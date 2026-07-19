mod process;
mod protocol;
#[cfg(test)]
mod test_support;

use crate::errors::DesktopError;
use crate::paths::BridgeLaunchConfig;
use process::{BridgeProcess, BRIDGE_RESPONSE_TIMEOUT};
use serde::Serialize;
use serde_json::Value;
use std::sync::Mutex;
use std::time::Duration;

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
        self.request_with_timeout(command, BRIDGE_RESPONSE_TIMEOUT)
    }

    pub(crate) fn request_with_timeout(
        &self,
        command: Value,
        timeout: Duration,
    ) -> Result<Value, DesktopError> {
        let mut guard = self
            .process
            .lock()
            .map_err(|_| DesktopError::internal_state_error())?;
        let response = match guard.as_mut() {
            Some(process) => process.request_with_timeout(&command, timeout),
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
                        | "bridge_timeout"
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

#[cfg(test)]
mod tests {
    use super::{BridgeManager, BridgeProcess};
    use crate::bridge::test_support::{
        test_config, unique_temp_root, write_bridge_main_that_stops_responding_after_handshake,
    };
    use serde_json::json;
    use std::fs;
    use std::time::Duration;

    const TEST_TIMEOUT: Duration = Duration::from_millis(300);

    #[test]
    fn stop_is_idempotent_when_the_bridge_never_started() {
        let manager = BridgeManager::default();

        let first = manager.stop().unwrap();
        let second = manager.stop().unwrap();

        assert!(!first.running);
        assert!(!second.running);
        assert_eq!(first.process_id, None);
        assert_eq!(second.process_id, None);
    }

    #[test]
    fn status_is_not_running_and_stop_stays_idempotent_after_a_request_timeout() {
        let root = unique_temp_root("continuity-bridge-manager-timeout-test");
        write_bridge_main_that_stops_responding_after_handshake(&root);

        let process =
            BridgeProcess::spawn_with_timeout(test_config(root.clone()), TEST_TIMEOUT).unwrap();
        let manager = BridgeManager::default();
        *manager.process.lock().unwrap() = Some(process);

        let request_result = manager.request_with_timeout(
            json!({"command": "send_message", "text": "hello"}),
            TEST_TIMEOUT,
        );
        assert_eq!(request_result.unwrap_err().code, "bridge_timeout");

        let status = manager.status().unwrap();
        assert!(!status.running);
        assert_eq!(status.process_id, None);

        let first_stop = manager.stop().unwrap();
        let second_stop = manager.stop().unwrap();
        assert!(!first_stop.running);
        assert!(!second_stop.running);

        fs::remove_dir_all(root).unwrap();
    }
}
