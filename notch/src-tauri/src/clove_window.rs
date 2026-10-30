// The CLOVE window inside this one (the hub's Assistant pages). The CLOVE assistant serves its own window on
// 127.0.0.1 with a token that changes every run, and writes that address to `$XDG_RUNTIME_DIR/clove.url` (a
// directory only this user can read). This reads it, checks that something answers there, and starts CLOVE's
// login service (`clove.service`, from the clove folder's scripts/install_autostart.sh) when it isn't running.

use std::net::{Ipv4Addr, SocketAddr, TcpStream};
use std::path::PathBuf;
use std::time::Duration;

fn url_file() -> PathBuf {
    std::env::var_os("XDG_RUNTIME_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/tmp"))
        .join("clove.url")
}

/// The port of `http://127.0.0.1:<port>/?t=<token>`, the only address CLOVE writes; anything else is refused.
pub fn port_of(url: &str) -> Option<u16> {
    let rest = url.trim().strip_prefix("http://127.0.0.1:")?;
    let (port, token) = rest.split_once("/?t=")?;
    let port: u16 = port.parse().ok()?;
    let token_ok = (8..=128).contains(&token.len())
        && token.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_');
    (port != 0 && token_ok).then_some(port)
}

/// Where CLOVE's window is, if CLOVE is running: the file is there, well formed, and its port answers.
#[tauri::command]
pub fn clove_window_url() -> Option<String> {
    let url = std::fs::read_to_string(url_file()).ok()?;
    let port = port_of(&url)?;
    TcpStream::connect_timeout(&SocketAddr::from((Ipv4Addr::LOCALHOST, port)), Duration::from_millis(300)).ok()?;
    Some(url.trim().to_string())
}

/// Asks systemd to start CLOVE. It returns at once; the page then waits for the window's address to appear.
#[tauri::command]
pub async fn clove_start() -> Result<(), String> {
    #[cfg(target_os = "linux")]
    {
        let out = tauri::async_runtime::spawn_blocking(|| {
            std::process::Command::new("systemctl")
                .args(["--user", "start", "--no-block", "clove.service"])
                .output()
        })
        .await
        .map_err(|e| e.to_string())?
        .map_err(|e| format!("Could not run systemctl: {e}"))?;
        if out.status.success() {
            return Ok(());
        }
        let err = String::from_utf8_lossy(&out.stderr);
        if err.contains("not found") || err.contains("not loaded") {
            return Err("CLOVE's login service isn't installed. Run scripts/install_autostart.sh in the clove folder.".into());
        }
        Err(err.trim().chars().take(240).collect())
    }
    #[cfg(not(target_os = "linux"))]
    {
        Err("Starting CLOVE from here works on Linux only.".into())
    }
}

#[cfg(test)]
mod tests {
    use super::port_of;

    #[test]
    fn reads_the_address_clove_writes() {
        assert_eq!(port_of("http://127.0.0.1:43025/?t=NmTSkAz-HsGZb009GDL8RA\n"), Some(43025));
    }

    #[test]
    fn refuses_anything_else() {
        for bad in [
            "",
            "http://127.0.0.1:43025/",
            "http://127.0.0.1:0/?t=abcdefghij",
            "http://127.0.0.1:99999/?t=abcdefghij",
            "http://localhost:43025/?t=abcdefghij",
            "http://127.0.0.1.evil.com:80/?t=abcdefghij",
            "https://127.0.0.1:43025/?t=abcdefghij",
            "http://127.0.0.1:43025/?t=short",
            "http://127.0.0.1:43025/?t=abcdefghij&x=<script>",
            "http://127.0.0.1:43025/evil?t=abcdefghij",
        ] {
            assert_eq!(port_of(bad), None, "{bad}");
        }
    }
}
