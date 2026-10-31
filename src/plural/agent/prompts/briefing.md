A teammate's AI agent is about to work in the same project and cannot see this conversation. Write it a briefing of this session inside <briefing></briefing> tags.

<sections>
1. Goal: what the people in this session are trying to achieve, in one or two sentences.
2. Done: what was done, with the decisions made and the reason for each, and the approaches that were tried and dropped and why.
3. State: what works now, what does not, failing tests or errors quoted exactly.
4. Open: what is unfinished, promised or planned next.
5. Gotchas: constraints and preferences the users stated, exact names, paths, commands and numbers that are hard to reconstruct.
</sections>

<rules>
- Be concrete and use the exact identifiers. Say so where you are unsure and never invent anything that was not said or shown.
- Do not include secrets, tokens, passwords, keys or personal data, and do not paste file contents: name the file and say what changed.
- Stay under {max_words} words.
- Do not call any tools; respond with text only.
</rules>
