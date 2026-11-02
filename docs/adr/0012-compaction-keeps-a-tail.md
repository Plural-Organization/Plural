# ADR 0012: compaction keeps the newest turns

Status: accepted. Supersedes ADR 0003.

## Context

ADR 0003 replaced the whole conversation with one summary and the run's prompt. A compaction in the
middle of a run dropped everything the run had done so far: the agent read its files again, the context
grew back, and the next compaction came sooner. It also summarized through the same request shape as a
normal turn, which kept the prompt cache but sent every tool result whole, and wrote each summary from
scratch, so detail thinned with every compaction.

ADR 0003 rejected a kept tail because its turns carry thinking blocks bound to the history before them.
Anthropic's guidance for this case is to strip the thinking blocks from the kept turns and keep their text
and tool calls; blocks may be removed from the front of the history, not from its middle.

pi compacts this way: it keeps about 20k recent tokens, summarizes the rest in a separate request with
long tool results cut, updates the previous summary instead of rewriting it, and lists the files read and
changed.

## Decision

- Compaction keeps the newest `PLURAL_COMPACT_KEEP` tokens (20000, at most half the threshold) as they
  are. The kept part starts at a prompt or at a turn that calls tools, never at a tool result, so a result
  never loses its call. The conversation becomes the summary, the run's prompt when the summary covered it,
  then the kept turns.
- Kept assistant turns lose their provider-native content (thinking blocks and signatures); their text
  and tool calls stay.
- The summary is asked for in its own request: a short system prompt, no tools, and the older messages as
  text, each tool result cut to 2000 characters. A previous summary is passed as `<previous_summary>` and
  updated. The files the agent read and changed are listed after the summary and carried into the next one.
  A summary cut off at the output limit is not used.
- `context.compacted` names the first kept message (`kept_from`: `prompt:<id>` or `call:<tool call id>`),
  so a restarted host rebuilds the same conversation from the event log.
- Triggers, provenance and the untrusted-notes framing of the summary are as in ADR 0003, with the
  threshold now the model's window less `PLURAL_COMPACT_RESERVE`.

## Consequences

- A compaction mid-run no longer makes the agent redo its latest work.
- The summary request does not reuse the conversation's prompt cache. It is much smaller than the
  conversation, and the fast model that usually writes it has no share in the main model's cache.
- The kept turns' thinking is gone: the model continues from their text and tool calls. Anthropic expects
  this to cost little when done once, at a compaction.
- Snipping turns from the middle of the history remains off limits: it would invalidate every later
  thinking block.
