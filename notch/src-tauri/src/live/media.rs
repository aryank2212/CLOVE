// Now playing, for Clove Notch's media activity: every MPRIS player on the
// session bus (Spotify, a browser tab playing YouTube or Apple Music, mpv,
// VLC…), not only Spotify as the pill in spotify.rs. One thread listens for
// players coming, going and changing; each change re-reads that player and the
// whole list goes to the page as `live-media`.

use std::collections::HashMap;
use std::sync::Mutex;
use std::time::Duration;

use dbus::arg::{PropMap, RefArg};
use dbus::blocking::stdintf::org_freedesktop_dbus::Properties;
use dbus::blocking::Connection;
use dbus::Message;
use serde::Serialize;
use tauri::{AppHandle, Emitter};

use crate::island::WINDOW_LABEL;

const PREFIX: &str = "org.mpris.MediaPlayer2.";
const PATH: &str = "/org/mpris/MediaPlayer2";
const PLAYER: &str = "org.mpris.MediaPlayer2.Player";
const CALL: Duration = Duration::from_millis(1500);
/// A cover bigger than this is not a cover.
const MAX_ART: usize = 6 * 1024 * 1024;

#[derive(Serialize, Clone, Default, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct Player {
    bus: String,
    app: String,
    source: String,
    title: String,
    artist: String,
    album: String,
    art_url: Option<String>,
    url: String,
    duration: f64,
    position: f64,
    position_at: f64,
    playing: bool,
    can_next: bool,
    can_prev: bool,
    can_seek: bool,
    #[serde(skip)]
    track_path: String,
}

#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
struct Artwork {
    art_url: String,
    data_url: String,
}

static PLAYERS: Mutex<Vec<Player>> = Mutex::new(Vec::new());
/// The cover last sent, so a play/pause does not fetch it again.
static LAST_ART: Mutex<String> = Mutex::new(String::new());

fn now_ms() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs_f64() * 1000.0)
        .unwrap_or(0.0)
}

fn text(map: &PropMap, key: &str) -> String {
    let Some(v) = map.get(key) else { return String::new() };
    if let Some(s) = v.0.as_str() {
        return s.to_string();
    }
    // xesam:artist is a list of names.
    v.0.as_iter()
        .map(|it| it.filter_map(|x| x.as_str().map(str::to_string)).collect::<Vec<_>>().join(", "))
        .unwrap_or_default()
}

fn number(map: &PropMap, key: &str) -> f64 {
    map.get(key)
        .and_then(|v| v.0.as_i64().map(|n| n as f64).or_else(|| v.0.as_u64().map(|n| n as f64)).or_else(|| v.0.as_f64()))
        .unwrap_or(0.0)
}

fn flag(map: &PropMap, key: &str) -> bool {
    map.get(key).and_then(|v| v.0.as_i64()).is_some_and(|n| n != 0)
}

/// Which service a player is, from its bus name, the track's address and — for
/// a browser, which says neither — the title of the tab that plays it.
pub fn source_of(bus: &str, url: &str, window_titles: &[String], title: &str) -> &'static str {
    let name = bus.trim_start_matches(PREFIX).to_ascii_lowercase();
    if name.starts_with("spotify") || name.contains("spotifyd") || name.contains("ncspot") {
        return "spotify";
    }
    let by_text = |hay: &str| -> Option<&'static str> {
        let h = hay.to_ascii_lowercase();
        if h.contains("music.youtube") || h.contains("youtube music") {
            Some("ytmusic")
        } else if h.contains("youtube.com") || h.contains("youtu.be") || h.ends_with("- youtube") || h.contains("- youtube -") || h.contains("- youtube —") {
            Some("youtube")
        } else if h.contains("music.apple") || h.contains("apple music") {
            Some("applemusic")
        } else if h.contains("open.spotify") || h.contains("spotify – ") || h.contains("spotify - ") {
            Some("spotify")
        } else {
            None
        }
    };
    if let Some(s) = by_text(url) {
        return s;
    }
    let browser = ["chrom", "firefox", "brave", "zen", "vivaldi", "edge", "opera", "librewolf", "plasma-browser"]
        .iter()
        .any(|b| name.contains(b));
    if browser {
        // The tab's window says "<video title> - YouTube - <browser>".
        let wanted = title.to_ascii_lowercase();
        let tab = window_titles
            .iter()
            .filter(|t| !wanted.is_empty() && t.to_ascii_lowercase().contains(&wanted))
            .find_map(|t| by_text(t))
            .or_else(|| window_titles.iter().find_map(|t| by_text(t)));
        return tab.unwrap_or("browser");
    }
    if ["vlc", "mpv", "celluloid", "totem", "haruna", "smplayer", "kodi"].iter().any(|v| name.contains(v)) {
        return "video";
    }
    "music"
}

/// Window titles, where the compositor tells (Hyprland). Empty elsewhere.
fn window_titles() -> Vec<String> {
    let Ok(out) = std::process::Command::new("hyprctl").args(["clients", "-j"]).output() else { return Vec::new() };
    let Ok(v) = serde_json::from_slice::<serde_json::Value>(&out.stdout) else { return Vec::new() };
    v.as_array()
        .map(|a| a.iter().filter_map(|c| c.get("title").and_then(|t| t.as_str()).map(str::to_string)).collect())
        .unwrap_or_default()
}

fn read_player(conn: &Connection, bus: &str, known: Option<&Player>) -> Option<Player> {
    let proxy = conn.with_proxy(bus, PATH, CALL);
    let props: PropMap = proxy.get_all(PLAYER).ok()?;
    let meta: PropMap = proxy.get(PLAYER, "Metadata").unwrap_or_default();
    let title = text(&meta, "xesam:title");
    let url = text(&meta, "xesam:url");
    let track_path = meta.get("mpris:trackid").map(|v| v.0.as_str().unwrap_or_default().to_string()).unwrap_or_default();
    if title.is_empty() && url.is_empty() {
        return None;
    }
    let app: String = proxy.get("org.mpris.MediaPlayer2", "Identity").unwrap_or_default();
    let status = props.get("PlaybackStatus").and_then(|v| v.0.as_str()).unwrap_or_default().to_string();
    // The tab is only looked up when the track changes: it spawns hyprctl.
    let source = match known {
        Some(k) if k.title == title && k.source != "browser" => k.source.clone(),
        _ => {
            let direct = source_of(bus, &url, &[], &title);
            if direct == "browser" { source_of(bus, &url, &window_titles(), &title) } else { direct }.to_string()
        }
    };
    let art = text(&meta, "mpris:artUrl");
    Some(Player {
        bus: bus.to_string(),
        app,
        source,
        title: if title.is_empty() { url.rsplit('/').next().unwrap_or_default().to_string() } else { title },
        artist: text(&meta, "xesam:artist"),
        album: text(&meta, "xesam:album"),
        art_url: (!art.is_empty()).then_some(art),
        url,
        duration: number(&meta, "mpris:length") / 1_000_000.0,
        position: number(&props, "Position") / 1_000_000.0,
        position_at: now_ms(),
        playing: status == "Playing",
        can_next: flag(&props, "CanGoNext"),
        can_prev: flag(&props, "CanGoPrevious"),
        can_seek: flag(&props, "CanSeek"),
        track_path,
    })
}

fn emit(app: &AppHandle) {
    let players = PLAYERS.lock().unwrap().clone();
    // The cover of whichever plays, else of the first.
    if let Some(art) = players.iter().find(|p| p.playing).or(players.first()).and_then(|p| p.art_url.clone()) {
        want_artwork(app, art);
    }
    let _ = app.emit_to(WINDOW_LABEL, "live-media", &players);
}

fn want_artwork(app: &AppHandle, url: String) {
    {
        let mut last = LAST_ART.lock().unwrap();
        if *last == url {
            return;
        }
        *last = url.clone();
    }
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        let bytes = if let Some(path) = url.strip_prefix("file://") {
            let path = percent_decode(path);
            std::fs::metadata(&path).ok().filter(|m| m.len() as usize <= MAX_ART).and_then(|_| std::fs::read(&path).ok())
        } else if url.starts_with("https://") {
            fetch(&url).await
        } else if let Some(b64) = url.strip_prefix("data:").and_then(|d| d.split_once(";base64,")) {
            // Already a data URL (some players inline the cover).
            let _ = b64;
            let _ = app.emit_to(WINDOW_LABEL, "live-art", Artwork { art_url: url.clone(), data_url: url });
            return;
        } else {
            None
        };
        let Some(bytes) = bytes else { return };
        let Some(mime) = crate::spotify::sniff_image(&bytes) else { return };
        let data_url = format!("data:{mime};base64,{}", crate::claude::base64_for(&bytes));
        let _ = app.emit_to(WINDOW_LABEL, "live-art", Artwork { art_url: url, data_url });
    });
}

async fn fetch(url: &str) -> Option<Vec<u8>> {
    let client = reqwest::Client::builder().timeout(Duration::from_secs(8)).build().ok()?;
    let response = client.get(url).send().await.ok()?.error_for_status().ok()?;
    crate::net::read_capped(response, MAX_ART).await.ok()
}

fn percent_decode(s: &str) -> String {
    let bytes = s.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' && i + 2 < bytes.len() {
            if let Ok(b) = u8::from_str_radix(&s[i + 1..i + 3], 16) {
                out.push(b);
                i += 3;
                continue;
            }
        }
        out.push(bytes[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

fn list_players(conn: &Connection) -> Vec<String> {
    let proxy = conn.with_proxy("org.freedesktop.DBus", "/org/freedesktop/DBus", CALL);
    let names: Result<(Vec<String>,), _> = proxy.method_call("org.freedesktop.DBus", "ListNames", ());
    names
        .map(|(n,)| n.into_iter().filter(|n| n.starts_with(PREFIX) && !n.contains("playerctld") && !n.contains("kdeconnect")).collect())
        .unwrap_or_default()
}

fn owner_of(conn: &Connection, bus: &str) -> Option<String> {
    let proxy = conn.with_proxy("org.freedesktop.DBus", "/org/freedesktop/DBus", CALL);
    let r: Result<(String,), _> = proxy.method_call("org.freedesktop.DBus", "GetNameOwner", (bus,));
    r.ok().map(|(o,)| o)
}

/// Re-reads one player into the shared list. True when the list changed.
fn refresh(conn: &Connection, bus: &str) -> bool {
    let known = PLAYERS.lock().unwrap().iter().find(|p| p.bus == bus).cloned();
    let next = read_player(conn, bus, known.as_ref());
    let mut players = PLAYERS.lock().unwrap();
    let at = players.iter().position(|p| p.bus == bus);
    match (at, next) {
        (Some(i), Some(p)) => {
            players[i] = p;
            true
        }
        (None, Some(p)) => {
            players.push(p);
            true
        }
        (Some(i), None) => {
            players.remove(i);
            true
        }
        (None, None) => false,
    }
}

pub fn start(app: AppHandle) {
    let _ = std::thread::Builder::new().name("clove-live-media".into()).spawn(move || loop {
        listen(&app);
        // The bus went away (a session restart): try again, slowly.
        std::thread::sleep(Duration::from_secs(5));
    });
}

fn listen(app: &AppHandle) {
    let Ok(conn) = Connection::new_session() else { return };
    let rules = [
        "type='signal',sender='org.freedesktop.DBus',interface='org.freedesktop.DBus',member='NameOwnerChanged',arg0namespace='org.mpris.MediaPlayer2'",
        "type='signal',path='/org/mpris/MediaPlayer2',interface='org.freedesktop.DBus.Properties',member='PropertiesChanged'",
        "type='signal',path='/org/mpris/MediaPlayer2',interface='org.mpris.MediaPlayer2.Player',member='Seeked'",
    ];
    for rule in rules {
        let _ = conn.add_match_no_cb(rule);
    }
    // Signals come from a connection's unique name: which player is that?
    let mut owners: HashMap<String, String> = HashMap::new();
    PLAYERS.lock().unwrap().clear();
    for bus in list_players(&conn) {
        if let Some(owner) = owner_of(&conn, &bus) {
            owners.insert(owner, bus.clone());
        }
        refresh(&conn, &bus);
    }
    emit(app);

    loop {
        match conn.channel().blocking_pop_message(Duration::from_secs(30)) {
            Ok(Some(msg)) => {
                if handle(&conn, &mut owners, &msg) {
                    emit(app);
                }
            }
            Ok(None) => {}
            Err(_) => return,
        }
    }
}

fn handle(conn: &Connection, owners: &mut HashMap<String, String>, msg: &Message) -> bool {
    let member = msg.member().map(|m| m.to_string()).unwrap_or_default();
    if member == "NameOwnerChanged" {
        let Ok((name, _old, new)) = msg.read3::<String, String, String>() else { return false };
        if !name.starts_with(PREFIX) || name.contains("playerctld") || name.contains("kdeconnect") {
            return false;
        }
        owners.retain(|_, bus| *bus != name);
        if new.is_empty() {
            let mut players = PLAYERS.lock().unwrap();
            let before = players.len();
            players.retain(|p| p.bus != name);
            return players.len() != before;
        }
        owners.insert(new, name.clone());
        return refresh(conn, &name);
    }
    let Some(sender) = msg.sender().map(|s| s.to_string()) else { return false };
    let Some(bus) = owners.get(&sender).cloned() else { return false };
    refresh(conn, &bus)
}

/// Play, pause, skip, seek on one player. Runs on its own connection: the
/// listener's is busy waiting.
pub fn control(app: &AppHandle, bus: &str, action: &str, value: Option<f64>) -> bool {
    if !bus.starts_with(PREFIX) {
        return false;
    }
    let Ok(conn) = Connection::new_session() else { return false };
    let proxy = conn.with_proxy(bus, PATH, CALL);
    let call = |method: &str| proxy.method_call::<(), _, _, _>(PLAYER, method, ()).is_ok();
    let ok = match action {
        "toggle" => call("PlayPause"),
        "play" => call("Play"),
        "pause" => call("Pause"),
        "next" => call("Next"),
        "previous" => call("Previous"),
        "seek" => {
            let Some(seconds) = value else { return false };
            let track = PLAYERS.lock().unwrap().iter().find(|p| p.bus == bus).map(|p| p.track_path.clone()).unwrap_or_default();
            match dbus::Path::new(track) {
                Ok(path) => proxy
                    .method_call::<(), _, _, _>(PLAYER, "SetPosition", (path, (seconds * 1_000_000.0) as i64))
                    .is_ok(),
                Err(_) => false,
            }
        }
        "raise" => proxy.method_call::<(), _, _, _>("org.mpris.MediaPlayer2", "Raise", ()).is_ok(),
        _ => false,
    };
    // Browsers do not always signal a seek or a skip: read it back.
    if ok {
        std::thread::sleep(Duration::from_millis(180));
        if refresh(&conn, bus) {
            emit(app);
        }
    }
    ok
}

/// The list as it is now, and the current cover again (the page just loaded).
pub fn snapshot(app: &AppHandle) -> Vec<Player> {
    LAST_ART.lock().unwrap().clear();
    let players = PLAYERS.lock().unwrap().clone();
    if let Some(art) = players.iter().find(|p| p.playing).or(players.first()).and_then(|p| p.art_url.clone()) {
        want_artwork(app, art);
    }
    players
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_player_is_named_for_its_service() {
        assert_eq!(source_of("org.mpris.MediaPlayer2.spotify", "", &[], "x"), "spotify");
        assert_eq!(source_of("org.mpris.MediaPlayer2.mpv", "", &[], "x"), "video");
        assert_eq!(source_of("org.mpris.MediaPlayer2.rhythmbox", "", &[], "x"), "music");
        assert_eq!(
            source_of("org.mpris.MediaPlayer2.firefox.instance_1_2", "https://www.youtube.com/watch?v=1", &[], "x"),
            "youtube"
        );
    }

    #[test]
    fn a_browser_tab_is_found_by_its_title() {
        let titles = vec!["Lofi beats - YouTube - Chromium".to_string(), "Inbox - Gmail".to_string()];
        assert_eq!(source_of("org.mpris.MediaPlayer2.chromium.instance1", "", &titles, "Lofi beats"), "youtube");
        let apple = vec!["Apple Music - Web Player".to_string()];
        assert_eq!(source_of("org.mpris.MediaPlayer2.chromium.instance1", "", &apple, "Song"), "applemusic");
        assert_eq!(source_of("org.mpris.MediaPlayer2.chromium.instance1", "", &[], "Song"), "browser");
    }

    #[test]
    fn file_addresses_are_decoded() {
        assert_eq!(percent_decode("/tmp/cover%20art.png"), "/tmp/cover art.png");
    }
}
