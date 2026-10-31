// CLOVE fork: the Controls page — screenshot, screen recording, stay awake, night light — and the music player
// for whatever is playing (any MPRIS player: Spotify, a browser tab, mpv…).
//
// The four actions use Omarchy's own commands when they are there (the same ones its menu and keys use, so the
// state is shared with the rest of the desktop), and plain tools otherwise: grim + slurp for a screenshot,
// systemd-inhibit for staying awake, hyprsunset for the night light.

use serde::Serialize;
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::Mutex;

/// One of Omarchy's commands, wherever this install keeps them.
fn omarchy(cmd: &str) -> Option<PathBuf> {
    let home = std::env::var_os("HOME").map(PathBuf::from)?;
    let mut dirs = vec![home.join("omarchy/bin"), home.join(".local/share/omarchy/bin")];
    if let Some(path) = std::env::var_os("PATH") {
        dirs.extend(std::env::split_paths(&path));
    }
    dirs.into_iter().map(|d| d.join(cmd)).find(|p| p.is_file())
}

fn has(cmd: &str) -> bool {
    std::env::var_os("PATH")
        .map(|p| std::env::split_paths(&p).any(|d| d.join(cmd).is_file()))
        .unwrap_or(false)
}

/// Starts a command and lets it run on its own (a screenshot picker, a recorder).
fn spawn(program: &std::path::Path, args: &[&str]) -> bool {
    let mut c = Command::new(program);
    c.args(args).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        c.process_group(0);
    }
    c.spawn().is_ok()
}

fn output(program: &std::path::Path, args: &[&str]) -> String {
    Command::new(program)
        .args(args)
        .stdin(Stdio::null())
        .stderr(Stdio::null())
        .output()
        .map(|o| String::from_utf8_lossy(&o.stdout).into_owned())
        .unwrap_or_default()
}

/// The stay-awake fallback (no Omarchy): a systemd-inhibit held for as long as it's on.
static INHIBIT: Mutex<Option<std::process::Child>> = Mutex::new(None);

#[derive(Serialize, Default, Clone)]
pub struct ControlsStatus {
    pub awake: bool,
    pub nightlight: bool,
    pub recording: bool,
}

fn recording_now() -> bool {
    Command::new("pgrep")
        .args(["-x", "gpu-screen-recorder"])
        .stdout(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
        || Command::new("pgrep").args(["-x", "wf-recorder"]).stdout(Stdio::null()).status().map(|s| s.success()).unwrap_or(false)
}

fn status_now() -> ControlsStatus {
    let awake = match omarchy("omarchy-toggle-idle") {
        Some(p) => output(&p, &["status"]).contains("\"enabled\":true"),
        None => INHIBIT.lock().unwrap().is_some(),
    };
    let nightlight = match omarchy("omarchy-toggle-nightlight") {
        Some(p) => output(&p, &["--status"]).contains("\"enabled\":true"),
        None => {
            let t = output(std::path::Path::new("hyprctl"), &["hyprsunset", "temperature"]);
            t.trim().parse::<u32>().map(|k| k < 6000).unwrap_or(false)
        }
    };
    ControlsStatus { awake, nightlight, recording: recording_now() }
}

#[tauri::command]
pub async fn controls_status() -> ControlsStatus {
    tauri::async_runtime::spawn_blocking(status_now).await.unwrap_or_default()
}

/// screenshot | record | awake | nightlight. Returns the state after it.
#[tauri::command]
pub async fn controls_action(action: String) -> ControlsStatus {
    tauri::async_runtime::spawn_blocking(move || {
        match action.as_str() {
            "screenshot" => {
                if let Some(p) = omarchy("omarchy-capture-screenshot") {
                    spawn(&p, &[]);
                } else if has("grim") && has("slurp") {
                    let dir = std::env::var_os("HOME").map(PathBuf::from).unwrap_or_default().join("Pictures");
                    let _ = std::fs::create_dir_all(&dir);
                    let file = dir.join(format!("screenshot-{}.png", chrono_stamp()));
                    let script = format!(
                        "g=$(slurp) && grim -g \"$g\" '{}' && (command -v wl-copy >/dev/null && wl-copy < '{}' || true)",
                        file.display(),
                        file.display()
                    );
                    spawn(std::path::Path::new("sh"), &["-c", &script]);
                }
            }
            "record" => {
                if let Some(p) = omarchy("omarchy-capture-screenrecording") {
                    if recording_now() {
                        spawn(&p, &["--stop-recording"]);
                    } else {
                        spawn(&p, &[]);
                    }
                }
            }
            "awake" => {
                if let Some(p) = omarchy("omarchy-toggle-idle") {
                    let _ = output(&p, &["toggle"]);
                } else {
                    let mut held = INHIBIT.lock().unwrap();
                    if let Some(mut child) = held.take() {
                        let _ = child.kill();
                        let _ = child.wait();
                    } else {
                        *held = Command::new("systemd-inhibit")
                            .args(["--what=idle:sleep", "--who=Clove Notch", "--why=Stay awake", "sleep", "infinity"])
                            .stdin(Stdio::null())
                            .stdout(Stdio::null())
                            .stderr(Stdio::null())
                            .spawn()
                            .ok();
                    }
                }
            }
            "nightlight" => {
                if let Some(p) = omarchy("omarchy-toggle-nightlight") {
                    let _ = output(&p, &[]);
                } else {
                    let on = status_now().nightlight;
                    let _ = output(std::path::Path::new("hyprctl"), &["hyprsunset", "temperature", if on { "6500" } else { "4000" }]);
                }
            }
            _ => {}
        }
        // A recorder takes a moment to start or stop.
        if action == "record" {
            std::thread::sleep(std::time::Duration::from_millis(700));
        }
        status_now()
    })
    .await
    .unwrap_or_default()
}

fn chrono_stamp() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    secs.to_string()
}

/// Opens an https link in Chrome (Chromium if that's what is here), else the default browser.
#[tauri::command]
pub async fn open_in_chrome(url: String) -> bool {
    if !url.starts_with("https://") || url.len() > 2048 {
        return false;
    }
    tauri::async_runtime::spawn_blocking(move || {
        for browser in ["google-chrome-stable", "google-chrome", "chromium", "chromium-browser"] {
            if has(browser) && spawn(std::path::Path::new(browser), &[url.as_str()]) {
                return true;
            }
        }
        spawn(std::path::Path::new("xdg-open"), &[url.as_str()])
    })
    .await
    .unwrap_or(false)
}

// ── Music: whatever MPRIS player is playing ────────────────────────────────────

#[derive(Serialize, Default, Clone)]
pub struct MediaState {
    /// The player's own name (Spotify, Chromium, mpv…).
    pub player: String,
    pub title: String,
    pub artist: String,
    pub playing: bool,
    /// Seconds; 0 when the player doesn't say.
    pub position: f64,
    pub length: f64,
    /// The cover as a data URL (the page may show only data: images), or "".
    pub art: String,
}

/// The last cover read: (its URL, its data URL), so a track's cover is read once.
static ART: Mutex<(String, String)> = Mutex::new((String::new(), String::new()));
const ART_LIMIT: u64 = 3 * 1024 * 1024;

#[cfg(target_os = "linux")]
mod mpris {
    use super::MediaState;
    use dbus::arg::{PropMap, RefArg};
    use dbus::blocking::stdintf::org_freedesktop_dbus::Properties;
    use dbus::blocking::Connection;
    use std::time::Duration;

    const PLAYER: &str = "org.mpris.MediaPlayer2.Player";
    const T: Duration = Duration::from_millis(800);

    fn players(conn: &Connection) -> Vec<String> {
        let proxy = conn.with_proxy("org.freedesktop.DBus", "/org/freedesktop/DBus", T);
        let (names,): (Vec<String>,) = proxy.method_call("org.freedesktop.DBus", "ListNames", ()).unwrap_or_default();
        names.into_iter().filter(|n| n.starts_with("org.mpris.MediaPlayer2.")).collect()
    }

    /// The player to show: one that is playing, else one that is paused, else none.
    fn pick(conn: &Connection) -> Option<(String, bool)> {
        let mut paused = None;
        for name in players(conn) {
            let proxy = conn.with_proxy(name.as_str(), "/org/mpris/MediaPlayer2", T);
            let status: String = proxy.get(PLAYER, "PlaybackStatus").unwrap_or_default();
            if status == "Playing" {
                return Some((name, true));
            }
            if status == "Paused" && paused.is_none() {
                paused = Some((name, false));
            }
        }
        paused
    }

    fn text(v: Option<&dbus::arg::Variant<Box<dyn RefArg>>>) -> String {
        let Some(v) = v else { return String::new() };
        if let Some(s) = v.0.as_str() {
            return s.to_string();
        }
        v.0.as_iter()
            .map(|it| it.filter_map(|x| x.as_str().map(str::to_string)).collect::<Vec<_>>().join(", "))
            .unwrap_or_default()
    }

    pub fn state() -> Option<(MediaState, String)> {
        let conn = Connection::new_session().ok()?;
        let (name, playing) = pick(&conn)?;
        let proxy = conn.with_proxy(name.as_str(), "/org/mpris/MediaPlayer2", T);
        let meta: PropMap = proxy.get(PLAYER, "Metadata").unwrap_or_default();
        let identity: String = proxy.get("org.mpris.MediaPlayer2", "Identity").unwrap_or_default();
        let position: i64 = proxy.get(PLAYER, "Position").unwrap_or(0);
        let length = meta.get("mpris:length").and_then(|v| v.0.as_i64()).unwrap_or(0);
        let art_url = text(meta.get("mpris:artUrl"));
        let title = text(meta.get("xesam:title"));
        if title.is_empty() {
            return None;
        }
        Some((
            MediaState {
                player: if identity.is_empty() { name.trim_start_matches("org.mpris.MediaPlayer2.").to_string() } else { identity },
                title,
                artist: text(meta.get("xesam:artist")),
                playing,
                position: position.max(0) as f64 / 1e6,
                length: length.max(0) as f64 / 1e6,
                art: String::new(),
            },
            art_url,
        ))
    }

    pub fn control(action: &str) -> bool {
        let Ok(conn) = Connection::new_session() else { return false };
        let Some((name, _)) = pick(&conn) else { return false };
        let method = match action {
            "toggle" => "PlayPause",
            "next" => "Next",
            "previous" => "Previous",
            _ => return false,
        };
        let proxy = conn.with_proxy(name.as_str(), "/org/mpris/MediaPlayer2", T);
        proxy.method_call::<(), _, _, _>(PLAYER, method, ()).is_ok()
    }
}

fn data_url(bytes: &[u8]) -> String {
    let mime = if bytes.starts_with(&[0xFF, 0xD8, 0xFF]) {
        "image/jpeg"
    } else if bytes.starts_with(b"\x89PNG") {
        "image/png"
    } else if bytes.len() > 12 && &bytes[8..12] == b"WEBP" {
        "image/webp"
    } else {
        return String::new();
    };
    format!("data:{mime};base64,{}", crate::claude::base64_for(bytes))
}

async fn cover(url: &str) -> String {
    {
        let art = ART.lock().unwrap();
        if art.0 == url {
            return art.1.clone();
        }
    }
    let bytes: Option<Vec<u8>> = if let Some(path) = url.strip_prefix("file://") {
        let path = percent_decode(path);
        std::fs::metadata(&path)
            .ok()
            .filter(|m| m.is_file() && m.len() <= ART_LIMIT)
            .and_then(|_| std::fs::read(&path).ok())
    } else if url.starts_with("https://") && !crate::integrations::PAUSED.load(std::sync::atomic::Ordering::Relaxed) {
        let client = reqwest::Client::builder().timeout(std::time::Duration::from_secs(6)).build().ok();
        match client {
            Some(c) => match c.get(url).send().await {
                Ok(r) if r.content_length().unwrap_or(0) <= ART_LIMIT => r.bytes().await.ok().map(|b| b.to_vec()),
                _ => None,
            },
            None => None,
        }
    } else {
        None
    };
    let out = bytes.filter(|b| b.len() as u64 <= ART_LIMIT).map(|b| data_url(&b)).unwrap_or_default();
    *ART.lock().unwrap() = (url.to_string(), out.clone());
    out
}

fn percent_decode(s: &str) -> String {
    let bytes = s.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' && i + 2 < bytes.len() {
            if let Ok(v) = u8::from_str_radix(&s[i + 1..i + 3], 16) {
                out.push(v);
                i += 3;
                continue;
            }
        }
        out.push(bytes[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// What is playing now, or None.
#[tauri::command]
pub async fn media_state() -> Option<MediaState> {
    #[cfg(target_os = "linux")]
    {
        let (mut state, art_url) = tauri::async_runtime::spawn_blocking(mpris::state).await.ok()??;
        if !art_url.is_empty() {
            state.art = cover(&art_url).await;
        }
        Some(state)
    }
    #[cfg(not(target_os = "linux"))]
    {
        None
    }
}

/// toggle | next | previous, on the player shown.
#[tauri::command]
pub async fn media_control(action: String) -> bool {
    #[cfg(target_os = "linux")]
    {
        tauri::async_runtime::spawn_blocking(move || mpris::control(&action)).await.unwrap_or(false)
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = action;
        false
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn covers_are_sniffed() {
        assert!(data_url(&[0xFF, 0xD8, 0xFF, 0xE0]).starts_with("data:image/jpeg;base64,"));
        assert!(data_url(b"\x89PNG\r\n").starts_with("data:image/png;base64,"));
        assert_eq!(data_url(b"<html>"), "");
    }

    #[test]
    fn file_urls_are_decoded() {
        assert_eq!(percent_decode("/home/ak/My%20Music/c.jpg"), "/home/ak/My Music/c.jpg");
        assert_eq!(percent_decode("/a%2"), "/a%2");
    }
}
