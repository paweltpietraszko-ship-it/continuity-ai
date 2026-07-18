#![cfg(test)]

use crate::paths::BridgeLaunchConfig;
use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

pub(crate) fn unique_temp_root(prefix: &str) -> PathBuf {
    let suffix = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    std::env::temp_dir().join(format!("{prefix}-{}-{suffix}", std::process::id()))
}

pub(crate) fn test_config(backend_root: PathBuf) -> BridgeLaunchConfig {
    BridgeLaunchConfig {
        python: std::env::var_os("CONTINUITY_PYTHON").unwrap_or_else(|| OsString::from("python")),
        backend_root,
        provider: "fake_aurora".to_owned(),
    }
}

fn write_backend_package(root: &Path, body: &str) {
    let package = root.join("src").join("continuity_ai");
    fs::create_dir_all(&package).unwrap();
    fs::write(package.join("__init__.py"), "").unwrap();
    fs::write(package.join("bridge_main.py"), body).unwrap();
}

/// Always echoes back a well-formed response for every request.
pub(crate) fn write_fake_bridge_main(root: &Path) {
    write_backend_package(
        root,
        r#"import json, sys
for raw in sys.stdin.buffer:
    command = json.loads(raw.decode("utf-8"))
    response = {"ok": True, "command": command["command"], "data": {"echo": command.get("text")}}
    sys.stdout.buffer.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()
"#,
    );
}

/// Starts and reads each request but never writes a response — simulates a
/// hung Bridge, including on the very first (handshake) request.
pub(crate) fn write_hanging_bridge_main(root: &Path) {
    write_backend_package(
        root,
        r#"import sys
for _raw in sys.stdin.buffer:
    pass
"#,
    );
}

/// Answers the first request (the handshake) correctly, then silently
/// consumes every later request without ever responding again.
pub(crate) fn write_bridge_main_that_stops_responding_after_handshake(root: &Path) {
    write_backend_package(
        root,
        r#"import json, sys
answered = False
for raw in sys.stdin.buffer:
    command = json.loads(raw.decode("utf-8"))
    if not answered:
        answered = True
        response = {"ok": True, "command": command["command"], "data": {"echo": command.get("text")}}
        sys.stdout.buffer.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
        sys.stdout.buffer.flush()
"#,
    );
}
