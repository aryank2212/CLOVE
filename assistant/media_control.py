"""Media control: play on Spotify/YouTube."""
import subprocess
import logging

log = logging.getLogger("clove.media_control")

def play_spotify(query: str) -> str:
    try:
        subprocess.Popen(["spotify", "--uri", f"spotify:search:{query}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"opening Spotify for {query}"
    except FileNotFoundError:
        return "Spotify not installed"

def play_youtube(query: str) -> str:
    import urllib.parse
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)
    subprocess.Popen(["google-chrome", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"opened YouTube search for {query}"
