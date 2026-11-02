The messages inside <conversation> are the older part of the session. Write a checkpoint of them inside <summary></summary> tags. The newest messages stay as they are after the checkpoint, so they need no repeating.

Use this format:

## Goal
[What the people in the session are trying to get done; several items if the session moved between tasks.]

## People
- [Who asked for what, decided or ruled out what, close to their own words.]

## Constraints and preferences
- [Requirements, boundaries and preferences stated so far, or "(none)".]

## Progress
### Done
- [x] [Work completed, files created or changed.]
### In progress
- [ ] [Work under way.]
### Blocked
- [What is in the way, or "(none)".]

## Key decisions
- **[Decision]**: [Why.]

## Next steps
1. [What should happen next, in order.]

## Critical context
- [Details needed to continue: data, examples, references, or "(none)".]

<rules>
- Keep what people said, asked for and established close to their own words, with who said it. The agent's own explanations can shrink to what they concluded or produced.
- Keep exact file paths, names, commands, numbers, error messages and links.
- Long tool results are shortened in this request only; the agent read them whole, and its own messages say what it concluded. Never write that a result was cut or that the agent saw only part of it.
- Keep each section short. Respond with text only and call no tools.
</rules>
