// Things that happen once and must be seen: a desktop notification (a ride, an
// order, a payment, a call — phone notifications mirrored by KDE Connect arrive
// the same way), a phone call ringing on the paired phone, a fingerprint read,
// a password prompt answered. Each has its own small thread, blocked on the bus
// or on the journal, that forwards what it sees to the page; the page decides
// what it means (src/core/live.ts).

use std::io::{BufRead, BufReader};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicU32, Ordering};
use std::time::Duration;

use dbus::blocking::Connection;
use dbus::message::MessageType;
use serde_json::json;
use tauri::{AppHandle, Emitter};

use crate::island::WINDOW_LABEL;

static NEXT_ID: AtomicU32 = AtomicU32::new(1);

pub fn start(app: AppHandle) {
    spawn("clove-live-notify", app.clone(), notifications);
    spawn("clove-live-calls", app.clone(), phone_calls);
    spawn("clove-live-fprint", app.clone(), fingerprints);
    spawn("clove-live-journal", app, journal);
}

/// Runs `f` again, slowly, whenever it returns (the bus or the journal went away).
fn spawn(name: &str, app: AppHandle, f: fn(&AppHandle)) {
    let _ = std::thread::Builder::new().name(name.into()).spawn(move || loop {
        f(&app);
        std::thread::sleep(Duration::from_secs(10));
    });
}

/// Every notification shown on this desktop, read as a bus monitor: nothing is
/// taken from the notification daemon, which still shows them all.
fn notifications(app: &AppHandle) {
    let Ok(conn) = Connection::new_session() else { return };
    let rules = vec!["type='method_call',interface='org.freedesktop.Notifications',member='Notify'".to_string()];
    let proxy = conn.with_proxy("org.freedesktop.DBus", "/org/freedesktop/DBus", Duration::from_secs(3));
    let became: Result<(), _> = proxy.method_call("org.freedesktop.DBus.Monitoring", "BecomeMonitor", (rules, 0u32));
    if let Err(err) = became {
        crate::log::line(format!("live: cannot watch notifications: {err}"));
        // Not allowed here: no point asking every ten seconds.
        std::thread::sleep(Duration::from_secs(3600));
        return;
    }
    loop {
        match conn.channel().blocking_pop_message(Duration::from_secs(60)) {
            Ok(Some(msg)) => {
                if msg.msg_type() != MessageType::MethodCall || msg.member().as_deref() != Some("Notify") {
                    continue;
                }
                let Ok((app_name, _replaces, _icon, summary, body)) = msg.read5::<String, u32, String, String, String>() else { continue };
                // Our own and the assistant's notifications are not news to us.
                if app_name.eq_ignore_ascii_case("clove-notch") {
                    continue;
                }
                let _ = app.emit_to(
                    WINDOW_LABEL,
                    "live-notification",
                    json!({ "id": NEXT_ID.fetch_add(1, Ordering::Relaxed), "app": app_name, "summary": summary, "body": body }),
                );
            }
            Ok(None) => {}
            Err(_) => return,
        }
    }
}

/// A call on the phone paired with KDE Connect: ringing, answered, missed.
fn phone_calls(app: &AppHandle) {
    let Ok(conn) = Connection::new_session() else { return };
    if conn.add_match_no_cb("type='signal',interface='org.kde.kdeconnect.device.telephony',member='callReceived'").is_err() {
        return;
    }
    loop {
        match conn.channel().blocking_pop_message(Duration::from_secs(60)) {
            Ok(Some(msg)) => {
                if msg.member().as_deref() != Some("callReceived") {
                    continue;
                }
                let Ok((event, number, name)) = msg.read3::<String, String, String>() else { continue };
                let device = msg.path().map(|p| p.to_string()).unwrap_or_default();
                let device = device.trim_start_matches("/modules/kdeconnect/devices/").split('/').next().unwrap_or_default().to_string();
                let _ = app.emit_to(WINDOW_LABEL, "live-call", json!({ "event": event, "number": number, "name": name, "device": device }));
            }
            Ok(None) => {}
            Err(_) => return,
        }
    }
}

/// fprintd says how each fingerprint read went.
fn fingerprints(app: &AppHandle) {
    let Ok(conn) = Connection::new_system() else { return };
    if conn.add_match_no_cb("type='signal',interface='net.reactivated.Fprint.Device'").is_err() {
        return;
    }
    loop {
        match conn.channel().blocking_pop_message(Duration::from_secs(60)) {
            Ok(Some(msg)) => match msg.member().as_deref() {
                Some("VerifyFingerSelected") => auth(app, "fingerprint", None, "Touch the sensor"),
                Some("VerifyStatus") => {
                    let Ok((result, done)) = msg.read2::<String, bool>() else { continue };
                    match result.as_str() {
                        "verify-match" => auth(app, "fingerprint", Some(true), "Fingerprint recognised"),
                        "verify-no-match" => auth(app, "fingerprint", Some(false), "Not recognised"),
                        _ if done => auth(app, "fingerprint", Some(false), "Try again"),
                        _ => {}
                    }
                }
                _ => {}
            },
            Ok(None) => {}
            Err(_) => return,
        }
    }
}

fn auth(app: &AppHandle, method: &str, ok: Option<bool>, detail: &str) {
    let _ = app.emit_to(WINDOW_LABEL, "live-auth", json!({ "method": method, "ok": ok, "detail": detail }));
}

/// What one line of the journal says about an authentication, if anything.
pub fn auth_from_journal(line: &str) -> Option<(&'static str, bool, String)> {
    let lower = line.to_ascii_lowercase();
    // Howdy: face recognition through PAM.
    if lower.contains("howdy") {
        if lower.contains("identified") || lower.contains("success") {
            return Some(("face", true, "Face recognised".into()));
        }
        if lower.contains("fail") || lower.contains("unknown face") || lower.contains("timeout") || lower.contains("no face") {
            return Some(("face", false, "Face not recognised".into()));
        }
        return None;
    }
    // polkit: "Operator of unix-session:1 successfully authenticated as unix-user:ak to gain … for action org.x.y …"
    if lower.contains("successfully authenticated as") {
        let action = line.split("for action ").nth(1).and_then(|a| a.split_whitespace().next()).unwrap_or_default();
        let what = action.rsplit('.').next().unwrap_or_default().replace(['-', '_'], " ");
        return Some(("password", true, if what.is_empty() { "Authenticated".into() } else { format!("Authenticated: {what}") }));
    }
    if lower.contains("failed to authenticate") || (lower.contains("pam_unix(") && lower.contains("authentication failure")) {
        return Some(("password", false, "Authentication failed".into()));
    }
    None
}

/// polkit, sudo and Howdy write their verdicts to the journal.
fn journal(app: &AppHandle) {
    let child = Command::new("journalctl")
        .args(["-f", "-n", "0", "-o", "cat", "-t", "polkitd", "-t", "sudo", "-t", "howdy", "-t", "pam_howdy", "-t", "hyprlock"])
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn();
    let Ok(mut child) = child else {
        std::thread::sleep(Duration::from_secs(3600));
        return;
    };
    if let Some(out) = child.stdout.take() {
        for line in BufReader::new(out).lines().map_while(Result::ok) {
            if let Some((method, ok, detail)) = auth_from_journal(&line) {
                auth(app, method, Some(ok), &detail);
            }
        }
    }
    let _ = child.kill();
    let _ = child.wait();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_journal_is_read_for_verdicts() {
        let ok = "Operator of unix-session:1 successfully authenticated as unix-user:ak to gain TEMPORARY authorization for action org.freedesktop.packagekit.package-install for system-bus-name::1.99";
        assert_eq!(auth_from_journal(ok), Some(("password", true, "Authenticated: package install".into())));
        assert_eq!(
            auth_from_journal("Operator of unix-session:1 FAILED to authenticate to gain authorization"),
            Some(("password", false, "Authentication failed".into()))
        );
        assert_eq!(
            auth_from_journal("pam_unix(sudo:auth): authentication failure; logname=ak uid=1000"),
            Some(("password", false, "Authentication failed".into()))
        );
        assert_eq!(auth_from_journal("[howdy] Identified face as ak"), Some(("face", true, "Face recognised".into())));
        assert_eq!(auth_from_journal("ak : TTY=pts/1 ; COMMAND=/usr/bin/ls"), None);
    }
}
