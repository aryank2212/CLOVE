// What the machine itself is doing, for Clove Notch's status activities: who
// has the microphone and the camera, a screen recording, the battery of this
// computer and of what is connected to it (Bluetooth earphones, a mouse, the
// phone paired with KDE Connect), a Wi-Fi hotspot, and the lock screen.
//
// One thread reads all of it every two seconds from the cheapest place each
// lives in (/proc, /sys, one D-Bus call, one nmcli call) and sends `live-system`
// only when something changed.

use std::collections::HashMap;
use std::os::unix::fs::MetadataExt;
use std::process::Command;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use dbus::arg::{PropMap, RefArg};
use dbus::blocking::Connection;
use serde::Serialize;
use tauri::{AppHandle, Emitter};

use crate::island::WINDOW_LABEL;

const TICK: Duration = Duration::from_secs(2);
const CALL: Duration = Duration::from_millis(1200);
/// Programs that record the screen, by process name.
const RECORDERS: [&str; 7] = ["gpu-screen-reco", "wf-recorder", "wl-screenrec", "obs", "kooha", "simplescreenrec", "ffmpeg-screen"];
const LOCKERS: [&str; 5] = ["hyprlock", "swaylock", "gtklock", "waylock", "i3lock"];
/// These hold the camera or the microphone for everyone else: not a user of it.
const PLUMBING: [&str; 4] = ["pipewire", "wireplumber", "pipewire-pulse", "pipewire-media"];

#[derive(Serialize, Clone, Default, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct Recording {
    app: String,
    pid: u32,
    /// Unix ms the process started.
    since: f64,
}

#[derive(Serialize, Clone, Default, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct Battery {
    present: bool,
    percent: u32,
    charging: bool,
    plugged: bool,
}

#[derive(Serialize, Clone, Default, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct Device {
    id: String,
    name: String,
    /// "headphones", "phone", "mouse", "keyboard", "other".
    kind: String,
    percent: Option<u32>,
    charging: bool,
}

#[derive(Serialize, Clone, Default, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct Hotspot {
    name: String,
    ssid: String,
    iface: String,
    clients: u32,
}

#[derive(Serialize, Clone, Default, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct Snapshot {
    mic: Vec<String>,
    camera: Vec<String>,
    screen: Vec<Recording>,
    battery: Battery,
    devices: Vec<Device>,
    hotspot: Option<Hotspot>,
    locked: bool,
}

static LAST: Mutex<Option<Snapshot>> = Mutex::new(None);
/// A camera node was opened or closed since the last look.
static CAMERA_DIRTY: AtomicBool = AtomicBool::new(true);

pub fn snapshot() -> Option<Snapshot> {
    LAST.lock().unwrap().clone()
}

pub fn start(app: AppHandle) {
    let _ = std::thread::Builder::new().name("clove-live-camera".into()).spawn(watch_camera_nodes);
    let _ = std::thread::Builder::new().name("clove-live-system".into()).spawn(move || {
        let mut camera: Vec<String> = Vec::new();
        let mut devices: Vec<Device> = Vec::new();
        let mut hotspot: Option<Hotspot> = None;
        let mut hotspot_modes: HashMap<String, (String, String)> = HashMap::new();
        let mut tick: u64 = 0;
        loop {
            let procs = user_processes();
            if CAMERA_DIRTY.swap(false, Ordering::Relaxed) || !camera.is_empty() {
                camera = camera_users(&procs);
            }
            // Slower things, on every third tick: they leave this process.
            if tick % 3 == 0 {
                devices = connected_devices();
                hotspot = read_hotspot(&mut hotspot_modes);
            }
            let next = Snapshot {
                mic: mic_users(),
                camera: camera.clone(),
                screen: recordings(&procs),
                battery: read_battery(),
                devices: devices.clone(),
                hotspot: hotspot.clone(),
                locked: procs.iter().any(|p| LOCKERS.contains(&p.comm.as_str())),
            };
            let changed = {
                let mut last = LAST.lock().unwrap();
                let changed = last.as_ref() != Some(&next);
                if changed {
                    *last = Some(next.clone());
                }
                changed
            };
            if changed {
                let _ = app.emit_to(WINDOW_LABEL, "live-system", &next);
            }
            tick += 1;
            std::thread::sleep(TICK);
        }
    });
}

// ── Processes ─────────────────────────────────────────────────────────────────

struct Proc {
    pid: u32,
    comm: String,
}

/// This user's processes: only their files can be looked into anyway.
fn user_processes() -> Vec<Proc> {
    let uid = unsafe { libc::getuid() };
    let Ok(dir) = std::fs::read_dir("/proc") else { return Vec::new() };
    dir.flatten()
        .filter_map(|e| {
            let pid: u32 = e.file_name().to_str()?.parse().ok()?;
            if e.metadata().ok()?.uid() != uid {
                return None;
            }
            let comm = std::fs::read_to_string(e.path().join("comm")).ok()?.trim().to_string();
            Some(Proc { pid, comm })
        })
        .collect()
}

/// A readable name for a process: "chrome" → "Chrome".
fn pretty(comm: &str) -> String {
    let base = comm.trim_end_matches("-bin").trim_end_matches("-stable");
    let known = [
        ("chrome", "Chrome"), ("chromium", "Chromium"), ("firefox", "Firefox"), ("zen", "Zen"), ("brave", "Brave"),
        ("obs", "OBS"), ("zoom", "Zoom"), ("teams", "Teams"), ("discord", "Discord"), ("Discord", "Discord"),
        ("telegram-deskt", "Telegram"), ("signal-desktop", "Signal"), ("gpu-screen-reco", "Screen recording"),
        ("wf-recorder", "Screen recording"), ("wl-screenrec", "Screen recording"), ("python", "Python"),
        ("clove-notch", "Clove Notch"), ("cheese", "Cheese"), ("ffmpeg", "ffmpeg"), ("mpv", "mpv"),
    ];
    if let Some((_, nice)) = known.iter().find(|(k, _)| base.starts_with(k)) {
        return (*nice).to_string();
    }
    let mut c = base.chars();
    c.next().map(|f| f.to_uppercase().collect::<String>() + c.as_str()).unwrap_or_default()
}

fn started_ms(pid: u32) -> f64 {
    std::fs::metadata(format!("/proc/{pid}"))
        .and_then(|m| m.modified())
        .ok()
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| d.as_secs_f64() * 1000.0)
        .unwrap_or(0.0)
}

fn recordings(procs: &[Proc]) -> Vec<Recording> {
    procs
        .iter()
        .filter(|p| RECORDERS.contains(&p.comm.as_str()))
        // OBS open is not OBS recording; the others only exist while they record.
        .filter(|p| p.comm != "obs")
        .map(|p| Recording { app: pretty(&p.comm), pid: p.pid, since: started_ms(p.pid) })
        .collect()
}

/// True when `pid` is one of the screen recorders, checked again before a signal is sent.
pub fn is_recorder(pid: u32) -> bool {
    std::fs::read_to_string(format!("/proc/{pid}/comm")).is_ok_and(|c| RECORDERS.contains(&c.trim()) && c.trim() != "obs")
}

// ── Camera ────────────────────────────────────────────────────────────────────

/// Blocks on inotify for the camera nodes: an open or a close marks them dirty,
/// so /proc is only searched for who holds them when something happened.
fn watch_camera_nodes() {
    let fd = unsafe { libc::inotify_init1(libc::IN_CLOEXEC) };
    if fd < 0 {
        // No inotify: look every tick instead.
        loop {
            CAMERA_DIRTY.store(true, Ordering::Relaxed);
            std::thread::sleep(TICK);
        }
    }
    let mut watched = 0;
    if let Ok(dir) = std::fs::read_dir("/dev") {
        for e in dir.flatten() {
            let name = e.file_name();
            if !name.to_string_lossy().starts_with("video") {
                continue;
            }
            if let Ok(path) = std::ffi::CString::new(e.path().to_string_lossy().as_bytes()) {
                let wd = unsafe { libc::inotify_add_watch(fd, path.as_ptr(), libc::IN_OPEN | libc::IN_CLOSE) };
                if wd >= 0 {
                    watched += 1;
                }
            }
        }
    }
    if watched == 0 {
        return;
    }
    let mut buf = [0u8; 1024];
    loop {
        let n = unsafe { libc::read(fd, buf.as_mut_ptr().cast(), buf.len()) };
        if n <= 0 {
            std::thread::sleep(TICK);
            continue;
        }
        CAMERA_DIRTY.store(true, Ordering::Relaxed);
    }
}

fn camera_users(procs: &[Proc]) -> Vec<String> {
    let mut users: Vec<String> = Vec::new();
    let mut plumbing = false;
    for p in procs {
        let Ok(fds) = std::fs::read_dir(format!("/proc/{}/fd", p.pid)) else { continue };
        let holds = fds.flatten().any(|fd| {
            std::fs::read_link(fd.path()).is_ok_and(|t| t.to_string_lossy().starts_with("/dev/video"))
        });
        if !holds {
            continue;
        }
        if PLUMBING.iter().any(|x| p.comm.starts_with(x)) {
            plumbing = true;
            continue;
        }
        let name = pretty(&p.comm);
        if !users.contains(&name) {
            users.push(name);
        }
    }
    // PipeWire holds it for a sandboxed app we cannot name.
    if users.is_empty() && plumbing && pipewire_camera_running() {
        users.push("Camera".into());
    }
    users
}

/// PipeWire keeps the node open while idle too: only a running one counts.
fn pipewire_camera_running() -> bool {
    let Ok(out) = Command::new("pw-dump").output() else { return false };
    let Ok(v) = serde_json::from_slice::<serde_json::Value>(&out.stdout) else { return false };
    v.as_array().is_some_and(|nodes| {
        nodes.iter().any(|n| {
            let info = &n["info"];
            info["props"]["media.class"] == "Video/Source" && info["state"] == "running"
        })
    })
}

// ── Microphone ────────────────────────────────────────────────────────────────

/// True when `pid` is the CLOVE assistant: started from its folder (`.venv/bin/python agent.py` in
/// `…/CLOVE/assistant`), so its working folder or its command line names it.
fn is_clove(pid: &str) -> bool {
    if pid.is_empty() || !pid.chars().all(|c| c.is_ascii_digit()) {
        return false;
    }
    let cwd = std::fs::read_link(format!("/proc/{pid}/cwd")).map(|p| p.to_string_lossy().to_ascii_lowercase()).unwrap_or_default();
    let cmd = std::fs::read(format!("/proc/{pid}/cmdline")).map(|c| String::from_utf8_lossy(&c).to_ascii_lowercase()).unwrap_or_default();
    cwd.contains("clove") || cmd.contains("clove")
}

fn mic_users() -> Vec<String> {
    let Ok(out) = Command::new("pactl").args(["-f", "json", "list", "source-outputs"]).output() else { return Vec::new() };
    let Ok(v) = serde_json::from_slice::<serde_json::Value>(&out.stdout) else { return Vec::new() };
    let streams = v.as_array().map(Vec::as_slice).unwrap_or_default();
    // A stream from the ALSA plugin carries no process id; its client does. Asked only when needed.
    let mut client_pids: Option<HashMap<String, String>> = None;
    let mut users: Vec<String> = Vec::new();
    for s in streams {
        let props = &s["properties"];
        let prop = |k: &str| props[k].as_str().unwrap_or_default();
        // Volume meters (pavucontrol, a mixer applet) listen without recording.
        if s["corked"] == true || prop("media.name").contains("Peak detect") || prop("application.id").contains("pavucontrol") {
            continue;
        }
        let binary = prop("application.process.binary");
        let raw = if !binary.is_empty() { binary } else { prop("application.name") };
        // "PipeWire ALSA [python3.14]" → python3.14
        let inner = raw.rsplit_once('[').map(|(_, r)| r.trim_end_matches(']')).unwrap_or(raw);
        let mut pid = prop("application.process.id").to_string();
        if pid.is_empty() {
            let clients = client_pids.get_or_insert_with(client_process_ids);
            let client = s["client"].as_str().map(str::to_string).or_else(|| s["client"].as_u64().map(|n| n.to_string()));
            pid = client.and_then(|c| clients.get(&c).cloned()).unwrap_or_default();
        }
        // The CLOVE assistant listens for its name: say so rather than "Python".
        let name = if is_clove(&pid) { "CLOVE".to_string() } else { pretty(inner.trim()) };
        if !name.is_empty() && !users.contains(&name) {
            users.push(name);
        }
    }
    users
}

/// PipeWire's clients by index, with the process each belongs to.
fn client_process_ids() -> HashMap<String, String> {
    let Ok(out) = Command::new("pactl").args(["-f", "json", "list", "clients"]).output() else { return HashMap::new() };
    let Ok(v) = serde_json::from_slice::<serde_json::Value>(&out.stdout) else { return HashMap::new() };
    v.as_array()
        .map(|clients| {
            clients
                .iter()
                .filter_map(|c| {
                    let index = c["index"].as_u64().map(|n| n.to_string()).or_else(|| c["index"].as_str().map(str::to_string))?;
                    let pid = c["properties"]["application.process.id"].as_str()?.to_string();
                    Some((index, pid))
                })
                .collect()
        })
        .unwrap_or_default()
}

// ── Battery ───────────────────────────────────────────────────────────────────

fn read_battery() -> Battery {
    let mut b = Battery::default();
    let Ok(dir) = std::fs::read_dir("/sys/class/power_supply") else { return b };
    for e in dir.flatten() {
        let read = |f: &str| std::fs::read_to_string(e.path().join(f)).map(|s| s.trim().to_string()).unwrap_or_default();
        match read("type").as_str() {
            "Battery" if read("scope") != "Device" && !b.present => {
                b.present = true;
                b.percent = read("capacity").parse().unwrap_or(0);
                b.charging = read("status") == "Charging";
            }
            "Mains" | "USB" if read("online") == "1" => b.plugged = true,
            _ => {}
        }
    }
    b
}

fn device_kind(icon: &str, name: &str) -> &'static str {
    let hay = format!("{icon} {name}").to_ascii_lowercase();
    if ["headset", "headphone", "audio", "buds", "airpods", "earbuds", "pods", "speaker"].iter().any(|k| hay.contains(k)) {
        "headphones"
    } else if hay.contains("phone") {
        "phone"
    } else if hay.contains("mouse") {
        "mouse"
    } else if hay.contains("keyboard") {
        "keyboard"
    } else {
        "other"
    }
}

fn prop_str(map: &PropMap, key: &str) -> String {
    map.get(key).and_then(|v| v.0.as_str()).unwrap_or_default().to_string()
}

fn prop_num(map: &PropMap, key: &str) -> Option<f64> {
    map.get(key).and_then(|v| v.0.as_i64().map(|n| n as f64).or_else(|| v.0.as_u64().map(|n| n as f64)).or_else(|| v.0.as_f64()))
}

type Managed = HashMap<dbus::Path<'static>, HashMap<String, PropMap>>;

/// Connected Bluetooth devices (BlueZ), wireless peripherals (UPower) and the
/// phones KDE Connect reaches, each with its battery when it reports one.
fn connected_devices() -> Vec<Device> {
    let mut out: Vec<Device> = Vec::new();
    if let Ok(conn) = Connection::new_system() {
        let bluez = conn.with_proxy("org.bluez", "/", CALL);
        let managed: Result<(Managed,), _> = bluez.method_call("org.freedesktop.DBus.ObjectManager", "GetManagedObjects", ());
        if let Ok((objects,)) = managed {
            for (path, ifaces) in &objects {
                let Some(dev) = ifaces.get("org.bluez.Device1") else { continue };
                if prop_num(dev, "Connected").unwrap_or(0.0) == 0.0 {
                    continue;
                }
                let name = { let a = prop_str(dev, "Alias"); if a.is_empty() { prop_str(dev, "Name") } else { a } };
                let percent = ifaces.get("org.bluez.Battery1").and_then(|b| prop_num(b, "Percentage")).map(|p| p as u32);
                out.push(Device {
                    id: path.to_string(),
                    kind: device_kind(&prop_str(dev, "Icon"), &name).to_string(),
                    name,
                    percent,
                    charging: false,
                });
            }
        }
        let upower = conn.with_proxy("org.freedesktop.UPower", "/org/freedesktop/UPower", CALL);
        let paths: Result<(Vec<dbus::Path<'static>>,), _> = upower.method_call("org.freedesktop.UPower", "EnumerateDevices", ());
        for path in paths.map(|(p,)| p).unwrap_or_default() {
            let dev = conn.with_proxy("org.freedesktop.UPower", path.clone(), CALL);
            let got: Result<(PropMap,), _> = dev.method_call("org.freedesktop.DBus.Properties", "GetAll", ("org.freedesktop.UPower.Device",));
            let Ok((props,)) = got else { continue };
            // 1 = mains, 2 = this computer's battery: both are read from /sys.
            let kind = prop_num(&props, "Type").unwrap_or(0.0) as u32;
            if kind <= 3 || prop_num(&props, "IsPresent") == Some(0.0) {
                continue;
            }
            let name = prop_str(&props, "Model");
            let percent = prop_num(&props, "Percentage").map(|p| p.round() as u32);
            // BlueZ already listed it: UPower only adds the battery it may know.
            if let Some(same) = out.iter_mut().find(|d| !name.is_empty() && d.name == name) {
                same.percent = same.percent.or(percent);
                continue;
            }
            if name.is_empty() {
                continue;
            }
            let kind = match kind {
                5 => "mouse",
                6 => "keyboard",
                8 => "phone",
                17 | 18 | 19 | 21 => "headphones",
                _ => device_kind("", &name),
            };
            out.push(Device {
                id: path.to_string(),
                name,
                kind: kind.to_string(),
                percent,
                charging: prop_num(&props, "State") == Some(1.0),
            });
        }
    }
    if let Ok(conn) = Connection::new_session() {
        let daemon = conn.with_proxy("org.kde.kdeconnect", "/modules/kdeconnect", CALL);
        let ids: Result<(Vec<String>,), _> = daemon.method_call("org.kde.kdeconnect.daemon", "devices", (true, true));
        for id in ids.map(|(i,)| i).unwrap_or_default() {
            let path = format!("/modules/kdeconnect/devices/{id}");
            let dev = conn.with_proxy("org.kde.kdeconnect", path.as_str(), CALL);
            let name = dbus::blocking::stdintf::org_freedesktop_dbus::Properties::get::<String>(&dev, "org.kde.kdeconnect.device", "name")
                .unwrap_or_else(|_| "Phone".into());
            let battery_path = format!("{path}/battery");
            let battery = conn.with_proxy("org.kde.kdeconnect", battery_path.as_str(), CALL);
            let charge = dbus::blocking::stdintf::org_freedesktop_dbus::Properties::get::<i32>(&battery, "org.kde.kdeconnect.device.battery", "charge").ok();
            let charging = dbus::blocking::stdintf::org_freedesktop_dbus::Properties::get::<bool>(&battery, "org.kde.kdeconnect.device.battery", "isCharging").unwrap_or(false);
            out.push(Device {
                id: format!("kdeconnect:{id}"),
                name,
                kind: "phone".into(),
                percent: charge.filter(|c| *c >= 0).map(|c| c as u32),
                charging,
            });
        }
    }
    out.sort_by(|a, b| a.id.cmp(&b.id));
    out
}

// ── Hotspot ───────────────────────────────────────────────────────────────────

fn nmcli(args: &[&str]) -> Option<String> {
    let out = Command::new("nmcli").args(args).output().ok()?;
    out.status.success().then(|| String::from_utf8_lossy(&out.stdout).into_owned())
}

/// The Wi-Fi connection this computer shares as an access point, if any. A
/// connection's mode never changes, so it is asked once per connection.
fn read_hotspot(modes: &mut HashMap<String, (String, String)>) -> Option<Hotspot> {
    let active = nmcli(&["-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"])?;
    for line in active.lines() {
        let mut parts = line.rsplitn(3, ':');
        let (Some(iface), Some(kind), Some(name)) = (parts.next(), parts.next(), parts.next()) else { continue };
        if kind != "802-11-wireless" {
            continue;
        }
        let name = name.replace("\\:", ":");
        let (mode, ssid) = modes
            .entry(name.clone())
            .or_insert_with(|| {
                let got = nmcli(&["-g", "802-11-wireless.mode,802-11-wireless.ssid", "connection", "show", &name]).unwrap_or_default();
                let mut l = got.lines();
                (l.next().unwrap_or_default().to_string(), l.next().unwrap_or_default().to_string())
            })
            .clone();
        if mode != "ap" {
            continue;
        }
        let clients = Command::new("iw")
            .args(["dev", iface, "station", "dump"])
            .output()
            .map(|o| String::from_utf8_lossy(&o.stdout).lines().filter(|l| l.starts_with("Station ")).count() as u32)
            .unwrap_or(0);
        return Some(Hotspot { ssid: if ssid.is_empty() { name.clone() } else { ssid }, name, iface: iface.to_string(), clients });
    }
    None
}

pub fn hotspot_off() -> bool {
    let Some(name) = LAST.lock().unwrap().as_ref().and_then(|s| s.hotspot.as_ref().map(|h| h.name.clone())) else { return false };
    nmcli(&["connection", "down", &name]).is_some()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn devices_are_sorted_into_kinds() {
        assert_eq!(device_kind("audio-headset", "WH-1000XM4"), "headphones");
        assert_eq!(device_kind("", "AirPods Pro"), "headphones");
        assert_eq!(device_kind("phone", "Pixel"), "phone");
        assert_eq!(device_kind("input-mouse", "MX Master"), "mouse");
        assert_eq!(device_kind("input-keyboard", "K380"), "keyboard");
        assert_eq!(device_kind("", "Thing"), "other");
    }

    #[test]
    fn only_a_process_number_is_looked_up() {
        assert!(!is_clove(""));
        assert!(!is_clove("abc"));
        assert!(!is_clove("../1"));
        assert!(!is_clove("999999999"));
    }

    #[test]
    fn process_names_read_well() {
        assert_eq!(pretty("chrome"), "Chrome");
        assert_eq!(pretty("zen-bin"), "Zen");
        assert_eq!(pretty("python3.14"), "Python");
        assert_eq!(pretty("cheese"), "Cheese");
        assert_eq!(pretty("kamoso"), "Kamoso");
    }
}
