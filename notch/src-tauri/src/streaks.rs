// CLOVE fork: LeetCode for the StandBy streak cards. GitHub and Gitea come from their connections (integrations.rs
// already reads their contribution calendars); LeetCode has no sign-in to connect, only a public profile, so its
// "connection" is his user name and this reads that profile's submission calendar:
//   https://leetcode.com/graphql  matchedUser.userCalendar.submissionCalendar   (JSON: {"<unix time>": count})
// The page (core/streaks.ts) puts the moments on his local days and works out the streaks.

use serde::Serialize;
use std::time::Duration;

const LIMIT: usize = 4 * 1024 * 1024;

#[derive(Serialize, Default, Debug, PartialEq)]
pub struct StreakData {
    /// Moments, unix seconds: the page puts them on his local days.
    pub stamps: Vec<(i64, u32)>,
}

fn valid_user(user: &str) -> bool {
    !user.is_empty() && user.len() <= 64 && user.chars().all(|c| c.is_ascii_alphanumeric() || "-_.".contains(c))
}

pub fn parse_leetcode(json: &str) -> Vec<(i64, u32)> {
    let v: serde_json::Value = serde_json::from_str(json).unwrap_or_default();
    let cal = v["data"]["matchedUser"]["userCalendar"]["submissionCalendar"].as_str().unwrap_or("{}");
    let map: serde_json::Map<String, serde_json::Value> = serde_json::from_str(cal).unwrap_or_default();
    let mut out: Vec<(i64, u32)> = map
        .into_iter()
        .filter_map(|(k, v)| Some((k.parse::<i64>().ok()?, v.as_u64()? as u32)))
        .collect();
    out.sort();
    out
}

async fn get(url: &str, post: Option<String>) -> Result<String, String> {
    if crate::integrations::PAUSED.load(std::sync::atomic::Ordering::Relaxed) {
        return Err("paused".into());
    }
    let parsed = reqwest::Url::parse(url).map_err(|e| e.to_string())?;
    let client = crate::net::client(&parsed, Duration::from_secs(15))?;
    let req = match post {
        Some(body) => client
            .post(parsed)
            .header("Content-Type", "application/json")
            .header("Referer", "https://leetcode.com")
            .body(body),
        None => client.get(parsed),
    };
    let resp = req.header("User-Agent", "Clove-Notch").send().await.map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("{}", resp.status()));
    }
    let body = crate::net::read_capped(resp, LIMIT).await?;
    Ok(String::from_utf8_lossy(&body).into_owned())
}

/// LeetCode's submission calendar for `user` (a public profile).
#[tauri::command]
pub async fn streaks_fetch(user: String) -> Result<StreakData, String> {
    let user = user.trim().trim_start_matches('@').to_string();
    if !valid_user(&user) {
        return Err("Not a valid user name".into());
    }
    let body = serde_json::json!({
        "query": "query($u:String!){matchedUser(username:$u){userCalendar{submissionCalendar}}}",
        "variables": {"u": user},
    })
    .to_string();
    Ok(StreakData { stamps: parse_leetcode(&get("https://leetcode.com/graphql", Some(body)).await?) })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn leetcode_calendar() {
        let lc = r#"{"data":{"matchedUser":{"userCalendar":{"submissionCalendar":"{\"1761264000\": 3, \"1761177600\": 1}"}}}}"#;
        assert_eq!(parse_leetcode(lc), vec![(1761177600, 1), (1761264000, 3)]);
        assert_eq!(parse_leetcode(r#"{"data":{"matchedUser":null}}"#), vec![]);
    }

    #[test]
    fn only_plain_names() {
        assert!(valid_user("aryank2212") && valid_user("neal_wu") && !valid_user("a/../b") && !valid_user(""));
    }
}
