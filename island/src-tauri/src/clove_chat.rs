// Chat with CLOVE itself. The question goes to the running CLOVE assistant over its control socket
// (`$XDG_STATE_HOME/clove/ctl.sock`, created with mode 0600 so only this user can use it), and CLOVE answers
// with its own brain, memory and tools. Nothing here talks to the network; if CLOVE isn't running the chat
// says so instead of falling back to another provider.

use std::path::PathBuf;
use std::time::Duration;

use serde_json::{json, Value};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::UnixStream;

use crate::chat::{Chat, ChatContext, ChatReply, ModelInfo};

pub const CLOVE: &str = "clove";
/// CLOVE may run a tool or two before it answers.
const TIMEOUT: Duration = Duration::from_secs(180);

fn socket() -> PathBuf {
    let state = std::env::var_os("XDG_STATE_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(std::env::var_os("HOME").unwrap_or_default()).join(".local/state"));
    state.join("clove").join("ctl.sock")
}

pub fn models() -> Vec<ModelInfo> {
    vec![ModelInfo { id: CLOVE.into(), label: "CLOVE".into() }]
}

/// What the island knows about the question, in words CLOVE can act on.
fn with_context(query: &str, context: Option<&ChatContext>) -> String {
    match context {
        Some(ChatContext::File { name, path }) => format!("{query}\n[The file {name} was dropped on the island: {path}]"),
        Some(ChatContext::Window { app_name, title, url }) => {
            let at = url.as_deref().map(|u| format!(" ({u})")).unwrap_or_default();
            format!("{query}\n[He is looking at {app_name}: {title}{at}]")
        }
        None => query.to_string(),
    }
}

/// One question, one answer, over CLOVE's control socket.
pub async fn ask(query: &str) -> Result<String, String> {
    let talk = async {
        let mut stream = UnixStream::connect(socket())
            .await
            .map_err(|_| "CLOVE isn't running. Start it from the CLOVE window (Assistant › Conversation) and ask again.".to_string())?;
        let line = format!("chat {}\n", json!({ "text": query }));
        stream.write_all(line.as_bytes()).await.map_err(|e| e.to_string())?;
        let mut reader = BufReader::new(stream);
        let mut out = String::new();
        reader.read_line(&mut out).await.map_err(|e| e.to_string())?;
        let reply: Value = serde_json::from_str(out.trim()).map_err(|_| format!("CLOVE: {}", out.trim()))?;
        match reply.get("text").and_then(Value::as_str) {
            Some(text) => Ok(text.to_string()),
            None => Err(reply.get("error").and_then(Value::as_str).unwrap_or("CLOVE gave no answer").to_string()),
        }
    };
    tokio::time::timeout(TIMEOUT, talk).await.map_err(|_| "CLOVE took too long to answer.".to_string())?
}

pub async fn send(chat: &Chat, query: String, context: Option<ChatContext>) -> Result<ChatReply, String> {
    let turn = chat.begin(CLOVE);
    let asked = with_context(&query, context.as_ref());
    let answer = ask(&asked).await?;
    chat.commit(&turn, json!({ "role": "user", "content": asked }), json!({ "role": "assistant", "content": answer }),
                &query, &answer);
    Ok(ChatReply { text: answer })
}
