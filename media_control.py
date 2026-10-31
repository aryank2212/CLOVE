"""Media control: play on Spotify/YouTube."""
import subprocess
import logging

log = logging.getLogger("clove.media_control")

def play_spotify(query: str) -> str:
    try:
        import config
        if config.IS_MAC:
            argv = ["open", f"spotify:search:{query}"]
        elif config.IS_WINDOWS:
            argv = ["start", "spotify:search:" + query]
        else:
            argv = ["spotify", "--uri", f"spotify:search:{query}"]
        subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=config.IS_WINDOWS)
        return f"opening Spotify for {query}"
    except FileNotFoundError:
        return "Spotify not installed"

def play_youtube(query: str) -> str:
    import urllib.parse
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)
    from desktop import chrome_argv
    subprocess.Popen(chrome_argv(url), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"opened YouTube search for {query}"
