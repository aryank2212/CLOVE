"""Hybrid brain: local ears and voice, Gemini thinking. Mic -> Whisper (GPU) -> Gemini Flash text with tools ->
Kokoro voice. Only text reaches the cloud, which uses a small fraction of the free-tier budget that streaming live
audio does, and every request sees only the tools it needs (toolpick). The models in HYBRID_MODELS are tried in
order; when all are out of quota Clove hands over to Qwen by himself.
"""
import asyncio
import logging
import time
from types import SimpleNamespace

from google.genai import types

import config
from brain_local import SENTENCE_END, LocalBrain
from prompt import system_prompt

log = logging.getLogger("clove")
QUOTA = ("429", "resource_exhausted", "quota", "rate limit")
COOL_S = 120                     # a model that ran out of quota is skipped for this long


class HybridBrain(LocalBrain):
    key = "hybrid"
    label = "Hybrid"

    def __init__(self, a):
        super().__init__(a)
        self.tool_names = set(self.picker.by_name)
        self.cool: dict[str, float] = {}          # model -> skipped until

    def available(self) -> tuple[bool, str]:
        import importlib.util
        if not self.a.client:
            return False, "no GEMINI_API_KEY in .env"
        if any(importlib.util.find_spec(m) is None for m in ("faster_whisper", "kokoro_onnx")):
            return False, "speech packages missing (pip install -r requirements.txt)"
        return True, ""

    async def prepare(self):
        if self.unload_task:
            self.unload_task.cancel()
            self.unload_task = None
        if self.stt is None or self.tts is None:
            self.a.ui.send(type="notice", text="Loading speech models…")
            from stt import STT
            from tts import TTS
            from prompt import vocabulary
            if self.stt is None:
                self.stt = await asyncio.to_thread(STT, vocabulary())
            if self.tts is None:
                self.tts = await asyncio.to_thread(TTS)
        self.system = system_prompt("hybrid") + (
            "\n\nYou are speaking through a local voice: keep every reply short and plain (no markdown, lists or "
            "emoji), one to three sentences unless he asks for more.")
        self.warm = True

    async def release(self):
        if self.warm:
            self.unload_task = asyncio.create_task(self._unload_later())

    async def _unload_later(self):
        try:
            await asyncio.sleep(max(config.LOCAL_KEEP_WARM_MIN, 0) * 60)
            if self.a.active != self.key:
                self.stt = self.tts = None             # frees the GPU memory Whisper and Kokoro hold
                self.warm = False
        except asyncio.CancelledError:
            raise

    async def greet(self):
        self.say("Hybrid mode, sir.")

    async def _keepalive(self):
        await asyncio.Event().wait()                    # nothing to keep warm: the model lives in the cloud

    # ---- history in Gemini's format ------------------------------------------------------
    def _assistant_msg(self, text: str, calls: list) -> dict:
        msg = super()._assistant_msg(text, calls)
        if getattr(self, "_parts", None):
            msg["parts"] = self._parts                 # keeps Gemini's thought signatures for the next request
        return msg

    def _contents(self, extra: list | None) -> list[types.Content]:
        out: list[types.Content] = []
        for m in self.history + (extra or []):
            role = m["role"]
            if role == "user":
                out.append(types.Content(role="user", parts=[types.Part(text=m["content"])]))
            elif role == "assistant":
                parts = m.get("parts") or ([types.Part(text=m["content"])] if m["content"] else []) + [
                    types.Part(function_call=types.FunctionCall(name=c["function"]["name"],
                                                                args=c["function"]["arguments"] or {}))
                    for c in m.get("tool_calls", [])]
                if parts:
                    out.append(types.Content(role="model", parts=parts))
            elif role == "tool":
                part = types.Part.from_function_response(name=m.get("tool_name", "tool"),
                                                         response={"result": m["content"]})
                if out and out[-1].role == "user" and out[-1].parts and out[-1].parts[0].function_response:
                    out[-1].parts.append(part)        # several results for one model turn go together
                else:
                    out.append(types.Content(role="user", parts=[part]))
        return out

    def _models(self) -> list[str]:
        now = time.monotonic()
        ready = [m for m in config.HYBRID_MODELS if self.cool.get(m, 0) < now]
        return ready or list(config.HYBRID_MODELS[:1])

    # ---- one model reply ----------------------------------------------------------------------
    async def _generate(self, tools: bool = True, extra: list | None = None) -> tuple[str, list]:
        self._parts = None
        decls = self.picker.pick(self.request_text) if tools else []
        cfg = types.GenerateContentConfig(
            system_instruction=self.system, temperature=0.4, max_output_tokens=600,
            tools=[types.Tool(function_declarations=decls)] if decls else None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            thinking_config=types.ThinkingConfig(thinking_level=config.HYBRID_THINKING))
        contents = self._contents(extra)
        last_err = None
        for model in self._models():
            try:
                text, calls = await self._stream(model, contents, cfg)
                if calls:
                    self.picker.used({c.function.name for c in calls})
                return text, calls
            except asyncio.CancelledError:
                raise
            except Exception as e:
                last_err = e
                low = str(e).lower()
                if any(q in low for q in QUOTA):
                    self.cool[model] = time.monotonic() + COOL_S
                    log.warning("hybrid: %s is out of quota, trying the next model", model)
                    continue
                if "thinking" in low and "level" in low:          # a model without thinking levels
                    cfg.thinking_config = None
                    try:
                        return await self._stream(model, contents, cfg)
                    except Exception as e2:
                        last_err = e2
                log.warning("hybrid: %s failed: %s", model, str(e)[:160])
        if last_err and any(q in str(last_err).lower() for q in QUOTA) and "qwen" in self.a.brains:
            self.a.ui.send(type="notice", text="Gemini's free quota is used up for now; switching to Qwen.")
            self.a.request_switch("qwen", "quota")
            self.say("The cloud quota is used up for now, sir, so Qwen is taking over.")
            return "The cloud quota is used up for now, sir, so Qwen is taking over.", []
        raise RuntimeError(f"no Gemini model answered ({last_err})")

    async def _stream(self, model: str, contents, cfg) -> tuple[str, list]:
        stream = await self.a.client.aio.models.generate_content_stream(model=model, contents=contents, config=cfg)
        text, buf, calls, parts, first = "", "", [], [], True
        async for chunk in stream:
            cand = (chunk.candidates or [None])[0]
            for p in (cand.content.parts if cand and cand.content and cand.content.parts else []):
                parts.append(p)
                if p.function_call:
                    calls.append(SimpleNamespace(function=SimpleNamespace(
                        name=p.function_call.name, arguments=dict(p.function_call.args or {}))))
                elif p.text and not p.thought:
                    self.a.awaiting = False
                    text += p.text
                    buf += p.text
                    *done, buf = SENTENCE_END.split(buf)
                    for s in done:
                        if s.strip():
                            self.a.caption("clove", s.strip() + " ", new=first)
                            first = False
                            self.say(s)
        if buf.strip():
            self.a.caption("clove", buf.strip(), new=first)
            self.say(buf)
        self._parts = self._merge(parts)
        return text.strip(), calls

    @staticmethod
    def _merge(parts: list) -> list:
        """Streaming splits one text into many parts; join neighbouring plain text so the history stays small."""
        out = []
        for p in parts:
            if (out and p.text is not None and not p.function_call and not p.thought and not p.thought_signature
                    and out[-1].text is not None and not out[-1].function_call and not out[-1].thought):
                out[-1] = types.Part(text=out[-1].text + p.text, thought_signature=out[-1].thought_signature)
            else:
                out.append(p)
        return out
