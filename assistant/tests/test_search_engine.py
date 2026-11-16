"""'Search the web' goes to Bing unless he chose another engine (SEARCH_ENGINE in .env)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import desktop  # noqa: E402

fails = 0


def check(name, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + name)
    fails += not ok


config.SEARCH_ENGINE = "bing"
check("Bing is the default", desktop.search_url("best pizza near me") == "https://www.bing.com/search?q=best+pizza+near+me")
check("the query is made safe for a link", desktop.search_url("a&b=c d?").endswith("a%26b%3Dc+d%3F"))
check("Google when he picks it", desktop.search_url("x", "google").startswith("https://www.google.com/search?q="))
check("DuckDuckGo and Brave too", desktop.search_url("x", "duckduckgo").startswith("https://duckduckgo.com/") and
      desktop.search_url("x", "brave").startswith("https://search.brave.com/"))
config.SEARCH_ENGINE = "GOOGLE"
check("the setting is not case sensitive", desktop.search_url("x").startswith("https://www.google.com/"))
config.SEARCH_ENGINE = "nonsense"
check("an unknown engine falls back to Bing", desktop.search_url("x").startswith("https://www.bing.com/"))
config.SEARCH_ENGINE = ""
check("an empty setting is Bing", desktop.search_url("x").startswith("https://www.bing.com/"))
opened = []
config.SEARCH_ENGINE = "bing"
desktop._chrome_open = lambda url, profile, new=False: opened.append(url)
out = desktop.web_search("weather in Mumbai")
check("the search tool opens Bing's results", opened == ["https://www.bing.com/search?q=weather+in+Mumbai"] and "bing.com" in out)
print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
