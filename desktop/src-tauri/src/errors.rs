use serde::Serialize;
use std::fmt::{Display, Formatter};

#[derive(Debug, Clone, Serialize)]
pub struct DesktopError {
    pub code: &'static str,
    pub message: &'static str,
}

impl DesktopError {
    pub const fn new(code: &'static str, message: &'static str) -> Self {
        Self { code, message }
    }

    pub const fn bridge_not_running() -> Self {
        Self::new(
            "bridge_not_running",
            "Continuity AI could not connect to the local analysis process.",
        )
    }

    pub const fn bridge_already_running() -> Self {
        Self::new(
            "bridge_already_running",
            "The local analysis process is already running.",
        )
    }

    pub const fn bridge_start_failed() -> Self {
        Self::new(
            "bridge_start_failed",
            "Continuity AI could not start the local analysis process.",
        )
    }

    pub const fn bridge_stopped() -> Self {
        Self::new(
            "bridge_stopped",
            "The local analysis process stopped unexpectedly.",
        )
    }

    pub const fn bridge_write_failed() -> Self {
        Self::new(
            "bridge_write_failed",
            "Continuity AI could not send the request to the local analysis process.",
        )
    }

    pub const fn bridge_read_failed() -> Self {
        Self::new(
            "bridge_read_failed",
            "Continuity AI could not read the local analysis response.",
        )
    }

    pub const fn bridge_protocol_error() -> Self {
        Self::new(
            "bridge_protocol_error",
            "The local analysis process returned an invalid response.",
        )
    }

    pub const fn bridge_response_too_large() -> Self {
        Self::new(
            "bridge_response_too_large",
            "The local analysis response exceeded the supported size.",
        )
    }

    pub const fn backend_root_not_found() -> Self {
        Self::new(
            "backend_root_not_found",
            "Continuity AI could not locate its local analysis backend.",
        )
    }

    pub const fn provider_not_configured() -> Self {
        Self::new(
            "provider_not_configured",
            "The local analysis provider is not configured.",
        )
    }

    pub const fn invalid_request() -> Self {
        Self::new(
            "invalid_request",
            "The desktop application produced an invalid local request.",
        )
    }

    pub const fn internal_state_error() -> Self {
        Self::new(
            "internal_state_error",
            "Continuity AI could not access the local analysis session.",
        )
    }
}

impl Display for DesktopError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(self.message)
    }
}

impl std::error::Error for DesktopError {}
