use crate::bridge::protocol::{encode_command, read_response};
use crate::errors::DesktopError;
use crate::paths::BridgeLaunchConfig;
use serde_json::{json, Value};
use std::env;
use std::ffi::OsString;
use std::io::{BufReader, BufWriter, Write};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

const GRACEFUL_SHUTDOWN_TIMEOUT: Duration = Duration::from_millis(800);
const SHUTDOWN_POLL_INTERVAL: Duration = Duration::from_millis(20);

pub struct BridgeProcess {
    child: Child,
    stdin: Option<BufWriter<ChildStdin>>,
    stdout: Option<BufReader<ChildStdout>>,
}

impl BridgeProcess {
    pub fn spawn(config: BridgeLaunchConfig) -> Result<Self, DesktopError> {
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

        let mut process = Self {
            child,
            stdin: Some(stdin),
            stdout: Some(stdout),
        };
        let handshake = process
            .request(&json!({"command": "get_workspace_state"}))
            .map_err(|_| DesktopError::bridge_start_failed())?;
        if handshake.get("ok").and_then(Value::as_bool) != Some(true) {
            return Err(DesktopError::bridge_start_failed());
        }
        Ok(process)
    }

    pub fn request(&mut self, command: &Value) -> Result<Value, DesktopError> {
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
            .as_mut()
            .ok_or_else(DesktopError::bridge_not_running)?;
        let response = read_response(reader)?;
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
    use super::BridgeProcess;
    use crate::paths::BridgeLaunchConfig;
    use serde_json::json;
    use std::ffi::OsString;
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::time::{SystemTime, UNIX_EPOCH};

    fn unique_temp_root(prefix: &str) -> PathBuf {
        let suffix = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir().join(format!("{prefix}-{}-{suffix}", std::process::id()))
    }

    fn write_fake_bridge_main(root: &Path) {
        let package = root.join("src").join("continuity_ai");
        fs::create_dir_all(&package).unwrap();
        fs::write(package.join("__init__.py"), "").unwrap();
        fs::write(
            package.join("bridge_main.py"),
            r#"import json, sys
for raw in sys.stdin.buffer:
    command = json.loads(raw.decode("utf-8"))
    response = {"ok": True, "command": command["command"], "data": {"echo": command.get("text")}}
    sys.stdout.buffer.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()
"#,
        )
        .unwrap();
    }

    fn test_config(backend_root: PathBuf) -> BridgeLaunchConfig {
        BridgeLaunchConfig {
            python: std::env::var_os("CONTINUITY_PYTHON")
                .unwrap_or_else(|| OsString::from("python")),
            backend_root,
            provider: "fake_aurora".to_owned(),
        }
    }

    #[test]
    fn persistent_process_round_trips_utf8_ndjson() {
        let root = unique_temp_root("continuity-bridge-process-test");
        write_fake_bridge_main(&root);

        let mut process = BridgeProcess::spawn(test_config(root.clone())).unwrap();
        let response = process
            .request(&json!({"command": "send_message", "text": "Paweł Żółć"}))
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
}
