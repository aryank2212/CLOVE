# CLOVE: the full guide


_Paths below are relative to `assistant/`. The short version is the [README](../README.md)._
A voice butler duo for this PC. **Clove** is the male voice, **Rose** is the female voice - switchable any time by saying "switch to Rose" or "switch to Clove". One of two **brains** does the everyday work itself (apps, bookmarks, files, notes and small scripts, volume,
music, reminders, questions) and only hands genuinely complex work to **Claude Code** in a terminal or
**Claude in Chrome**, then tells you how it went. The brains: **Gemini Live** (cloud: fast, best quality) and
**Qwen 3.8 27B** (runs on this PC: private, works offline, slower). Switch between them any time.

## Run

```bash
./run.sh            # in a terminal; normally it already runs as a service (below)
./run.sh --text     # no mic/speaker, type in the window
./run.sh --devices  # list audio devices (for MIC_DEVICE / SPEAKER_DEVICE in .env)
./run.sh --doctor   # checks key, audio, Chrome extension, Qwen, OpenCode, memory - and says how to fix each
tests/run_all.sh    # all tests; safe while Clove runs (temp memory file, isolated Chrome on port 8799)
```

Put your key in `.env` (`GEMINI_API_KEY=...`, see `.env.example` for every setting). Launching again while it runs
just brings the window back; it never runs twice. Started from a terminal, closing its window quits it.

### Starting with your session

`scripts/install_autostart.sh` installs the systemd user service `clove` (in `~/.config/systemd/user`): CLOVE starts
when you log in, with no window and no terminal, waits up to two minutes for this folder's drive to be mounted, and
is restarted if it crashes. Closing the window never stops it.

```bash
systemctl --user start clove      # now (a copy already running from a terminal wins: close that first)
systemctl --user stop clove       # until the next login
journalctl --user -u clove        # why it did or didn't start
scripts/install_autostart.sh --remove
```

Clove Notch starts at login on its own (its General page, "Open at login"). The Chrome extension loads
whenever Chrome runs; CLOVE opens Chrome itself when it needs the browser.

## What it does

| You say | Who does it |
|---|---|
| "open my LeetCode bookmark", "open a terminal", "what time is it" | Clove, instantly |
| "write a script that…", "make a note…", "volume down", "pause the music", "remind me in 20 minutes" | Clove, instantly |
| "install htop", "maximize Chrome" (needs the Window Calls extension) | Clove, after you approve the plan |
| "add a settings page to my clove project", "build me a Flask app…" | Claude Code in a terminal (complex work only) |
| "star the anthropic SDK repo on GitHub", "fill in this form" | Claude in Chrome |
| "explain how attention works in transformers" | a stronger Gemini text model |
| "what's on my screen?", "read that error", "where is the submit button?" | Clove looks at a screenshot; for "where…" his glowing cursor glides to it and highlights it |
| "what's my morning plan?", "run my night log", "how was my week?" | Your three scheduled Claude tasks, run on demand (see **Routines**) |
| "research X in depth" | Claude reads many sources for a few minutes while Clove talks you through it |

- **Plans**: multi-step requests get a checklist in the window, done one step at a time and ticked off live
  (Claude reports each step as it finishes it).
- **Approval**: anything that installs, deletes or changes the system shows the plan first and waits for
  "yes" (or the Approve button). Packages install with your system's package manager (pacman, apt, dnf or zypper) through `pkexec`, so the desktop asks for your password.
- **Claude terminals** show readable progress, close themselves 5 s after finishing (failures stay open),
  and Clove notices if you close one early. Each run is kept in `tasks/<id>/` for a week.

## Natural turn-taking (talking to Clove, and on calls)

Clove decides when you have finished speaking instead of answering after a fixed half-second of silence (`SMART_TURNS=on`,
`turn_taking.py`). When you pause, a small local Whisper model reads how your words end:
- a question, a short reply ("yes", "okay") or a complete command ("open YouTube") -> answered after ~0.5-0.9 s;
- an ordinary sentence -> ~1 s;
- mid-thought ("send Mom a message saying...", "so I was thinking", "um", "tell him") -> it waits up to 3 s.
Talking over Clove pauses his voice at once; "mm-hm"/"okay"/"haan" lets him carry on, while "stop", "wait", "no", "sorry"
or a real sentence stops him and he listens. `SMART_TURNS=off` goes back to Gemini's own fixed rule (`VAD_SILENCE_MS`).

## Two brains: Gemini and Qwen

| | Gemini (cloud) | Qwen (this PC) |
|---|---|---|
| Hears you with | Gemini Live | Whisper large-v3-turbo on the GPU |
| Thinks with | Gemini | `qwen3.8:27b` via Ollama |
| Speaks with | Gemini's voice (Algieba) | Kokoro, a deep British voice |
| Needs | `GEMINI_API_KEY`, internet | `scripts/install_local.sh` (about 20 GB), no internet |
| Speed | replies in ~1-2 s | instant commands ("open my YouTube", volume, time, "what's left") are answered by code; other replies are slower (see **Good to know**) |

**How fast is Qwen here?** Measured on this PC (RTX 4060 with 8 GB, 31 GB RAM): `qwen3.8:27b` is a 17 GB model, so
about two thirds of it runs on the CPU, which limits it to roughly **3-4 words per second** (the model's built-in
multi-token prediction is already on). So Clove works around it:
- **Instant commands never touch the model**: open a bookmark/site/app, search, volume, media, time/date, reminders,
  "what's left", "I finished X", the three routines, "what's on my screen", "where is the … icon": **~0.5 s**.
- Simple tool results are confirmed by code ("Opening YouTube, sir."), skipping a second model pass.
- Anything else goes to the model: a short answer starts speaking after **~7 s**; a request that needs a tool
  (and a spoken result) takes **~10-13 s**. Each reply is capped short; sentences are spoken as they're written.
- Gemini answers in 1-2 s, so use Qwen when you want **private/offline**, Gemini when you want **fast**.
- Taking over from Gemini takes ~30 s the first time (loading Whisper and the model, while Gemini keeps talking),
  then ~0.2 s while Qwen is still warm.
- `LOCAL_GPU_LAYERS` (default auto) decides how much of the model sits on the GPU; Whisper shares that GPU.

**Switching**: click the **Gemini | Qwen** toggle in the window (or press **Alt+B**), or just say *"switch to Qwen"* /
*"switch to Gemini"* (also "go back to Gemini", "use the local one"). The other brain **warms up first while the
current one keeps talking**, then takes over by itself with the conversation carried across (so there's no dead air
and it doesn't forget what you were doing), and says a short "Qwen here, sir." Everything running keeps running:
Claude jobs, plans, today's memory, the cursor. The choice is remembered for the next start (`BRAIN=` pins one).
After a switch away, Qwen stays in memory for `LOCAL_KEEP_WARM_MIN` minutes so switching back is quick, then the GPU
is freed. Screen vision, pointing, `ask_gemini` and research still use your Gemini key from either brain.

## Calls on your behalf (WhatsApp Web, Google Meet)

Ask: *"call Rahul on WhatsApp and tell him I'll be 15 minutes late, and ask whether to bring the report"* or *"join this Meet
(abc-defg-hij) and say I'm running 5 minutes behind"*. Clove reads back who, where and what it will say, waits for your
**yes**, then opens the chat, places the call, waits until it is answered, and talks to them in **its own voice** (a second
Gemini Live session just for the call), keeping to the mission you gave it.

- **You hear everything live**: the caller *and* Clove, about 80 ms delayed, through your normal speakers/headphones. The
  window shows the running transcript. With headphones you can keep talking to Clove normally during the call
  (*"tell her 5 pm"* is passed into the call). On speakers Clove ignores its microphone while call audio is playing, so it
  can't mistake the caller for you; headphones are better.
- **Take over any time**: *"I'll talk"* (Clove goes silent and your real microphone goes into the call), *"carry on"* (Clove
  resumes), *"hang up"*.
- **Every call command is scoped to its own tab**: a Meet you have open can't be mistaken for the WhatsApp call you just
  placed (that bug made Clove think a ringing call had connected), and "end call" only ever hangs up the call it started.
  While it works, the log shows what it sees: `call state: ...`, which Chrome streams were routed to it, and the loudest sound
  it has heard from the call (`call audio: ...`). If nothing is audible after 14 s it tells you instead of staying silent.
- **It starts only when the call truly connects** (the call timer is running; ringing and the ring tone never count), waits a
  moment for the person to say hello, then (if nobody speaks for 15 s it says just *"Hello?"*, and gives up after 25 s) opens with *"Hello <name>, this is Clove."* and gets to the point, and hangs up as
  soon as it is done. It doesn't say "AI assistant" or whose assistant it is unless asked (`CALL_DISCLOSE=on` adds
  *"<you>'s AI assistant"* to the greeting), but it always answers honestly if asked who or what it is, never imitates your voice, never agrees to money or
  commitments, never gives out passwords/codes/card or ID details, hands anything unexpected back to you, and stops after
  `CALL_MAX_MINUTES` (10). Note that the other person's audio is processed by Gemini and kept as a text transcript in memory.
- **How the audio works**: two virtual devices (PipeWire). The call tab's microphone is Clove' voice, the call tab's sound
  goes to Clove, and both are looped to your speakers. Only audio Chrome opens *after* the call starts is touched (your music
  or another meeting is left alone); everything is put back and removed when the call ends. First call: Chrome asks to allow
  the microphone for web.whatsapp.com / meet.google.com: click Allow once.
- **Already in a call? Say "take over"**: Clove finds the call running in Chrome (Meet or WhatsApp), mutes your other sounding tabs
  for the duration, moves the call's audio onto its virtual devices and carries on from there ("Hello everyone, this is Clove,
  <you>'s AI assistant. <you> asked me to take over..."). **"Join the meeting link in the group"** finds the Meet link in the open
  chat; if that meeting is already open in a tab it reuses it instead of opening a second copy. **A group call running in a WhatsApp
  chat** ("Ongoing call"): Clove presses Join and takes part. Ask "is there a call going on?" any time.
- **Meet you had already joined**: if you joined the meeting yourself before asking Clove to start/take over, Chrome's audio for
  that meeting already exists, so once the call is confirmed live Clove takes over *all* of Chrome's audio streams (your other
  sounding tabs are muted first and restored afterwards). In a meeting it also no longer hangs up when nobody speaks for a while.
- **Out-of-date extension**: Chrome only picks up extension changes when you press Reload on `chrome://extensions`. Clove now compares
  versions when the extension connects, tells you in the window, and every call error says so plainly (the old behaviour was a silent
  failure). `./run.sh --doctor` shows it too.
- Answer an incoming WhatsApp call for you: *"answer the call and tell them I'll call back in an hour"*.
- Caveat: WhatsApp Web's call screen changes often; the controls are matched by their labels and tested on mock pages, so the first
  real call may need a small selector fix (`./run.sh --doctor`, and the buttons it can see are shown in the log).

## Qwen: fast voice model + big coding model

The voice brain runs **`qwen3:8b`**, which fits entirely on the 8 GB GPU: about 40 tokens/s, a tool call in under a
second (the 27B managed 2-3 tokens/s because two thirds of it ran on the CPU). Memory, to-do and quick Chrome commands
are answered by code with no model at all. The 27B (`qwen3.8-oc`) stays for **OpenCode coding jobs**, where quality
matters more than speed. Qwen only sees a compact 24-tool list (~2,000 tokens), because its context window is small.
Set `LOCAL_MODEL=` to change the voice model. Compare models: `.venv/bin/python tests/bench_local.py MODEL [gpu_layers]`.

## Qwen runs only when needed

Ollama is no longer a background service (disabled at login). It starts when you switch to Qwen or give OpenCode a
job, and **unloads the model and stops again** 2 minutes after you switch back to Gemini (`LOCAL_KEEP_WARM_MIN`),
90 seconds after an OpenCode job ends, and when Clove quits. `STOP_OLLAMA_WHEN_IDLE=off` keeps the server up (the
model still unloads). To start it at login again: `systemctl --user enable ollama`.

## OpenCode on Qwen, and Chrome control

**OpenCode (coding by voice)**: say *"use opencode to add a login page to my flask app"* (or just ask for coding work).
Clove opens OpenCode in a terminal on the local Qwen model (`OPENCODE_MODEL`, default `qwen3.8-oc` = the same
`qwen3.8:27b` with a 16k context, made by `ollama create qwen3.8-oc`; OpenCode needs far more than Ollama's 4k default,
without it the model never sees the task. Expect minutes per job on this GPU, not seconds; registered in
`~/.config/opencode/opencode.json`), narrates what it is doing every few seconds, and reports the result.
Say "open opencode live" for the interactive OpenCode screen if you want to steer it yourself.

**Chrome control (Clove Hands extension)**: a Manifest V3 extension in `chrome_extension/`, built the way Claude in
Chrome works: a connection to this app, page reading with numbered elements, and real (debugger) clicks and typing.
1. Open `chrome://extensions`, switch on **Developer mode**, **Load unpacked**, pick the `chrome_extension` folder.
2. Start Clove. The extension icon shows **ON** when connected (only that extension can connect: the socket checks its fixed ID).
3. Say *"new tab"*, *"close this tab"*, *"close the github tab"*, *"switch to youtube tab"*, *"go back"*, *"scroll down"*,
   *"click sign in"*, *"type hello in the search box and press enter"*: answered instantly by code. Longer web tasks
   are done by the brain step by step: read, click, type, read again.
While the debugger is attached Chrome shows a "started debugging this browser" bar; it goes away seconds after the last action.

### Memory, to-dos and what is on your screen

- **Self-managing memory**: conversation older than 45 days is folded into one short searchable digest per day (kept
  forever); only if the file outgrows a tenth of your free disk (at least 2 GB) are the oldest raw turns dropped
  (`MEMORY_MAX_MB=<n>` sets a hard cap instead). Every 30 minutes Gemini reads the new conversation and saves the
  lasting facts and to-dos by itself (never passwords or card numbers). To-dos take due dates ("by friday",
  "tomorrow") and can be listed as today / overdue / this week. `python memory.py stats|search WORDS|todos|tidy|export FILE`.
- **Long-term memory**: `~/.local/share/clove/memory.db` (SQLite, **no fixed cap**: it grows as needed and tidies itself). It keeps facts you tell it ("remember that…"), your **to-do list** ("add X to my
  to-do", "what's on my list", "I did X", also whatever Clove finds in Notion), the **full result of every research /
  Claude / OpenCode job** (searchable; ask "what did you find?" and he reads all of it), the conversation, and what you
  were last doing. Both brains load it at start, so it survives restarts. Tools: `remember`, `recall`, `todo`, `recall_research`.
- **Finds things by meaning**: "when is my sister's birthday" finds "Priya's birthday is 14 November" (Gemini
  embeddings stored in the same file; plain word search when offline). Unknown things come back as unknown, not guesses.
- **Knows what you're looking at**: the extension pushes every tab change (and which WhatsApp chat is open, checked
  every 3 s) to Gemini as a silent note, so it acts at once instead of asking Chrome first.
- **Knows what you're looking at (details)**: the extension reports your active tab, so with WhatsApp on screen "open Sam's
  chat" opens that chat in WhatsApp (never a file search). "Open WhatsApp" switches to the WhatsApp tab that is already
  open; only "another/new one" opens a second. Typing goes to the named box (message vs search), and WhatsApp
  messages are sent with `wa_chat` + `wa_send`.
- **Clove Hands v3 can**: reuse tabs by app name ("open WhatsApp", "gmail", "youtube"); read pages and see your
  highlighted text; click (by text, "the second Reply", inside a named section), hover (CSS menus too), drag and drop,
  tick boxes, pick dropdown options, **fill a whole form** in one go; control video/audio (play, pause, skip 10 s,
  speed, fullscreen); pin/mute/duplicate/reopen tabs, zoom, group tabs, search history and bookmarks, bookmark a page;
  wait for slow pages and late-appearing buttons. It sees inside iframes and shadow DOM, notices when a click opens a
  new tab, and if a page ignores a normal click it clicks with a real mouse (the debugger bar then shows for a moment).
  A brief green ring shows what it is acting on.
- **No more "started debugging" bar**: clicks and typing use ordinary page events; the debugger is only a last resort.
- After updating the extension: `chrome://extensions` -> reload **Clove Hands**, then restart Clove.

## Routines and today's memory

Your three scheduled Claude tasks (they live on your Claude account; their instructions are copied word for word
into `routines/*.md`) run on demand, headless, with Claude reading your Notion plan and your Night Log:

| Say | Runs | Then |
|---|---|---|
| "what's my morning plan?" | **Morning Plan** | Clove tells you yesterday, today's tasks and the focus, and saves the tasks in **today's memory** |
| "run my night log" | **Night Log check-in** | Claude's questions come back; Clove asks you them conversationally, then sends all your answers into the *same* Claude conversation; Claude reviews, drafts the X post and saves the entry; Clove then **closes today's memory** |
| "weekly review" | **Weekly Roadmap Review** | numbers, verdict and next week; the X thread is on screen (say "copy it") |

- **Today's memory** (`~/.local/state/clove/day.json`) lives from the morning plan until the night log: not per
  session, not per 24 h. Restart Clove as often as you like and he still knows. Tell him what you did ("I
  finished the DSA set") and he ticks it off; ask "what's left?" any time. Things done that weren't on the plan are
  remembered too. The night log is Claude's to remember, so closing the day just deletes this file. A new morning
  plan replaces whatever was left.
- **Conversations continue**: answers and follow-ups go back into the same Claude session (`claude --resume`),
  also after a restart ("continue my night log").
- **After midnight** the night log is for the day that just ended; in the evening it's for today (or say
  "for yesterday").
- **Editing a task in Claude?** Update the matching file in `routines/` (the body is the task's prompt). Clove adds
  a short voice adapter on top, so don't put the adapter in the file.
- **Your own versions** go in `routines/local/` (git ignores it): a file there with the same `key` replaces the
  default, so your prompts, links and trigger ids stay on your PC.
- `ROUTINES_TERMINAL=on` shows a terminal while a routine runs; `CLOVE_ROUTINES_DRY_RUN=1` is a test switch that
  stops the night log from saving anything.

## Seeing, pointing, narrating

- **Screen**: only when you ask. Clove takes one screenshot (GNOME's own screenshot portal, so you may see the
  usual flash), sends it to Gemini vision, and deletes the file straight away. Nothing is stored. Don't ask him to
  look while a password or private message is open.
- **Cursor**: a transparent, click-through overlay (an XWayland window), so your own mouse and clicks pass
  straight through it. It only points; it never moves or clicks your real mouse. Say "hide the cursor", or press
  Esc, to dismiss it early.
- **Narration**: during long Claude jobs and research Clove says what is happening ("I'm reading python.org…")
  about every 15 s while nobody is talking, and says "still on it" if a step takes long. The same steps show in
  the window. Claude is asked to announce each major step in a sentence, which is what you hear.

## Window: CLOVE

One page (`ui/index.html`, `ui/clove.css`, `ui/clove.js`, fed by `dashboard.py`), shown inside Clove Notch's
window on its **Assistant** pages when Clove Notch is installed, else in a Chrome app window. It has Clove Notch's
look (`docs/DESIGN.md`): a black sidebar, a graphite panel, and a band on top of each page where its colour glows.
- **Sidebar**: Conversation, Activity, Systems, Preferences (Ctrl+1–4), the command palette (Ctrl+K), each
  connection from a real check (brain, Gemini API, Chrome extension, your machines, microphone), and CLOVE's state.
- **Conversation**: the band shows the state in words and the CLOVE mark. The mark walks about while CLOVE waits,
  stops and faces you when it listens, thinks or speaks; its ring follows your voice and CLOVE's, spins while it
  works and turns amber when a plan needs your yes. Click it to make CLOVE listen now, or to stop it speaking. Below:
  the conversation, every tool call as its own row, and the message box (Enter sends, Shift+Enter new line). On the
  right: the current task (plan steps with Approve / Reject), this PC's CPU, memory, GPU, network and disks
  (measured every 2 s; marked stale if updates stop), service health, and the workspace.
- **Activity**: the plan, background jobs, and a timeline of every tool run and notice. Its badge counts a plan
  waiting for approval and unread notices.
- **Systems**: telemetry, storage, service health, workspace, and an on-demand health check of this PC or any machine you added.
- **Preferences** change real things and are saved: brain, voice, wake word, chimes, compact window, reduce motion,
  workspace; it also lists what CLOVE may do and what it always asks about.
- **Ctrl+J** (separate window only): compact companion, a small floating window in the bottom-right corner (on
  Hyprland it is floated, resized and optionally pinned to every workspace). A very small window uses that layout too.

Nothing on screen is simulated: unavailable things say so (no GPU tool, no workspace, service down, data stale).
Motion stops when the window is hidden, and with "Reduce motion" or the system's reduced-motion setting.

## Good to know

- **Headphones**: Clove follows your system's output. With headphones/a headset connected (Bluetooth, USB or
  3.5 mm) he speaks through them *and* listens through their own mic; with nothing connected he uses your default
  speaker and the PC's mic. Connect or disconnect headphones any time: he switches within ~3 s and the window
  shows what is in use (🎧 / 🔈). A Bluetooth headset switches to phone-call sound quality while its mic is open,
  so music playing at the same time sounds muffled; set `PREFER_HEADSET_MIC=off` to listen with the PC mic and
  only *play* through the headphones.
- **Latency**: Bluetooth headsets switch to a low-quality, high-latency "call" mode when their mic is in
  use. For the snappiest replies use a wired/USB mic or the laptop mic (`MIC_DEVICE`) with any output.
- **Echo**: on speakers, the mic is muted while Clove talks (so he doesn't hear himself); interrupt with
  Esc or a click. With headphones you can simply talk over him. Force with `ECHO_GUARD=on|off`.
- **Access**: delegated Claude runs use `CLAUDE_PERMISSION_MODE` (default `bypassPermissions`, i.e. full
  access). Truly destructive shell commands (`rm -rf /`, `mkfs`, …) are always refused.
- **Mishearing**: Clove asks "Pardon me, sir?" instead of guessing. Speaking a little closer to the mic helps
  most; if he cuts you off mid-sentence, raise `VAD_SILENCE_MS` (e.g. 900).
- **Voice**: `GEMINI_VOICE` in `.env`. Deep options: Algieba (default, smooth), Charon, Alnilam, Gacrux, Puck.
- **Clove doesn't hear me**: run `.venv/bin/python agent.py --mic-test`, speak, and check the level meter. Clove picks a real microphone by itself (the system default can be a Bluetooth speaker's
  loopback, which hears music, not you); the choice is logged as `microphone: …`. To force one, set `MIC_DEVICE`
  in `.env` (list them with `--devices`). A Bluetooth headset mic only works after switching the headset to call
  mode (Clove does this itself unless `PREFER_HEADSET_MIC=off`).
- **Logs**: `~/.local/state/clove/clove.log`.

## Free-tier friendly: wake word, Hybrid brain, learned commands

- **Wake word** (`WAKE_WORD=on`): Clove ignores the room until you say "Clove" or "Rose" (at the start, "Clove, open
  YouTube", or the end, "...thanks Clove"). The small CPU Whisper already used for turn-taking reads the name, so
  there's no extra model. The words that woke him are replayed, so one sentence is enough. He stays awake 40 s after
  the last word from either side; "that's all" / "go to sleep" ends it early. While asleep **nothing is sent to
  Gemini**, which is where most of the Live audio quota went. A rising chime means "listening".
- **Hybrid brain** (third button, or "switch to hybrid"): Whisper hears you and Kokoro speaks on this PC, and only
  *text* goes to Gemini Flash-Lite. That's far cheaper on the free tier than Live audio. When Gemini Live runs out of
  quota Clove moves to Hybrid by himself, and from Hybrid to Qwen.
- **Only the tools that fit** (`toolpick.py`): Hybrid and Qwen requests carry ~20 of the ~115 tool definitions,
  picked from your words and the last few turns (Qwen's tool prompt went from ~5,400 to ~1,300 tokens).
- **Learned commands** (`learned.py`): when a model answers the same kind of request with the same harmless tool three
  times ("play X on YouTube", "set the volume to N", "open my X bookmark"), Clove turns it into an instant command
  that runs in code. "Forget that shortcut" removes the last one; learned_shortcuts lists them.
- **Knows what you're looking at**: the focused window (Hyprland or GNOME), and for a terminal its folder and git
  branch, go along with every request, so "commit this" or "what's this error" needs no screenshot.

## Your machines

CLOVE works on this PC and on any machine you add (`MACHINES=server=you@192.168.1.10`, SSH key auth) **itself**:
"how is my server doing" (machine_overview), "show me gitea's logs" / "restart jellyfin" (service), or any command
(run_command with machine=server). Restarts, deletes, installs and sudo wait for your yes; `SERVER_SUDO_PASSWORD`
(the machine's name in capitals) enables sudo there. An optional homelab bridge (`ANTON_HOST`) adds a Forge
execution layer's tools; empty, they are not offered.

## More things he can do

| Say | What happens |
|---|---|
| "start dictation" / hotkey `scripts/clove-ctl dictate` | what you say is typed where your cursor is (local Whisper); "stop dictation" ends it |
| "focus for 50 minutes" | holds back non-urgent updates, nudges you off YouTube/Reddit/…, tells you at the end what came in |
| "show me how to export a PDF in GIMP" | a guided tour: each step spoken, the glowing cursor points at it, waits until you've done it |
| "pair mode on" | watches your project's uncommitted diff and speaks up only when something looks clearly wrong |
| "Rose, what do you think?" | a frank second opinion from a different model |
| text or voice-note your Telegram bot (`PHONE_INBOX=on`) | Clove does it on the PC and texts back; jobs text their results |

**Coding agents can ask you questions** through Clove: register `clove_mcp.py` with an agent
(`claude mcp add clove -- python3 /path/to/clove/clove_mcp.py`, similarly for Codex, Gemini CLI, Kilo, OpenCode).
The agent gets `ask_user` (Clove asks you aloud and returns your answer), `tell_user` and `user_context`.

**Hotkeys** (Hyprland, in `~/.config/hypr/bindings.conf`):
`bind = SUPER, D, exec, /path/to/clove/scripts/clove-ctl dictate` and `bind = SUPER, C, exec, /path/to/clove/scripts/clove-ctl wake`.

## Clove Notch (top of the screen)

`notch/` is a fork of Coucou rebranded as CLOVE (its own name, mark, icon and sounds; see
`notch/CLOVE-FORK.md`). It runs as `clove-notch` (app grid: **CLOVE**, starts at login) and is connected both ways:
its chat asks CLOVE itself (over `~/.local/state/clove/ctl.sock`), and CLOVE shows its own work on Clove Notch as a
**CLOVE** pill: what you asked, each tool as it runs, the reply, finished jobs, and plans waiting for approval with
**Allow / Deny** (`notch.py`). If Clove Notch isn't running, CLOVE simply doesn't report there. Clove Notch's window
is also CLOVE's: its **Assistant** pages show this folder's `ui/` (it reads the address from
`$XDG_RUNTIME_DIR/clove.url`), and offer to start the `clove` service when CLOVE isn't running.


## Instagram DMs (official API)

Instagram's desktop notifications don't say who wrote. With Instagram's own API CLOVE gets every DM with the
sender's name and @username, and can reply, with no browser and no password (`assistant/instagram.py`).

1. In the Instagram app: Settings › Account type and tools › Switch to professional account › Creator (free).
2. At developers.facebook.com: Create app › "Other" › Business › add the **Instagram** product ›
   "API setup with Instagram login". Add your Instagram account (you're its admin, so no app review is needed)
   and **Generate token**: that is `IG_ACCESS_TOKEN`. The app secret on the same page is `IG_APP_SECRET`.
3. A public address for this PC's port 8790 (e.g. a Cloudflare tunnel hostname pointing at it).
4. In the same page's **Configure webhooks**: Callback URL `https://<your hostname>/instagram`, Verify token =
   your `IG_VERIFY_TOKEN`, then subscribe to **messages**.
5. Put the three values in `assistant/.env` and restart CLOVE.

Replies work within 24 hours of their last message. The token lasts 60 days; CLOVE renews it every few weeks.

## Code map

| File | Role |
|---|---|
| `agent.py` | entry point, single-instance lock, logging |
| `base.py` | the shared assistant: mic gate, window state, tool/plan/job plumbing, brain switching |
| `clove.py` | assembles the assistant and its three brains |
| `brain_gemini.py` | the Gemini Live brain (resumable, auto-reconnect), turn handling, tool calls |
| `brain_local.py`, `fastpath.py`, `stt.py`, `tts.py` | the Qwen brain: Whisper → Ollama (Qwen, tools) → Kokoro, plus instant command patterns |
| `scripts/install_local.sh` | installs Ollama (user level, no sudo) and the Qwen model |
| `brain_hybrid.py`, `toolpick.py` | the Hybrid brain (Whisper → Gemini text → Kokoro) and per-request tool picking |
| `wake.py`, `sounds.py` | wake word gate and earcons |
| `learned.py` | instant commands Clove teaches himself |
| `machines.py`, `cli_adapter.py` | commands/health/services on this PC and your machines; headless coding agents with fallback |
| `deskctx.py`, `dictate.py`, `focus.py`, `guide.py`, `pair.py`, `phone.py` | focused-window context, dictation, focus mode, guided tours, pair mode, Telegram inbox |
| `notch.py` | CLOVE's own pill and approval cards on Clove Notch |
| `ctl.py`, `scripts/clove-ctl`, `clove_mcp.py` | control socket, its CLI for hotkeys, and Clove as an MCP server for coding agents |
| `tools.py` | tool declarations, duplicate guard, approval gate, plan tracking |
| `jobs.py` | background jobs: Claude runs, installs, GNOME extensions (GNOME only), Gemini text models |
| `routines.py`, `daymem.py`, `routines/` | your three scheduled tasks, their voice adapter, and today's memory |
| `delegate.py`, `claude_view.py` | launching Claude in a terminal and its progress view |
| `desktop.py` | local actions: apps, bookmarks, files, URLs, windows, shell |
| `audio.py` | mic (high-pass filtered) and interruptible low-latency speaker |
| `prompt.py` | the voice model's instructions |
| `screen.py`, `helpers/screenshot_portal.py` | screenshot via the desktop portal, Gemini vision (describe / locate) |
| `pointer.py` | the on-screen cursor overlay |
| `llm.py` | hedged Gemini calls (best model first, next one if it is slow or busy) |
| `ui.py`, `ui/`, `dashboard.py` | the command-centre window (local websocket, per-run token) and its live data: telemetry, service checks, workspace, settings, window control |
