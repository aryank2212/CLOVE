// CLOVE fork: LocalSend, built in. Phones and computers running LocalSend see Clove Notch as "CLOVE"; files sent
// to it are offered in the notch (Accept / Decline) and saved to Downloads; files dropped on the notch go to any
// LocalSend device nearby. No other app is involved.
//
// The LocalSend protocol v2 (github.com/localsend/protocol):
//   - discovery: a JSON "announce" to the multicast group 224.0.0.167:53317; whoever hears it answers with
//     POST /api/localsend/v2/register on the announcer's HTTP port (or a multicast reply);
//   - receiving: POST /prepare-upload (the file list; we answer with a session and one token per file, or 403),
//     then POST /upload?sessionId&fileId&token per file (the bytes), or POST /cancel;
//   - sending: the same, the other way round.
// Clove Notch serves plain HTTP on 53317 (LocalSend's own port, which his firewall already allows), or the next
// free port when the LocalSend app happens to be running. Devices that use HTTPS (most phones) get HTTPS from us
// as clients; their self-signed certificates can't be checked against anything, as in LocalSend itself.
//
// Safety: nothing is saved without his Accept. A file goes in Downloads under its own name only (no paths), never
// larger than it said it would be, checked against its SHA-256 when the sender gives one, and only the device that
// asked may upload into its session.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use std::net::{IpAddr, Ipv4Addr, SocketAddr, SocketAddrV4};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter};
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::net::{TcpListener, TcpStream, UdpSocket};
use tokio::sync::oneshot;

const GROUP: Ipv4Addr = Ipv4Addr::new(224, 0, 0, 167);
const PORT: u16 = 53317;
const API: &str = "/api/localsend/v2";
/// How long he has to answer an incoming transfer.
const ASK_FOR: Duration = Duration::from_secs(90);
/// A device not heard from for this long leaves the list.
const FORGET_AFTER: Duration = Duration::from_secs(15 * 60);
const MAX_JSON: usize = 2 * 1024 * 1024;

// ── Values ──────────────────────────────────────────────────────────────────────

/// A device's description, as every LocalSend message carries it.
#[derive(Serialize, Deserialize, Clone, Debug, Default)]
#[serde(rename_all = "camelCase", default)]
pub struct Info {
    pub alias: String,
    pub version: String,
    pub device_model: Option<String>,
    pub device_type: Option<String>,
    pub fingerprint: String,
    pub port: Option<u16>,
    pub protocol: Option<String>,
    pub download: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub announce: Option<bool>,
}

#[derive(Clone, Debug)]
struct Device {
    info: Info,
    ip: IpAddr,
    seen: Instant,
}

/// A device for the page.
#[derive(Serialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct DeviceView {
    pub id: String,
    pub alias: String,
    pub device_type: String,
    pub device_model: String,
    pub ip: String,
}

#[derive(Deserialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct FileMeta {
    pub id: String,
    pub file_name: String,
    pub size: u64,
    #[serde(default)]
    pub file_type: String,
    #[serde(default)]
    pub sha256: Option<String>,
    #[serde(default)]
    pub preview: Option<String>,
}

#[derive(Deserialize, Debug)]
struct PrepareUpload {
    info: Info,
    files: HashMap<String, FileMeta>,
}

/// An incoming transfer he is asked about.
#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct Request {
    pub id: u64,
    pub alias: String,
    pub device_type: String,
    pub files: Vec<RequestFile>,
    pub total: u64,
    /// A text message (LocalSend's "send text"): shown, nothing to save.
    pub text: Option<String>,
}

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct RequestFile {
    pub name: String,
    pub size: u64,
}

/// Progress, both ways.
#[derive(Serialize, Clone, Debug, Default)]
#[serde(rename_all = "camelCase")]
pub struct Progress {
    /// "in" (receiving) | "out" (sending)
    pub direction: String,
    pub device: String,
    pub done_bytes: u64,
    pub total_bytes: u64,
    /// "running" | "done" | "declined" | "cancelled" | "failed"
    pub state: String,
    pub error: Option<String>,
    /// Received files where they were saved (when done).
    pub saved: Vec<String>,
    pub folder: Option<String>,
}

struct Session {
    from: IpAddr,
    device: String,
    files: HashMap<String, (String, FileMeta)>, // file id -> (token, meta)
    done: HashSet<String>,
    saved: Vec<PathBuf>,
    received: u64,
    total: u64,
    dir: PathBuf,
}

struct Inner {
    app: AppHandle,
    info: Info,
    devices: Mutex<HashMap<String, Device>>,
    pending: Mutex<HashMap<u64, oneshot::Sender<bool>>>,
    sessions: Mutex<HashMap<String, Session>>,
    next: AtomicU64,
    udp: tokio::sync::OnceCell<Arc<UdpSocket>>,
    last_emit: Mutex<Instant>,
}

static LS: OnceLock<Arc<Inner>> = OnceLock::new();

// ── Small helpers (tested) ──────────────────────────────────────────────────────

/// A file name safe to save: its last path part, no control characters or leading dots, at most 180 bytes.
pub fn safe_name(raw: &str) -> String {
    let last = raw.rsplit(['/', '\\']).next().unwrap_or("");
    let cleaned: String = last.chars().filter(|c| !c.is_control() && !matches!(c, ':' | '*' | '?' | '"' | '<' | '>' | '|')).collect();
    let trimmed = cleaned.trim().trim_start_matches('.').trim();
    let mut name = if trimmed.is_empty() { "file".to_string() } else { trimmed.to_string() };
    while name.len() > 180 {
        name.pop();
    }
    name
}

/// `dir/name`, or `dir/name (2).ext`… if that is taken.
pub fn unique_path(dir: &Path, name: &str) -> PathBuf {
    let first = dir.join(name);
    if !first.exists() {
        return first;
    }
    let (stem, ext) = match name.rfind('.') {
        Some(i) if i > 0 => (&name[..i], &name[i..]),
        _ => (name, ""),
    };
    for n in 2..10_000 {
        let p = dir.join(format!("{stem} ({n}){ext}"));
        if !p.exists() {
            return p;
        }
    }
    dir.join(format!("{stem} ({}){ext}", random_hex(4)))
}

pub fn random_hex(bytes: usize) -> String {
    let mut buf = vec![0u8; bytes];
    let ok = std::fs::File::open("/dev/urandom").and_then(|mut f| std::io::Read::read_exact(&mut f, &mut buf)).is_ok();
    if !ok {
        // No /dev/urandom (not Linux): time and process mixed through SHA-256.
        let seed = format!("{:?}{}{:?}", std::time::SystemTime::now(), std::process::id(), Instant::now());
        let h = Sha256::digest(seed.as_bytes());
        for (i, b) in buf.iter_mut().enumerate() {
            *b = h[i % h.len()];
        }
    }
    buf.iter().map(|b| format!("{b:02x}")).collect()
}

/// A MIME type from the extension (what LocalSend shows as the file's kind).
pub fn mime_for(name: &str) -> &'static str {
    let ext = name.rsplit('.').next().unwrap_or("").to_ascii_lowercase();
    match ext.as_str() {
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "gif" => "image/gif",
        "webp" => "image/webp",
        "heic" => "image/heic",
        "mp4" => "video/mp4",
        "mov" => "video/quicktime",
        "mkv" => "video/x-matroska",
        "mp3" => "audio/mpeg",
        "m4a" => "audio/mp4",
        "wav" => "audio/wav",
        "pdf" => "application/pdf",
        "zip" => "application/zip",
        "txt" | "md" => "text/plain",
        "apk" => "application/vnd.android.package-archive",
        _ => "application/octet-stream",
    }
}

fn query(target: &str) -> HashMap<String, String> {
    let q = target.split_once('?').map(|(_, q)| q).unwrap_or("");
    q.split('&')
        .filter_map(|kv| kv.split_once('='))
        .map(|(k, v)| (k.to_string(), percent_decode(v)))
        .collect()
}

fn percent_decode(s: &str) -> String {
    let b = s.as_bytes();
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        match b[i] {
            b'%' if i + 2 < b.len() => {
                if let Some(v) = std::str::from_utf8(&b[i + 1..i + 3]).ok().and_then(|h| u8::from_str_radix(h, 16).ok()) {
                    out.push(v);
                    i += 3;
                    continue;
                }
                out.push(b'%');
            }
            b'+' => out.push(b' '),
            c => out.push(c),
        }
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// His Downloads folder (XDG), else ~/Downloads.
fn downloads() -> PathBuf {
    let home = std::env::var_os("HOME").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("."));
    if let Ok(text) = std::fs::read_to_string(home.join(".config/user-dirs.dirs")) {
        for line in text.lines() {
            if let Some(v) = line.strip_prefix("XDG_DOWNLOAD_DIR=") {
                let v = v.trim().trim_matches('"').replace("$HOME", &home.to_string_lossy());
                if !v.is_empty() {
                    return PathBuf::from(v);
                }
            }
        }
    }
    home.join("Downloads")
}

/// This PC's IPv4 addresses on its networks (not loopback), from `ip -4 -j addr`.
fn local_ipv4() -> Vec<Ipv4Addr> {
    let out = std::process::Command::new("ip").args(["-4", "-j", "addr"]).output();
    let Ok(out) = out else { return Vec::new() };
    let v: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap_or_default();
    let mut ips = Vec::new();
    for iface in v.as_array().into_iter().flatten() {
        let name = iface["ifname"].as_str().unwrap_or("");
        if name == "lo" || name.starts_with("docker") || name.starts_with("br-") || name.starts_with("veth") {
            continue;
        }
        for a in iface["addr_info"].as_array().into_iter().flatten() {
            if let Some(ip) = a["local"].as_str().and_then(|s| s.parse::<Ipv4Addr>().ok()) {
                ips.push(ip);
            }
        }
    }
    ips
}

// ── Start ───────────────────────────────────────────────────────────────────────

pub fn start(app: &AppHandle) {
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        // Our HTTP port: LocalSend's own if free, else the next few.
        let mut listener = None;
        for port in PORT..PORT + 8 {
            if let Ok(l) = TcpListener::bind(SocketAddr::from((Ipv4Addr::UNSPECIFIED, port))).await {
                listener = Some((l, port));
                break;
            }
        }
        let Some((listener, port)) = listener else {
            eprintln!("[localsend] no free port");
            return;
        };
        let host = std::fs::read_to_string("/etc/hostname").unwrap_or_default().trim().to_string();
        let info = Info {
            alias: "CLOVE".into(),
            version: "2.1".into(),
            device_model: Some(if host.is_empty() { "Linux".into() } else { host }),
            device_type: Some("desktop".into()),
            fingerprint: random_hex(16),
            port: Some(port),
            protocol: Some("http".into()),
            download: Some(false),
            announce: None,
        };
        let inner = Arc::new(Inner {
            app,
            info,
            devices: Mutex::new(HashMap::new()),
            pending: Mutex::new(HashMap::new()),
            sessions: Mutex::new(HashMap::new()),
            next: AtomicU64::new(1),
            udp: tokio::sync::OnceCell::new(),
            last_emit: Mutex::new(Instant::now()),
        });
        let _ = LS.set(inner.clone());
        eprintln!("[localsend] serving on {port}");
        tauri::async_runtime::spawn(serve(inner.clone(), listener));
        if let Some(sock) = multicast_socket() {
            let sock = Arc::new(sock);
            let _ = inner.udp.set(sock.clone());
            tauri::async_runtime::spawn(listen_udp(inner.clone(), sock));
        }
        loop {
            announce(&inner).await;
            tokio::time::sleep(Duration::from_secs(120)).await;
        }
    });
}

/// The multicast socket: shares port 53317 with the LocalSend app if it runs (SO_REUSEADDR/PORT).
fn multicast_socket() -> Option<UdpSocket> {
    use socket2::{Domain, Protocol, Socket, Type};
    let s = Socket::new(Domain::IPV4, Type::DGRAM, Some(Protocol::UDP)).ok()?;
    s.set_reuse_address(true).ok()?;
    #[cfg(unix)]
    let _ = s.set_reuse_port(true);
    s.bind(&SocketAddr::from((Ipv4Addr::UNSPECIFIED, PORT)).into()).ok()?;
    let ips = local_ipv4();
    if ips.is_empty() {
        let _ = s.join_multicast_v4(&GROUP, &Ipv4Addr::UNSPECIFIED);
    }
    for ip in &ips {
        let _ = s.join_multicast_v4(&GROUP, ip);
    }
    let _ = s.set_multicast_loop_v4(true);
    s.set_nonblocking(true).ok()?;
    UdpSocket::from_std(s.into()).ok()
}

async fn announce(inner: &Arc<Inner>) {
    let Some(sock) = inner.udp.get() else { return };
    let mut msg = inner.info.clone();
    msg.announce = Some(true);
    let body = serde_json::to_vec(&msg).unwrap_or_default();
    // Out of every network he is on (the hotspot, the LAN, …).
    let raw = socket2::SockRef::from(sock.as_ref());
    let ips = local_ipv4();
    for ip in &ips {
        let _ = raw.set_multicast_if_v4(ip);
        let _ = sock.send_to(&body, SocketAddrV4::new(GROUP, PORT)).await;
    }
    if ips.is_empty() {
        let _ = sock.send_to(&body, SocketAddrV4::new(GROUP, PORT)).await;
    }
}

async fn listen_udp(inner: Arc<Inner>, sock: Arc<UdpSocket>) {
    let mut buf = vec![0u8; 64 * 1024];
    loop {
        let Ok((n, from)) = sock.recv_from(&mut buf).await else {
            tokio::time::sleep(Duration::from_millis(200)).await;
            continue;
        };
        let Ok(info) = serde_json::from_slice::<Info>(&buf[..n]) else { continue };
        if info.fingerprint == inner.info.fingerprint || info.alias.is_empty() {
            continue;
        }
        let ip = from.ip();
        remember(&inner, info.clone(), ip);
        if info.announce == Some(true) {
            // Answer: register with them over HTTP, else a multicast reply.
            let inner2 = inner.clone();
            tauri::async_runtime::spawn(async move {
                if !register_with(&inner2, &info, ip).await {
                    let mut reply = inner2.info.clone();
                    reply.announce = Some(false);
                    if let Some(s) = inner2.udp.get() {
                        let _ = s.send_to(&serde_json::to_vec(&reply).unwrap_or_default(), SocketAddrV4::new(GROUP, PORT)).await;
                    }
                }
            });
        }
    }
}

fn remember(inner: &Arc<Inner>, info: Info, ip: IpAddr) {
    let changed = {
        let mut devices = inner.devices.lock().unwrap();
        devices.retain(|_, d| d.seen.elapsed() < FORGET_AFTER);
        let key = info.fingerprint.clone();
        let new = !devices.contains_key(&key);
        devices.insert(key, Device { info, ip, seen: Instant::now() });
        new
    };
    if changed {
        let _ = inner.app.emit("localsend-devices", device_list(inner));
    }
}

fn device_list(inner: &Arc<Inner>) -> Vec<DeviceView> {
    let devices = inner.devices.lock().unwrap();
    let mut out: Vec<DeviceView> = devices
        .iter()
        .filter(|(_, d)| d.seen.elapsed() < FORGET_AFTER)
        .map(|(k, d)| DeviceView {
            id: k.clone(),
            alias: d.info.alias.clone(),
            device_type: d.info.device_type.clone().unwrap_or_else(|| "desktop".into()),
            device_model: d.info.device_model.clone().unwrap_or_default(),
            ip: d.ip.to_string(),
        })
        .collect();
    out.sort_by(|a, b| a.alias.cmp(&b.alias));
    out
}

fn client() -> Option<reqwest::Client> {
    reqwest::Client::builder()
        .danger_accept_invalid_certs(true)          // LocalSend's certificates are self-signed by design
        .connect_timeout(Duration::from_secs(4))
        .no_proxy()
        .build()
        .ok()
}

fn base_url(info: &Info, ip: IpAddr) -> String {
    let proto = if info.protocol.as_deref() == Some("http") { "http" } else { "https" };
    format!("{proto}://{ip}:{}{API}", info.port.unwrap_or(PORT))
}

async fn register_with(inner: &Arc<Inner>, info: &Info, ip: IpAddr) -> bool {
    let Some(c) = client() else { return false };
    let resp = c
        .post(format!("{}/register", base_url(info, ip)))
        .timeout(Duration::from_secs(5))
        .json(&inner.info)
        .send()
        .await;
    match resp {
        Ok(r) if r.status().is_success() => {
            if let Ok(mut theirs) = r.json::<Info>().await {
                if theirs.port.is_none() {
                    theirs.port = info.port;
                }
                if theirs.protocol.is_none() {
                    theirs.protocol = info.protocol.clone();
                }
                if !theirs.fingerprint.is_empty() && theirs.fingerprint != inner.info.fingerprint {
                    remember(inner, theirs, ip);
                }
            }
            true
        }
        _ => false,
    }
}

// ── The HTTP server (receiving) ─────────────────────────────────────────────────

async fn serve(inner: Arc<Inner>, listener: TcpListener) {
    loop {
        let Ok((stream, peer)) = listener.accept().await else { continue };
        let inner = inner.clone();
        tauri::async_runtime::spawn(async move {
            let _ = handle(inner, stream, peer).await;
        });
    }
}

struct Req {
    method: String,
    target: String,
    headers: HashMap<String, String>,
}

async fn read_head(r: &mut BufReader<TcpStream>) -> Option<Req> {
    let mut line = String::new();
    tokio::time::timeout(Duration::from_secs(15), r.read_line(&mut line)).await.ok()?.ok()?;
    let mut parts = line.split_whitespace();
    let method = parts.next()?.to_string();
    let target = parts.next()?.to_string();
    let mut headers = HashMap::new();
    loop {
        let mut h = String::new();
        let n = tokio::time::timeout(Duration::from_secs(15), r.read_line(&mut h)).await.ok()?.ok()?;
        if n == 0 || h == "\r\n" || h == "\n" {
            break;
        }
        if headers.len() > 100 {
            return None;
        }
        if let Some((k, v)) = h.split_once(':') {
            headers.insert(k.trim().to_ascii_lowercase(), v.trim().to_string());
        }
    }
    Some(Req { method, target, headers })
}

/// The body, all of it (small JSON bodies only).
async fn read_body(r: &mut BufReader<TcpStream>, req: &Req, limit: usize) -> Option<Vec<u8>> {
    let mut out = Vec::new();
    read_body_into(r, req, limit as u64, |chunk| {
        out.extend_from_slice(chunk);
        true
    })
    .await?;
    Some(out)
}

/// Streams the body to `sink` (Content-Length or chunked). None on a broken or oversized body.
async fn read_body_into(r: &mut BufReader<TcpStream>, req: &Req, limit: u64, mut sink: impl FnMut(&[u8]) -> bool) -> Option<u64> {
    let mut buf = vec![0u8; 256 * 1024];
    let mut total = 0u64;
    if req.headers.get("transfer-encoding").map(|v| v.to_ascii_lowercase().contains("chunked")).unwrap_or(false) {
        loop {
            let mut size_line = String::new();
            tokio::time::timeout(Duration::from_secs(60), r.read_line(&mut size_line)).await.ok()?.ok()?;
            let size = u64::from_str_radix(size_line.trim().split(';').next()?.trim(), 16).ok()?;
            if size == 0 {
                let mut end = String::new();
                let _ = r.read_line(&mut end).await;
                return Some(total);
            }
            let mut left = size;
            while left > 0 {
                let want = left.min(buf.len() as u64) as usize;
                let n = tokio::time::timeout(Duration::from_secs(60), r.read(&mut buf[..want])).await.ok()?.ok()?;
                if n == 0 {
                    return None;
                }
                total += n as u64;
                if total > limit || !sink(&buf[..n]) {
                    return None;
                }
                left -= n as u64;
            }
            let mut crlf = [0u8; 2];
            r.read_exact(&mut crlf).await.ok()?;
        }
    }
    let len: u64 = req.headers.get("content-length").and_then(|v| v.parse().ok()).unwrap_or(0);
    if len > limit {
        return None;
    }
    let mut left = len;
    while left > 0 {
        let want = left.min(buf.len() as u64) as usize;
        let n = tokio::time::timeout(Duration::from_secs(60), r.read(&mut buf[..want])).await.ok()?.ok()?;
        if n == 0 {
            return None;
        }
        total += n as u64;
        if !sink(&buf[..n]) {
            return None;
        }
        left -= n as u64;
    }
    Some(total)
}

async fn reply(r: &mut BufReader<TcpStream>, status: u16, body: &[u8]) {
    let text = match status {
        200 => "OK",
        204 => "No Content",
        400 => "Bad Request",
        403 => "Forbidden",
        404 => "Not Found",
        409 => "Conflict",
        422 => "Unprocessable Entity",
        _ => "Error",
    };
    let head = format!(
        "HTTP/1.1 {status} {text}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    );
    let s = r.get_mut();
    let _ = s.write_all(head.as_bytes()).await;
    let _ = s.write_all(body).await;
    let _ = s.flush().await;
}

async fn handle(inner: Arc<Inner>, stream: TcpStream, peer: SocketAddr) -> Option<()> {
    let mut r = BufReader::new(stream);
    let req = read_head(&mut r).await?;
    let path = req.target.split('?').next().unwrap_or("").to_string();
    let Some(route) = path.strip_prefix(API) else {
        reply(&mut r, 404, b"{}").await;
        return Some(());
    };
    match (req.method.as_str(), route) {
        ("POST", "/register") => {
            let body = read_body(&mut r, &req, MAX_JSON).await?;
            if let Ok(info) = serde_json::from_slice::<Info>(&body) {
                if info.fingerprint != inner.info.fingerprint && !info.alias.is_empty() {
                    remember(&inner, info, peer.ip());
                }
            }
            reply(&mut r, 200, &serde_json::to_vec(&inner.info).unwrap_or_default()).await;
        }
        ("GET", "/info") => {
            reply(&mut r, 200, &serde_json::to_vec(&inner.info).unwrap_or_default()).await;
        }
        ("POST", "/prepare-upload") => {
            let body = read_body(&mut r, &req, MAX_JSON).await?;
            let (status, out) = prepare_upload(&inner, &body, peer.ip()).await;
            reply(&mut r, status, &out).await;
        }
        ("POST", "/upload") => {
            let status = upload(&inner, &mut r, &req, peer.ip()).await;
            reply(&mut r, status, b"").await;
        }
        ("POST", "/cancel") => {
            let q = query(&req.target);
            let sid = q.get("sessionId").cloned().unwrap_or_default();
            let gone = {
                let mut sessions = inner.sessions.lock().unwrap();
                match sessions.get(&sid) {
                    Some(s) if s.from == peer.ip() => sessions.remove(&sid),
                    _ => None,
                }
            };
            if let Some(s) = gone {
                emit_progress(&inner, &s, "cancelled", None, true);
            }
            reply(&mut r, 200, b"").await;
        }
        _ => reply(&mut r, 404, b"{}").await,
    }
    Some(())
}

async fn prepare_upload(inner: &Arc<Inner>, body: &[u8], from: IpAddr) -> (u16, Vec<u8>) {
    if crate::integrations::PAUSED.load(Ordering::Relaxed) {
        return (403, b"{}".to_vec());
    }
    let Ok(p) = serde_json::from_slice::<PrepareUpload>(body) else { return (400, b"{}".to_vec()) };
    if p.files.is_empty() || p.files.len() > 1000 {
        return (400, b"{}".to_vec());
    }
    if !inner.sessions.lock().unwrap().is_empty() {
        return (409, b"{}".to_vec());
    }
    remember(inner, p.info.clone(), from);
    let files: Vec<FileMeta> = p.files.values().cloned().collect();
    // A message ("send text"): one text file whose words come in the preview.
    let text = (files.len() == 1 && files[0].file_type.starts_with("text/"))
        .then(|| files[0].preview.clone())
        .flatten();
    let id = inner.next.fetch_add(1, Ordering::Relaxed);
    let request = Request {
        id,
        alias: p.info.alias.clone(),
        device_type: p.info.device_type.clone().unwrap_or_else(|| "mobile".into()),
        files: files.iter().map(|f| RequestFile { name: safe_name(&f.file_name), size: f.size }).collect(),
        total: files.iter().map(|f| f.size).sum(),
        text: text.clone(),
    };
    let (tx, rx) = oneshot::channel();
    inner.pending.lock().unwrap().insert(id, tx);
    let _ = inner.app.emit("localsend-request", request);
    let accepted = matches!(tokio::time::timeout(ASK_FOR, rx).await, Ok(Ok(true)));
    inner.pending.lock().unwrap().remove(&id);
    if !accepted {
        let _ = inner.app.emit("localsend-progress", Progress {
            direction: "in".into(), device: p.info.alias.clone(), state: "declined".into(), ..Default::default()
        });
        return (403, b"{}".to_vec());
    }
    if text.is_some() {
        // Nothing to transfer: the words were in the request.
        return (204, Vec::new());
    }
    let sid = random_hex(16);
    let mut tokens = serde_json::Map::new();
    let mut session_files = HashMap::new();
    for f in files {
        let token = random_hex(16);
        tokens.insert(f.id.clone(), serde_json::Value::String(token.clone()));
        session_files.insert(f.id.clone(), (token, f));
    }
    let total = session_files.values().map(|(_, f)| f.size).sum();
    let dir = downloads();
    let _ = std::fs::create_dir_all(&dir);
    inner.sessions.lock().unwrap().insert(sid.clone(), Session {
        from, device: p.info.alias.clone(), files: session_files, done: HashSet::new(), saved: Vec::new(),
        received: 0, total, dir,
    });
    {
        let sessions = inner.sessions.lock().unwrap();
        if let Some(s) = sessions.get(&sid) {
            emit_progress(inner, s, "running", None, true);
        }
    }
    let out = serde_json::json!({ "sessionId": sid, "files": tokens });
    (200, serde_json::to_vec(&out).unwrap_or_default())
}

fn emit_progress(inner: &Arc<Inner>, s: &Session, state: &str, error: Option<String>, force: bool) {
    {
        let mut last = inner.last_emit.lock().unwrap();
        if !force && last.elapsed() < Duration::from_millis(120) {
            return;
        }
        *last = Instant::now();
    }
    let _ = inner.app.emit("localsend-progress", Progress {
        direction: "in".into(),
        device: s.device.clone(),
        done_bytes: s.received,
        total_bytes: s.total,
        state: state.into(),
        error,
        saved: s.saved.iter().map(|p| p.to_string_lossy().into_owned()).collect(),
        folder: Some(s.dir.to_string_lossy().into_owned()),
    });
}

async fn upload(inner: &Arc<Inner>, r: &mut BufReader<TcpStream>, req: &Req, from: IpAddr) -> u16 {
    let q = query(&req.target);
    let (Some(sid), Some(fid), Some(token)) = (q.get("sessionId"), q.get("fileId"), q.get("token")) else { return 400 };
    // Check the session, the device and the token, and take what we need.
    let (meta, dir) = {
        let sessions = inner.sessions.lock().unwrap();
        let Some(s) = sessions.get(sid) else { return 403 };
        if s.from != from || s.done.contains(fid) {
            return 403;
        }
        let Some((t, meta)) = s.files.get(fid) else { return 403 };
        if t != token {
            return 403;
        }
        (meta.clone(), s.dir.clone())
    };
    let final_path = unique_path(&dir, &safe_name(&meta.file_name));
    let part = final_path.with_file_name(format!(".{}.part", final_path.file_name().unwrap_or_default().to_string_lossy()));
    let Ok(mut file) = std::fs::File::create(&part) else { return 500 };
    let mut hasher = Sha256::new();
    let mut write_err = false;
    let inner2 = inner.clone();
    let sid2 = sid.clone();
    let got = read_body_into(r, req, meta.size, |chunk| {
        if std::io::Write::write_all(&mut file, chunk).is_err() {
            write_err = true;
            return false;
        }
        hasher.update(chunk);
        let mut sessions = inner2.sessions.lock().unwrap();
        if let Some(s) = sessions.get_mut(&sid2) {
            s.received += chunk.len() as u64;
            emit_progress(&inner2, s, "running", None, false);
            true
        } else {
            false                                   // cancelled meanwhile
        }
    })
    .await;
    drop(file);
    let ok = matches!(got, Some(n) if n == meta.size) && !write_err;
    let hash_ok = match meta.sha256.as_deref() {
        Some(want) if !want.is_empty() => format!("{:x}", hasher.finalize()).eq_ignore_ascii_case(want),
        _ => true,
    };
    if !ok || !hash_ok {
        let _ = std::fs::remove_file(&part);
        let mut sessions = inner.sessions.lock().unwrap();
        if let Some(s) = sessions.remove(sid) {
            let why = if hash_ok { "The transfer broke off" } else { "A file arrived damaged (checksum)" };
            emit_progress(inner, &s, "failed", Some(why.into()), true);
        }
        return if hash_ok { 500 } else { 422 };
    }
    if std::fs::rename(&part, &final_path).is_err() {
        let _ = std::fs::remove_file(&part);
        return 500;
    }
    let mut sessions = inner.sessions.lock().unwrap();
    let finished = if let Some(s) = sessions.get_mut(sid) {
        s.done.insert(fid.clone());
        s.saved.push(final_path);
        s.done.len() == s.files.len()
    } else {
        false
    };
    if finished {
        if let Some(s) = sessions.remove(sid) {
            emit_progress(inner, &s, "done", None, true);
        }
    }
    200
}

// ── Sending ─────────────────────────────────────────────────────────────────────

fn emit_out(app: &AppHandle, device: &str, done: u64, total: u64, state: &str, error: Option<String>) {
    let _ = app.emit("localsend-progress", Progress {
        direction: "out".into(), device: device.into(), done_bytes: done, total_bytes: total,
        state: state.into(), error, ..Default::default()
    });
}

async fn send_files(inner: Arc<Inner>, device: Device, paths: Vec<PathBuf>) -> Result<(), String> {
    let c = client().ok_or("no HTTP client")?;
    let base = base_url(&device.info, device.ip);
    let alias = device.info.alias.clone();
    let mut files = serde_json::Map::new();
    let mut list = Vec::new();
    for (i, p) in paths.iter().enumerate() {
        let meta = std::fs::metadata(p).map_err(|e| format!("{}: {e}", p.display()))?;
        if !meta.is_file() {
            continue;
        }
        let name = p.file_name().unwrap_or_default().to_string_lossy().into_owned();
        let id = format!("f{i}");
        files.insert(id.clone(), serde_json::json!({
            "id": id, "fileName": name, "size": meta.len(), "fileType": mime_for(&name),
        }));
        list.push((id, p.clone(), meta.len()));
    }
    if list.is_empty() {
        return Err("Nothing to send".into());
    }
    let total: u64 = list.iter().map(|(_, _, s)| s).sum();
    emit_out(&inner.app, &alias, 0, total, "waiting", None);
    let resp = c
        .post(format!("{base}/prepare-upload"))
        .timeout(Duration::from_secs(120))                   // they decide on their phone
        .json(&serde_json::json!({ "info": inner.info, "files": files }))
        .send()
        .await
        .map_err(|e| format!("Couldn't reach {alias}: {e}"))?;
    match resp.status().as_u16() {
        200 => {}
        204 => {
            emit_out(&inner.app, &alias, total, total, "done", None);
            return Ok(());
        }
        403 => {
            emit_out(&inner.app, &alias, 0, total, "declined", None);
            return Ok(());
        }
        409 => return Err(format!("{alias} is busy with another transfer")),
        401 => return Err(format!("{alias} asks for a PIN (turn it off in LocalSend there)")),
        s => return Err(format!("{alias} answered {s}")),
    }
    #[derive(Deserialize)]
    #[serde(rename_all = "camelCase")]
    struct Prepared {
        session_id: String,
        files: HashMap<String, String>,
    }
    let prepared: Prepared = resp.json().await.map_err(|e| e.to_string())?;
    let sent = Arc::new(AtomicU64::new(0));
    for (id, path, size) in list {
        let Some(token) = prepared.files.get(&id) else { continue };   // they took only some
        let file = tokio::fs::File::open(&path).await.map_err(|e| e.to_string())?;
        let sent2 = sent.clone();
        let app2 = inner.app.clone();
        let alias2 = alias.clone();
        let last = Arc::new(Mutex::new(Instant::now()));
        let stream = futures_util::stream::unfold(file, move |mut f| {
            let sent3 = sent2.clone();
            let app3 = app2.clone();
            let alias3 = alias2.clone();
            let last2 = last.clone();
            async move {
                let mut buf = vec![0u8; 256 * 1024];
                match f.read(&mut buf).await {
                    Ok(0) => None,
                    Ok(n) => {
                        buf.truncate(n);
                        let now = sent3.fetch_add(n as u64, Ordering::Relaxed) + n as u64;
                        let mut l = last2.lock().unwrap();
                        if l.elapsed() > Duration::from_millis(120) {
                            *l = Instant::now();
                            emit_out(&app3, &alias3, now, total, "running", None);
                        }
                        Some((Ok::<Vec<u8>, std::io::Error>(buf), f))
                    }
                    Err(e) => Some((Err(e), f)),
                }
            }
        });
        let url = format!("{base}/upload?sessionId={}&fileId={}&token={}", prepared.session_id, id, token);
        let r = c
            .post(url)
            .header("Content-Length", size.to_string())
            .header("Content-Type", "application/octet-stream")
            .body(reqwest::Body::wrap_stream(stream))
            .send()
            .await
            .map_err(|e| format!("Sending to {alias} broke off: {e}"))?;
        if !r.status().is_success() {
            let _ = c.post(format!("{base}/cancel?sessionId={}", prepared.session_id)).send().await;
            return Err(format!("{alias} refused a file ({})", r.status()));
        }
    }
    emit_out(&inner.app, &alias, total, total, "done", None);
    Ok(())
}

// ── Commands ────────────────────────────────────────────────────────────────────

/// The devices nearby (and a fresh announcement, so new ones show up).
#[tauri::command]
pub async fn localsend_devices() -> Vec<DeviceView> {
    let Some(inner) = LS.get().cloned() else { return Vec::new() };
    announce(&inner).await;
    device_list(&inner)
}

/// His answer to an incoming transfer.
#[tauri::command]
pub fn localsend_answer(id: u64, accept: bool) -> bool {
    let Some(inner) = LS.get() else { return false };
    let tx = inner.pending.lock().unwrap().remove(&id);
    tx.map(|t| t.send(accept).is_ok()).unwrap_or(false)
}

/// Sends files to a device (progress comes as `localsend-progress`).
#[tauri::command]
pub async fn localsend_send(device: String, paths: Vec<String>) -> Result<(), String> {
    let inner = LS.get().cloned().ok_or("LocalSend isn't running")?;
    let dev = inner.devices.lock().unwrap().get(&device).cloned().ok_or("That device is gone")?;
    let paths: Vec<PathBuf> = paths.into_iter().map(PathBuf::from).filter(|p| p.is_file()).collect();
    let alias = dev.info.alias.clone();
    let app = inner.app.clone();
    let result = send_files(inner, dev, paths).await;
    if let Err(e) = &result {
        emit_out(&app, &alias, 0, 0, "failed", Some(e.clone()));
    }
    result
}

/// This PC's name on LocalSend and the port it listens on (for the page).
#[tauri::command]
pub fn localsend_me() -> Option<(String, u16)> {
    LS.get().map(|i| (i.info.alias.clone(), i.info.port.unwrap_or(PORT)))
}

/// Opens the folder (Downloads) or shows a received file.
#[tauri::command]
pub fn localsend_open(path: String) -> bool {
    let p = PathBuf::from(&path);
    let dl = downloads();
    // Only inside Downloads: this opens what LocalSend saved, nothing else.
    if !p.starts_with(&dl) {
        return false;
    }
    std::process::Command::new("xdg-open").arg(&p).spawn().is_ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn names_are_made_safe() {
        assert_eq!(safe_name("../../etc/passwd"), "passwd");
        assert_eq!(safe_name("C:\\Users\\x\\photo.jpg"), "photo.jpg");
        assert_eq!(safe_name(".bashrc"), "bashrc");
        assert_eq!(safe_name(""), "file");
        assert_eq!(safe_name("a\u{0}b?.txt"), "ab.txt");
        assert!(safe_name(&"x".repeat(500)).len() <= 180);
    }

    #[test]
    fn taken_names_get_a_number() {
        let dir = std::env::temp_dir().join(format!("ls-test-{}", random_hex(4)));
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("a.jpg"), b"x").unwrap();
        assert_eq!(unique_path(&dir, "a.jpg"), dir.join("a (2).jpg"));
        assert_eq!(unique_path(&dir, "b.jpg"), dir.join("b.jpg"));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn queries_and_tokens() {
        let q = query("/api/localsend/v2/upload?sessionId=ab%20c&fileId=f1&token=t");
        assert_eq!(q.get("sessionId").map(String::as_str), Some("ab c"));
        assert_eq!(q.get("fileId").map(String::as_str), Some("f1"));
        assert_eq!(random_hex(16).len(), 32);
        assert_ne!(random_hex(8), random_hex(8));
        assert_eq!(mime_for("x.JPG"), "image/jpeg");
        assert_eq!(mime_for("x.unknown"), "application/octet-stream");
    }

    #[test]
    fn info_reads_what_phones_send() {
        let raw = r#"{"alias":"Pixel","version":"2.1","deviceModel":"Google","deviceType":"mobile","fingerprint":"abc","port":53317,"protocol":"https","download":false,"announce":true}"#;
        let i: Info = serde_json::from_str(raw).unwrap();
        assert_eq!(i.alias, "Pixel");
        assert_eq!(i.announce, Some(true));
        assert_eq!(base_url(&i, "192.168.1.5".parse().unwrap()), "https://192.168.1.5:53317/api/localsend/v2");
        let prep: PrepareUpload = serde_json::from_str(r#"{"info":{"alias":"P","fingerprint":"x"},"files":{"a":{"id":"a","fileName":"p.png","size":3,"fileType":"image/png"}}}"#).unwrap();
        assert_eq!(prep.files["a"].size, 3);
    }
}

// ── Picking files (the desktop's own file chooser) ─────────────────────────────

/// Opens the desktop's file chooser (the XDG portal: the same window every app uses) and returns the files he
/// picked, or nothing if he closed it.
#[tauri::command]
pub async fn pick_files(title: String) -> Vec<String> {
    tauri::async_runtime::spawn_blocking(move || portal_open_files(&title).unwrap_or_default())
        .await
        .unwrap_or_default()
}

#[cfg(target_os = "linux")]
fn portal_open_files(title: &str) -> Option<Vec<String>> {
    use dbus::arg::{PropMap, RefArg, Variant};
    use dbus::blocking::Connection;
    use dbus::message::MatchRule;

    let conn = Connection::new_session().ok()?;
    let token = format!("clove{}", random_hex(6));
    let sender = conn.unique_name().to_string();
    let sender = sender.trim_start_matches(':').replace('.', "_");
    let request = format!("/org/freedesktop/portal/desktop/request/{sender}/{token}");
    let picked: Arc<Mutex<Option<Vec<String>>>> = Arc::new(Mutex::new(None));
    let sink = picked.clone();
    // Listen for the answer before asking, so a quick one isn't missed.
    let rule = MatchRule::new_signal("org.freedesktop.portal.Request", "Response")
        .with_path(dbus::Path::new(request).ok()?);
    conn.add_match(rule, move |(code, results): (u32, PropMap), _, _| {
        let mut out = Vec::new();
        if code == 0 {
            if let Some(iter) = results.get("uris").and_then(|v| v.0.as_iter()) {
                for uri in iter.filter_map(|u| u.as_str().map(str::to_string)) {
                    if let Some(path) = uri.strip_prefix("file://") {
                        out.push(percent_decode(path));
                    }
                }
            }
        }
        *sink.lock().unwrap() = Some(out);
        false
    })
    .ok()?;
    let mut options = PropMap::new();
    options.insert("handle_token".into(), Variant(Box::new(token)));
    options.insert("multiple".into(), Variant(Box::new(true)));
    let proxy = conn.with_proxy("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop", Duration::from_secs(10));
    let _: (dbus::Path,) = proxy
        .method_call("org.freedesktop.portal.FileChooser", "OpenFile", ("", title, options))
        .ok()?;
    // He may take his time choosing.
    let until = Instant::now() + Duration::from_secs(600);
    while Instant::now() < until {
        let _ = conn.process(Duration::from_millis(500));
        if let Some(files) = picked.lock().unwrap().take() {
            return Some(files);
        }
    }
    None
}

#[cfg(not(target_os = "linux"))]
fn portal_open_files(_title: &str) -> Option<Vec<String>> {
    None
}
