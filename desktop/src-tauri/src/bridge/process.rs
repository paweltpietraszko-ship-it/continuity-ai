use crate::bridge::protocol::{encode_command, read_response};
use crate::errors::DesktopError;
use crate::paths::BridgeLaunchConfig;
use serde_json::{json, Value};
use std::env;
use std::ffi::OsString;
use std::io::{BufReader, BufWriter, Write};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

const GRACEFUL_SHUTDOWN_TIMEOUT: Duration = Duration::from_millis(800);
const SHUTDOWN_POLL_INTERVAL: Duration = Duration::from_millis(20);

/// Bounds every blocking Bridge response read, including the handshake
/// performed in `spawn`. A hung Python process can therefore never block a
/// caller — or the `BridgeManager` mutex it holds — for longer than this.
/// Production code always uses this constant via `spawn`/`BridgeManager`;
/// tests inject a shorter `Duration` through the `*_with_timeout` variants
/// instead of waiting out the real value.
pub(crate) const BRIDGE_RESPONSE_TIMEOUT: Duration = Duration::from_secs(8);

pub struct BridgeProcess {
    child: Child,
    stdin: Option<BufWriter<ChildStdin>>,
    stdout: Option<BufReader<ChildStdout>>,
}

impl BridgeProcess {
    pub fn spawn(config: BridgeLaunchConfig) -> Result<Self, DesktopError> {
        Self::spawn_with_timeout(config, BRIDGE_RESPONSE_TIMEOUT)
    }

    pub(crate) fn spawn_with_timeout(
        config: BridgeLaunchConfig,
        timeout: Duration,
    ) -> Result<Self, DesktopError> {
        let (child, stdin, stdout) = spawn_child(&config)?;
        let mut process = Self {
            child,
            stdin: Some(stdin),
            stdout: Some(stdout),
        };

        let handshake = process
            .request_with_timeout(&json!({"command": "get_workspace_state"}), timeout)
            .map_err(|error| match error.code {
                "bridge_timeout" => error,
                _ => DesktopError::bridge_start_failed(),
            })?;
        if handshake.get("ok").and_then(Value::as_bool) != Some(true) {
            return Err(DesktopError::bridge_start_failed());
        }
        Ok(process)
    }

    pub(crate) fn request_with_timeout(
        &mut self,
        command: &Value,
        timeout: Duration,
    ) -> Result<Value, DesktopError> {
        if !self.is_running()? {
            return Err(DesktopError::bridge_stopped());
        }

        let expected_command = command
            .get("command")
            .and_then(Value::as_str)
            .ok_or_else(DesktopError::invalid_request)?
            .to_owned();
        let encoded = encode_command(command)?;
        let writer = self
            .stdin
            .as_mut()
            .ok_or_else(DesktopError::bridge_not_running)?;
        writer
            .write_all(&encoded)
            .and_then(|_| writer.flush())
            .map_err(|_| DesktopError::bridge_write_failed())?;

        let reader = self
            .stdout
            .take()
            .ok_or_else(DesktopError::bridge_not_running)?;
        let (returned_reader, result) = read_response_bounded(reader, timeout);

        match &result {
            Err(error) if error.code == "bridge_timeout" => {
                // The blocking read is still parked on a background thread.
                // Killing the child closes its end of the pipe, which
                // unblocks that thread so it can exit and drop the
                // abandoned reader on its own; we never wait on it here.
                terminate_child(&mut self.child);
                self.stdin.take();
            }
            _ => self.stdout = returned_reader,
        }

        let response = result?;
        if response.get("command").and_then(Value::as_str) != Some(expected_command.as_str()) {
            return Err(DesktopError::bridge_protocol_error());
        }
        Ok(response)
    }

    pub fn is_running(&mut self) -> Result<bool, DesktopError> {
        self.child
            .try_wait()
            .map(|status| status.is_none())
            .map_err(|_| DesktopError::bridge_stopped())
    }

    pub fn process_id(&self) -> u32 {
        self.child.id()
    }

    pub fn stop(&mut self) {
        self.stdin.take();
        self.stdout.take();

        let deadline = Instant::now() + GRACEFUL_SHUTDOWN_TIMEOUT;
        while Instant::now() < deadline {
            match self.child.try_wait() {
                Ok(Some(_)) => return,
                Ok(None) => thread::sleep(SHUTDOWN_POLL_INTERVAL),
                Err(_) => break,
            }
        }

        terminate_child(&mut self.child);
    }
}

impl Drop for BridgeProcess {
    fn drop(&mut self) {
        self.stop();
    }
}

fn spawn_child(
    config: &BridgeLaunchConfig,
) -> Result<(Child, BufWriter<ChildStdin>, BufReader<ChildStdout>), DesktopError> {
    let python_path = merge_python_path(config.backend_root.join("src"))?;
    let mut command = Command::new(&config.python);
    command
        .arg("-m")
        .arg("continuity_ai.bridge_main")
        .current_dir(&config.backend_root)
        .env("CONTINUITY_REASONING_PROVIDER", &config.provider)
        .env("PYTHONPATH", python_path)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }

    let mut child = command
        .spawn()
        .map_err(|_| DesktopError::bridge_start_failed())?;
    let stdin = match child.stdin.take() {
        Some(stdin) => BufWriter::new(stdin),
        None => {
            terminate_child(&mut child);
            return Err(DesktopError::bridge_start_failed());
        }
    };
    let stdout = match child.stdout.take() {
        Some(stdout) => BufReader::new(stdout),
        None => {
            terminate_child(&mut child);
            return Err(DesktopError::bridge_start_failed());
        }
    };

    if let Some(mut stderr) = child.stderr.take() {
        thread::spawn(move || {
            let _ = std::io::copy(&mut stderr, &mut std::io::sink());
        });
    }

    Ok((child, stdin, stdout))
}

/// Reads one response with a bounded wait. The blocking read runs on a
/// dedicated thread so a hung Bridge process can never block the caller (or
/// the mutex it holds) past `timeout`. On success the reader — with any
/// state the `BufReader` accumulated — is handed back so the next request
/// keeps reading from the right place. On timeout the reader is abandoned;
/// the caller is expected to terminate the child, which closes the pipe and
/// lets the background thread unblock and exit on its own.
fn read_response_bounded(
    reader: BufReader<ChildStdout>,
    timeout: Duration,
) -> (Option<BufReader<ChildStdout>>, Result<Value, DesktopError>) {
    let (sender, receiver) = mpsc::channel();

    thread::spawn(move || {
        let mut reader = reader;
        let result = read_response(&mut reader);
        let _ = sender.send((reader, result));
    });

    match receiver.recv_timeout(timeout) {
        Ok((reader, result)) => (Some(reader), result),
        Err(_) => (None, Err(DesktopError::bridge_timeout())),
    }
}

fn merge_python_path(backend_src: std::path::PathBuf) -> Result<OsString, DesktopError> {
    let mut entries = vec![backend_src];
    if let Some(existing) = env::var_os("PYTHONPATH") {
        entries.extend(env::split_paths(&existing));
    }
    env::join_paths(entries).map_err(|_| DesktopError::bridge_start_failed())
}

fn terminate_child(child: &mut Child) {
    let _ = child.kill();
    let _ = child.wait();
}

#[cfg(test)]
mod tests {
    use super::{BridgeProcess, BRIDGE_RESPONSE_TIMEOUT};
    use crate::bridge::test_support::{
        test_config, unique_temp_root, write_bridge_main_that_stops_responding_after_handshake,
        write_fake_bridge_main, write_hanging_bridge_main,
    };
    use serde_json::json;
    use std::fs;
    use std::time::Duration;

    const TEST_TIMEOUT: Duration = Duration::from_millis(300);

    #[test]
    fn persistent_process_round_trips_utf8_ndjson() {
        let root = unique_temp_root("continuity-bridge-process-test");
        write_fake_bridge_main(&root);

        let mut process = BridgeProcess::spawn(test_config(root.clone())).unwrap();
        let response = process
            .request_with_timeout(
                &json!({"command": "send_message", "text": "Paweł Żółć"}),
                BRIDGE_RESPONSE_TIMEOUT,
            )
            .unwrap();
        assert_eq!(response["data"]["echo"], "Paweł Żółć");
        process.stop();
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn stop_terminates_the_python_subprocess() {
        let root = unique_temp_root("continuity-bridge-process-stop-test");
        write_fake_bridge_main(&root);

        let mut process = BridgeProcess::spawn(test_config(root.clone())).unwrap();
        process.stop();

        assert!(!process.is_running().unwrap());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn spawn_surfaces_bridge_timeout_when_the_handshake_never_responds() {
        let root = unique_temp_root("continuity-bridge-spawn-timeout-test");
        write_hanging_bridge_main(&root);

        let result = BridgeProcess::spawn_with_timeout(test_config(root.clone()), TEST_TIMEOUT);

        match result {
            Err(error) => assert_eq!(error.code, "bridge_timeout"),
            Ok(_) => panic!("expected spawn to time out waiting for the handshake"),
        }
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn handshake_timeout_terminates_the_hung_process() {
        let root = unique_temp_root("continuity-bridge-handshake-terminate-test");
        write_hanging_bridge_main(&root);

        let (child, stdin, stdout) = super::spawn_child(&test_config(root.clone())).unwrap();
        let mut process = BridgeProcess {
            child,
            stdin: Some(stdin),
            stdout: Some(stdout),
        };

        let result =
            process.request_with_timeout(&json!({"command": "get_workspace_state"}), TEST_TIMEOUT);

        match &result {
            Err(error) => assert_eq!(error.code, "bridge_timeout"),
            Ok(_) => panic!("expected the handshake request to time out"),
        }
        assert!(!process.is_running().unwrap());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn request_after_successful_start_times_out_when_the_process_stops_responding() {
        let root = unique_temp_root("continuity-bridge-request-timeout-test");
        write_bridge_main_that_stops_responding_after_handshake(&root);

        let mut process =
            BridgeProcess::spawn_with_timeout(test_config(root.clone()), TEST_TIMEOUT).unwrap();

        let result = process.request_with_timeout(
            &json!({"command": "send_message", "text": "hello"}),
            TEST_TIMEOUT,
        );

        match &result {
            Err(error) => assert_eq!(error.code, "bridge_timeout"),
            Ok(_) => panic!("expected the second request to time out"),
        }
        assert!(!process.is_running().unwrap());
        fs::remove_dir_all(root).unwrap();
    }
}
