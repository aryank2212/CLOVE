// Live Activities (src/core/live.ts): everything Clove Notch shows around the
// pill that does not come from a coding agent. This side only gathers — what
// plays (media.rs), what the machine is doing (system.rs), what just happened
// (watch.rs), a voice memo, and the few public web services the cards read
// (quotes, scores, routes). What any of it means is decided on the page.
//
// Linux only: every source is a Linux one. On Windows the commands answer with
// nothing and the activities that need them simply never appear.

#[cfg(target_os = "linux")]
mod media;
#[cfg(target_os = "linux")]
mod system;
#[cfg(target_os = "linux")]
mod watch;

use std::time::Duration;

use serde_json::{json, Value};
use tauri::AppHandle;

#[cfg(target_os = "linux")]
static STARTED: std::sync::Once = std::sync::Once::new();

/// Starts the watchers (once) and answers with what is already known, for a
/// page that has just loaded.
#[tauri::command]
pub fn live_start(app: AppHandle) -> Value {
    #[cfg(target_os = "linux")]
    {
        STARTED.call_once(|| {
            media::start(app.clone());
            system::start(app.clone());
            watch::start(app.clone());
            crate::log::line("live activities: watching players, devices and notifications");
        });
        json!({ "media": media::snapshot(&app), "system": system::snapshot() })
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = app;
        json!({ "media": [], "system": null })
    }
}

#[tauri::command]
pub async fn live_media_control(app: AppHandle, bus: String, action: String, value: Option<f64>) -> bool {
    #[cfg(target_os = "linux")]
    {
        tauri::async_runtime::spawn_blocking(move || media::control(&app, &bus, &action, value)).await.unwrap_or(false)
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = (app, bus, action, value);
        false
    }
}

/// The handful of things a card's button does to the machine.
#[tauri::command]
pub async fn live_action(app: AppHandle, action: String, arg: Option<String>) -> Value {
    #[cfg(target_os = "linux")]
    {
        tauri::async_runtime::spawn_blocking(move || imp::action(&app, &action, arg.as_deref().unwrap_or_default()))
            .await
            .unwrap_or(Value::Null)
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = (app, action, arg);
        Value::Null
    }
}

// ── The web services the cards read ───────────────────────────────────────────

const BROWSER_AGENT: &str = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";
const MAX_ANSWER: usize = 4 * 1024 * 1024;

/// The address for one kind of question. The page never passes an address:
/// only a kind and a short argument, which is checked here.
pub fn endpoint(kind: &str, arg: &str) -> Option<String> {
    let symbol_ok = |s: &str| !s.is_empty() && s.len() <= 240 && s.chars().all(|c| c.is_ascii_alphanumeric() || ".=@&-|^".contains(c));
    let encode = |s: &str| -> String {
        s.bytes()
            .map(|b| if b.is_ascii_alphanumeric() || b"-_.~".contains(&b) { (b as char).to_string() } else { format!("%{b:02X}") })
            .collect()
    };
    match kind {
        // CNBC's quote service: US and Indian stocks, indices, crypto, no key.
        "quote" if symbol_ok(arg) => Some(format!(
            "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols={}&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json",
            encode(arg)
        )),
        "bars" if symbol_ok(arg) && !arg.contains('|') => Some(format!("https://ts-api.cnbc.com/harmony/app/charts/1D.json?symbol={}", encode(arg))),
        // ESPN's scoreboard header: every match of a sport, live or not.
        "scores" if !arg.is_empty() && arg.len() <= 20 && arg.chars().all(|c| c.is_ascii_lowercase()) => {
            Some(format!("https://site.web.api.espn.com/apis/v2/scoreboard/header?sport={arg}"))
        }
        "geocode" if !arg.trim().is_empty() && arg.len() <= 200 => Some(format!(
            "https://nominatim.openstreetmap.org/search?q={}&format=json&limit=1",
            encode(arg.trim())
        )),
        // "lon,lat;lon,lat"
        "route" if !arg.is_empty() && arg.len() <= 80 && arg.chars().all(|c| c.is_ascii_digit() || ".,;-".contains(c)) && arg.contains(';') => Some(format!(
            "https://router.project-osrm.org/route/v1/driving/{arg}?overview=simplified&steps=true"
        )),
        "whereami" => Some("https://ipapi.co/json/".to_string()),
        _ => None,
    }
}

/// One question to one of the public services above; the answer as text.
#[tauri::command]
pub async fn live_fetch(kind: String, arg: Option<String>) -> Result<String, String> {
    let arg = arg.unwrap_or_default();
    let url = endpoint(&kind, &arg).ok_or_else(|| "not a question the notch asks".to_string())?;
    // Nominatim asks for an agent that names the app; the others want a browser's.
    let agent = if kind == "geocode" { concat!("clove-notch/", env!("CARGO_PKG_VERSION")) } else { BROWSER_AGENT };
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(12))
        .user_agent(agent)
        .build()
        .map_err(|e| e.to_string())?;
    let response = client.get(&url).send().await.map_err(|e| e.to_string())?;
    if !response.status().is_success() {
        return Err(format!("the service answered {}", response.status().as_u16()));
    }
    let bytes = crate::net::read_capped(response, MAX_ANSWER).await?;
    Ok(String::from_utf8_lossy(&bytes).into_owned())
}

#[cfg(target_os = "linux")]
mod imp {
    use std::io::{Read, Seek, SeekFrom};
    use std::path::PathBuf;
    use std::process::{Child, Command, Stdio};
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::{Arc, Mutex};
    use std::time::{Duration, Instant};

    use serde_json::{json, Value};
    use tauri::{AppHandle, Emitter};

    use super::system;
    use crate::island::WINDOW_LABEL;

    struct Memo {
        child: Child,
        path: PathBuf,
        started: Instant,
        stop: Arc<AtomicBool>,
    }

    static MEMO: Mutex<Option<Memo>> = Mutex::new(None);

    pub fn action(app: &AppHandle, action: &str, arg: &str) -> Value {
        match action {
            "memo-start" => memo_start(app),
            "memo-stop" => memo_stop(app),
            "stop-recording" => {
                let ok = arg.parse::<u32>().ok().filter(|pid| system::is_recorder(*pid)).is_some_and(|pid| {
                    // SIGINT: the recorder finishes its file, as Ctrl+C would.
                    unsafe { libc::kill(pid as i32, libc::SIGINT) == 0 }
                });
                json!(ok)
            }
            "hotspot-off" => json!(system::hotspot_off()),
            "lock" => json!(Command::new("loginctl").arg("lock-session").status().is_ok_and(|s| s.success())),
            "reveal" => {
                // Only what a memo wrote: its folder.
                let dir = memo_dir();
                let target = PathBuf::from(arg);
                if target.starts_with(&dir) {
                    crate::platform::reveal_folder(&dir.to_string_lossy());
                }
                json!(true)
            }
            "play-file" => {
                let target = PathBuf::from(arg);
                if target.starts_with(memo_dir()) && target.is_file() {
                    let _ = Command::new("xdg-open").arg(&target).spawn();
                }
                json!(true)
            }
            // "Accept" on a call: bring its app forward (Hyprland), where it is answered.
            "focus-app" => json!(focus_app(arg)),
            _ => Value::Null,
        }
    }

    /// Brings forward the window of an app named `name` (by its class, else its title), on Hyprland: the Lua
    /// dispatcher of 0.56 and later first, then the classic one.
    fn focus_app(name: &str) -> bool {
        let want = name.trim().to_ascii_lowercase();
        let word = want.split_whitespace().next().unwrap_or_default().to_string();
        if word.is_empty() {
            return false;
        }
        let Ok(out) = Command::new("hyprctl").args(["clients", "-j"]).output() else { return false };
        let clients: Vec<Value> = serde_json::from_slice(&out.stdout).unwrap_or_default();
        let text = |c: &Value, k: &str| c[k].as_str().unwrap_or_default().to_ascii_lowercase();
        let hit = clients
            .iter()
            .find(|c| text(c, "class").contains(&word) || text(c, "initialClass").contains(&word))
            .or_else(|| clients.iter().find(|c| text(c, "title").contains(&word)));
        let Some(address) = hit.and_then(|c| c["address"].as_str()) else { return false };
        // An address is all hex: nothing else reaches the dispatcher.
        if !address.starts_with("0x") || !address[2..].chars().all(|c| c.is_ascii_hexdigit()) {
            return false;
        }
        let dispatch = |args: &[&str]| {
            Command::new("hyprctl").args(args).output().map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string()).unwrap_or_default()
        };
        let lua = format!("hl.dsp.focus({{ window = \"address:{address}\" }})");
        dispatch(&["dispatch", &lua]) == "ok" || dispatch(&["dispatch", "focuswindow", &format!("address:{address}")]).contains("ok")
    }

    fn memo_dir() -> PathBuf {
        let home = PathBuf::from(std::env::var_os("HOME").unwrap_or_default());
        home.join("Music").join("Voice Memos")
    }

    fn memo_start(app: &AppHandle) -> Value {
        let mut memo = MEMO.lock().unwrap();
        if memo.is_some() {
            return json!({ "error": "already recording" });
        }
        let dir = memo_dir();
        if std::fs::create_dir_all(&dir).is_err() {
            return json!({ "error": "cannot create the Voice Memos folder" });
        }
        let t = crate::platform::local_time();
        let path = dir.join(format!(
            "Memo {:04}-{:02}-{:02} {:02}.{:02}.{:02}.wav",
            t.year, t.month, t.day, t.hour, t.minute, t.second
        ));
        let child = Command::new("pw-record")
            .args(["--rate", "44100", "--channels", "1", "--format", "s16"])
            .arg(&path)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn();
        let child = match child {
            Ok(c) => c,
            Err(err) => return json!({ "error": format!("cannot record (pw-record): {err}") }),
        };
        let stop = Arc::new(AtomicBool::new(false));
        meter(app.clone(), path.clone(), stop.clone());
        *memo = Some(Memo { child, path: path.clone(), started: Instant::now(), stop });
        json!({ "path": path.to_string_lossy() })
    }

    fn memo_stop(app: &AppHandle) -> Value {
        let Some(mut memo) = MEMO.lock().unwrap().take() else { return json!({ "error": "not recording" }) };
        memo.stop.store(true, Ordering::Relaxed);
        // SIGINT lets pw-record write the WAV header's final length.
        unsafe { libc::kill(memo.child.id() as i32, libc::SIGINT) };
        let _ = memo.child.wait();
        let seconds = memo.started.elapsed().as_secs_f64();
        let saved = json!({ "path": memo.path.to_string_lossy(), "seconds": seconds });
        let _ = app.emit_to(WINDOW_LABEL, "live-memo", json!({ "saved": saved }));
        saved
    }

    /// The input level, ten times a second, from the tail of the file being written.
    fn meter(app: AppHandle, path: PathBuf, stop: Arc<AtomicBool>) {
        let _ = std::thread::Builder::new().name("clove-live-memo".into()).spawn(move || {
            const WINDOW: u64 = 8820; // 100 ms of 44.1 kHz mono s16
            let mut buf = vec![0u8; WINDOW as usize];
            while !stop.load(Ordering::Relaxed) {
                std::thread::sleep(Duration::from_millis(100));
                let Ok(mut file) = std::fs::File::open(&path) else { continue };
                let len = file.metadata().map(|m| m.len()).unwrap_or(0);
                if len < WINDOW + 44 {
                    continue;
                }
                let start = (len - WINDOW) & !1;
                if file.seek(SeekFrom::Start(start)).is_err() || file.read_exact(&mut buf).is_err() {
                    continue;
                }
                let mut sum = 0f64;
                for pair in buf.chunks_exact(2) {
                    let s = i16::from_le_bytes([pair[0], pair[1]]) as f64 / 32768.0;
                    sum += s * s;
                }
                let rms = (sum / (WINDOW as f64 / 2.0)).sqrt();
                // Speech sits around 0.05–0.2 RMS: stretch it over the bar.
                let level = (rms * 6.0).min(1.0);
                let _ = app.emit_to(WINDOW_LABEL, "live-memo", json!({ "level": level }));
            }
        });
    }
}

#[cfg(test)]
mod tests {
    use super::endpoint;

    #[test]
    fn only_the_known_questions_get_an_address() {
        assert!(endpoint("quote", "TSLA|RELIANCE-IN|.NSEI|BTC.CM=").unwrap().starts_with("https://quote.cnbc.com/"));
        assert!(endpoint("bars", "TSLA").unwrap().ends_with("symbol=TSLA"));
        assert!(endpoint("scores", "cricket").unwrap().ends_with("sport=cricket"));
        assert!(endpoint("route", "77.2090,28.6139;77.1025,28.7041").unwrap().contains("/driving/77.2090,28.6139;77.1025,28.7041?"));
        assert!(endpoint("geocode", "India Gate, Delhi").unwrap().contains("q=India%20Gate%2C%20Delhi"));
        assert_eq!(endpoint("quote", "TSLA/../x"), None);
        assert_eq!(endpoint("bars", "A|B"), None);
        assert_eq!(endpoint("scores", "cricket&x=1"), None);
        assert_eq!(endpoint("route", "77.2,28.6"), None);
        assert_eq!(endpoint("route", "a;b"), None);
        assert_eq!(endpoint("fetch", "https://example.com"), None);
    }
}
