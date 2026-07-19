use crate::errors::DesktopError;
use serde_json::Value;
use std::io::{BufRead, BufReader};
use std::process::ChildStdout;

const MAX_RESPONSE_BYTES: usize = 8 * 1024 * 1024;

pub fn encode_command(command: &Value) -> Result<Vec<u8>, DesktopError> {
    if !command.is_object() {
        return Err(DesktopError::invalid_request());
    }

    let mut encoded = serde_json::to_vec(command).map_err(|_| DesktopError::invalid_request())?;
    encoded.push(b'\n');
    Ok(encoded)
}

pub fn read_response(reader: &mut BufReader<ChildStdout>) -> Result<Value, DesktopError> {
    let line = read_line_limited(reader)?;
    let response: Value =
        serde_json::from_slice(&line).map_err(|_| DesktopError::bridge_protocol_error())?;
    validate_envelope(&response)?;
    Ok(response)
}

fn read_line_limited<R: BufRead>(reader: &mut R) -> Result<Vec<u8>, DesktopError> {
    let mut line = Vec::new();

    loop {
        let available = reader
            .fill_buf()
            .map_err(|_| DesktopError::bridge_read_failed())?;
        if available.is_empty() {
            return Err(DesktopError::bridge_stopped());
        }

        let take = available
            .iter()
            .position(|byte| *byte == b'\n')
            .map_or(available.len(), |index| index + 1);

        if line.len().saturating_add(take) > MAX_RESPONSE_BYTES {
            return Err(DesktopError::bridge_response_too_large());
        }

        line.extend_from_slice(&available[..take]);
        reader.consume(take);

        if line.last() == Some(&b'\n') {
            return Ok(line);
        }
    }
}

fn validate_envelope(response: &Value) -> Result<(), DesktopError> {
    let object = response
        .as_object()
        .ok_or_else(DesktopError::bridge_protocol_error)?;
    let ok = object
        .get("ok")
        .and_then(Value::as_bool)
        .ok_or_else(DesktopError::bridge_protocol_error)?;

    match ok {
        true if object.get("data").is_some() => Ok(()),
        false if object.get("error").is_some() => Ok(()),
        _ => Err(DesktopError::bridge_protocol_error()),
    }
}

#[cfg(test)]
mod tests {
    use super::{encode_command, read_line_limited, validate_envelope};
    use serde_json::json;
    use std::io::BufReader;

    #[test]
    fn command_is_utf8_ndjson() {
        let encoded = encode_command(&json!({"command": "nieznane-Paweł Żółć"})).unwrap();
        assert!(encoded.ends_with(b"\n"));
        assert_eq!(
            std::str::from_utf8(&encoded).unwrap(),
            "{\"command\":\"nieznane-Paweł Żółć\"}\n"
        );
    }

    #[test]
    fn reads_one_line_without_consuming_the_next_response() {
        let input = b"{\"ok\":true,\"command\":\"one\",\"data\":{}}\n{\"ok\":true,\"command\":\"two\",\"data\":{}}\n";
        let mut reader = BufReader::new(&input[..]);
        let first = read_line_limited(&mut reader).unwrap();
        let second = read_line_limited(&mut reader).unwrap();
        assert!(std::str::from_utf8(&first).unwrap().contains("one"));
        assert!(std::str::from_utf8(&second).unwrap().contains("two"));
    }

    #[test]
    fn accepts_only_success_or_failure_envelopes() {
        validate_envelope(&json!({"ok": true, "command": "x", "data": {}})).unwrap();
        validate_envelope(&json!({"ok": false, "command": "x", "error": {}})).unwrap();
        assert!(validate_envelope(&json!({"ok": true, "command": "x"})).is_err());
    }
}
