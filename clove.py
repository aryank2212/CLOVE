"""Clove = the shared assistant + its three brains."""
from base import Assistant
from brain_gemini import GeminiBrain
from brain_hybrid import HybridBrain
from brain_local import LocalBrain


class Clove(Assistant):
    def __init__(self, ui, speaker=None):
        super().__init__(ui, speaker)
        self.brains = {"gemini": GeminiBrain(self), "hybrid": HybridBrain(self), "qwen": LocalBrain(self)}
