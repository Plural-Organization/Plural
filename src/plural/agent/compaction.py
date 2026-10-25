import re
from typing import Final

SUMMARY_PROMPT: Final = (
    "Summarize the transcript inside <summary></summary> tags. Include relevant information in "
    "the summary such that this conversation will be continued by a new context window without "
    "needing to redo work or be reprovided with relevant constraints or context. Be sure to "
    "preserve: (1) any difficulties or problems that came up, and how they were handled or "
    "resolved; (2) any possibilities, options, or approaches that were raised, tried, or set "
    "aside, and why; (3) anything that was asked for, decided, agreed, ruled out, or established "
    "as a preference, constraint, or boundary - stated exactly; (4) exactly where things stand "
    "now - what has been covered, settled, or completed so far, including files created or "
    "changed; (5) anything still open, unresolved, promised, or expected to happen next; (6) "
    "specific details that would be hard to reconstruct - names, paths, numbers, commands, exact "
    "wording, links or references - kept exactly. Be complete on these even at the cost of "
    "length; keep everything else concise. Weight the two voices differently: keep what the "
    "users said, asked for, shared, or established carefully and close to their own words, "
    "including who said it; your own explanations and reasoning can be condensed much further, "
    "to what they concluded or produced. Do not call any tools while writing this summary; "
    "respond with text only."
)

_TAGGED = re.compile(r"<summary>(.*?)</summary>", re.DOTALL)


def extract_summary(text: str) -> str:
    tagged = _TAGGED.search(text)
    return (tagged.group(1) if tagged else text).strip()
