"""Offer the model only the tools a request can need.

Sending all ~110 tool definitions on every turn costs thousands of tokens, slows the reply and makes wrong picks
more likely. A request gets the CORE tools plus the groups its words point at, plus whatever it used in the last
few turns (so "and restart it" still has `service`). Pure keyword matching: instant and free.
"""
import re

CORE = {"run_command", "open_url", "web_search", "open_app", "look_at_screen", "set_reminder", "remember", "recall",
        "todo", "show_plan", "update_step", "record_approval", "ask_gemini", "job_status", "cancel_job",
        "switch_brain", "recall_research", "answer_agent"}

GROUPS = [
    (r"\b(chrome|tab|tabs|page|site|website|click|scroll|type|fill|form|whatsapp|gmail|email|mail|linkedin|github|"
     r"youtube|login|log in|sign in|bookmark|reply|message|chat|send)\b",
     {"browser", "open_bookmark", "find_bookmarks", "delegate_to_claude"}),
    (r"\b(file|files|folder|directory|dir|note|notes|script|config|open .*\.(?:py|md|txt|json|pdf)|read|write|save|"
     r"document|pdf|summari[sz]e)\b",
     {"search_files", "open_path", "read_file", "write_file", "list_dir", "summarize_document"}),
    (r"\b(volume|louder|quieter|mute|music|song|play|pause|resume|next|previous|skip|spotify|youtube|video)\b",
     {"volume", "media", "play_spotify", "play_youtube"}),
    (r"\b(anton|server|homelab|machine|docker|container|service|restart|logs?|disk|memory|ram|cpu|uptime|systemd|"
     r"jellyfin|gitea|immich|ssh|health|status|running|down|crash(?:ed|ing)?)\b",
     {"machine_overview", "service", "anton_status", "anton_tools", "anton_run", "anton_events", "talk_to_anton"}),
    (r"\b(code|coding|bug|fix|build|project|repo|repository|refactor|test|tests|function|app|feature|commit|push|"
     r"pull request|pr|merge|branch|git|kilo|opencode|claude|codex|agent)\b",
     {"delegate_to_claude", "delegate_to_opencode", "delegate_to_agent", "agents_status", "git_status",
      "git_commit_push", "open_pr", "code_review", "pr_status", "pr_merge"}),
    (r"\b(call|phone|ring|meet|google meet|dial|hang up|answer)\b",
     {"call", "call_me", "call_me_free", "hangup_call", "mobile_call_status", "mobile_call_answer",
      "mobile_call_hangup", "mobile_call_list"}),
    (r"\b(morning|night|weekly|routine|plan for today|my day|log my day|what'?s left|finished|done with|review)\b",
     {"run_routine", "routine_reply", "day_status", "day_update", "morning_briefing"}),
    (r"\b(research|find out|look into|compare|in depth|everything about|investigate)\b",
     {"deep_research"}),
    (r"\b(where|point|show me|screen|error|button|icon|highlight|watch)\b",
     {"point_at", "clear_pointer", "debug_screen", "screen_watch_start", "screen_watch_stop", "screen_watch_add"}),
    (r"\b(window|maximi[sz]e|minimi[sz]e|move|resize|terminal|clipboard|copy|paste)\b",
     {"window", "run_in_terminal", "clipboard"}),
    (r"\b(install|uninstall|package|extension)\b", {"install_packages", "install_gnome_extension"}),
    (r"\b(text me|telegram|notify me)\b", {"text_me"}),
    (r"\b(habit|streak)\b", {"log_habit", "habit_status", "list_habits"}),
    (r"\b(macro|record (?:my|these) steps|replay)\b", {"macro_record_start", "macro_record_stop", "macro_list", "macro_replay"}),
    (r"\b(translate|in hindi|in english|in spanish|in french)\b", {"translate"}),
    (r"\b(dictat|type (?:this|that|what i say|it))\w*", {"dictate", "type_text"}),
    (r"\b(shortcut|shortcuts|learned|taught yourself)\b", {"learned_shortcuts"}),
    (r"\b(focus|pomodoro|distract|deep work)\b", {"focus"}),
    (r"\b(show me how|teach me|walk me through|guide me|how do i|tour)\b", {"guide", "point_at"}),
    (r"\b(pair|watch my code|review as i (?:code|go))\b", {"pair_mode"}),
    (r"\b(remember|memory|palace|forget)\b", {"forget", "palace_remember", "palace_recall", "palace_list"}),
    (r"\b(second opinion|what do you think rose|ask rose|rose,? what)\b", {"second_opinion"}),
    (r"\b(ghost|incognito|private mode)\b", {"ghost_mode"}),
    (r"\b(semantic|search (?:my )?(?:files|memory))\b", {"semantic_search"}),
    (r"\b(weather|outfit|wear)\b", {"weather_outfit"}),
]
GROUPS = [(re.compile(p, re.I), names) for p, names in GROUPS]
MAX_TOOLS = 40


class Picker:
    def __init__(self, declarations):
        # `behavior` (NON_BLOCKING background tools) only exists in the Live API; the text API rejects it.
        self.by_name = {d.name: d.model_copy(update={"behavior": None}) for d in declarations}
        self.recent: list[set[str]] = []           # tools used in the last few turns

    def used(self, names: set[str]):
        self.recent = (self.recent + [set(names)])[-3:]

    def names_for(self, text: str) -> list[str]:
        want = set(CORE)
        for pattern, names in GROUPS:
            if pattern.search(text or ""):
                want |= names
        for names in self.recent:
            want |= names
        picked = [n for n in self.by_name if n in want]            # keep declaration order (stable prompts)
        return picked[:MAX_TOOLS]

    def pick(self, text: str) -> list:
        return [self.by_name[n] for n in self.names_for(text)]
