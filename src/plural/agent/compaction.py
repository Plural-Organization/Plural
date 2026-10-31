import re
from typing import Final

from plural.agent.prompts import prompt

SUMMARY_PROMPT: Final = prompt("compaction")


def extract_tagged(text: str, tag: str) -> str:
    tagged = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    return (tagged.group(1) if tagged else text).strip()


def extract_summary(text: str) -> str:
    return extract_tagged(text, "summary")
