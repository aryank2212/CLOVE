"""Scheduled digests: morning + night + weekly, triggered by cron."""
import asyncio
import logging
from morning_briefing import gather as morning_gather

log = logging.getLogger("clove.scheduled_digests")

async def morning(speak_fn):
    b = await morning_gather()
    await speak_fn(b)
    return b

async def night(speak_fn, ask_fn):
    await speak_fn("Nightly check-in: what did you do today?")
    # caller collects response and logs
