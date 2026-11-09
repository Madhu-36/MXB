"""
Example plugin: play something on YouTube.

  "MXB, play lofi hip hop on youtube"
Opens the YouTube search results, waits for the page, then clicks the first video
(using the accessibility tree, with a keyboard fallback).
"""
import time
import urllib.parse
from engine.skills import skill


@skill(name="play_youtube", patterns=[r"^play\s+(?P<target>.+?)\s+on\s+you\s?tube$"],
       description="Search YouTube and start the first matching video", target="what to play", uses_input=True)
def play_youtube(target, ctx):
    if not target:
        return "What should I play?"
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(target)
    ex = ctx.executor
    ex.execute_action("open_url", url)
    time.sleep(4.0)  # let the results page load
    result = ex.execute_action("click_element", target)
    if "could not" in result.lower():
        # Fallback: Tab into the results list and open the first one.
        for _ in range(4):
            ex.execute_action("press_key", "tab")
        ex.execute_action("press_key", "enter")
    return f"Playing {target} on YouTube."
