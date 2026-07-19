use crate::errors::DesktopError;
use std::env;
use std::ffi::OsString;
use std::path::{Path, PathBuf};

const BACKEND_ROOT_ENV: &str = "CONTINUITY_BACKEND_ROOT";
const PYTHON_ENV: &str = "CONTINUITY_PYTHON";
const PROVIDER_ENV: &str = "CONTINUITY_REASONING_PROVIDER";

#[derive(Debug, Clone)]
pub struct BridgeLaunchConfig {
    pub python: OsString,
    pub backend_root: PathBuf,
    pub provider: String,
}

impl BridgeLaunchConfig {
    pub fn resolve() -> Result<Self, DesktopError> {
        let backend_root = resolve_backend_root()?;
        let python = env::var_os(PYTHON_ENV).unwrap_or_else(|| OsString::from("python"));
        let provider = env::var(PROVIDER_ENV)
            .ok()
            .filter(|value| matches!(value.as_str(), "deterministic_offline" | "openai"))
            .ok_or_else(DesktopError::provider_not_configured)?;

        Ok(Self {
            python,
            backend_root,
            provider,
        })
    }
}

pub fn resolve_backend_root() -> Result<PathBuf, DesktopError> {
    if let Some(explicit) = env::var_os(BACKEND_ROOT_ENV) {
        let candidate = PathBuf::from(explicit);
        if is_backend_root(&candidate) {
            return canonical_or_original(candidate);
        }
        return Err(DesktopError::backend_root_not_found());
    }

    if let Ok(current_dir) = env::current_dir() {
        if let Some(root) = find_backend_root(&current_dir) {
            return canonical_or_original(root);
        }
    }

    if let Ok(executable) = env::current_exe() {
        if let Some(parent) = executable.parent() {
            if let Some(root) = find_backend_root(parent) {
                return canonical_or_original(root);
            }
        }
    }

    Err(DesktopError::backend_root_not_found())
}

fn canonical_or_original(path: PathBuf) -> Result<PathBuf, DesktopError> {
    Ok(path.canonicalize().unwrap_or(path))
}

fn find_backend_root(start: &Path) -> Option<PathBuf> {
    start
        .ancestors()
        .take(8)
        .find(|candidate| is_backend_root(candidate))
        .map(Path::to_path_buf)
}

fn is_backend_root(candidate: &Path) -> bool {
    candidate.join("pyproject.toml").is_file()
        && candidate
            .join("src")
            .join("continuity_ai")
            .join("bridge_main.py")
            .is_file()
}

#[cfg(test)]
mod tests {
    use super::find_backend_root;
    use std::fs;

    #[test]
    fn finds_backend_from_nested_desktop_directory() {
        let root =
            std::env::temp_dir().join(format!("continuity-path-test-{}", std::process::id()));
        let nested = root.join("desktop").join("src-tauri");
        fs::create_dir_all(root.join("src").join("continuity_ai")).unwrap();
        fs::create_dir_all(&nested).unwrap();
        fs::write(root.join("pyproject.toml"), "[project]\n").unwrap();
        fs::write(
            root.join("src")
                .join("continuity_ai")
                .join("bridge_main.py"),
            "",
        )
        .unwrap();

        assert_eq!(find_backend_root(&nested), Some(root.clone()));
        fs::remove_dir_all(root).unwrap();
    }
}
