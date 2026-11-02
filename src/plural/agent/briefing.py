from typing import Final

from plural.agent.prompts import prompt, tag

BRIEFING_TAG: Final = "briefing"
MAX_BRIEFING_WORDS: Final = 450


def briefing_prompt(focus: str | None, previous: str | None) -> str:
    parts = [prompt("briefing").format(max_words=MAX_BRIEFING_WORDS)]
    if previous:
        parts.append(f"{prompt('briefing_update')}\n{tag('earlier', previous)}")
    if focus:
        parts.append(f"{prompt('briefing_question')}\n{tag('question', focus)}")
    return "\n\n".join(parts)
