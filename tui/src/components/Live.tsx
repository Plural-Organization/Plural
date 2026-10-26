import { Box, Text } from "ink";
import type { Feed } from "../feed";
import { tailLines } from "../lib/blocks";
import { theme } from "../theme";
import { Markdown } from "./Markdown";
import { Spinner, useElapsed } from "./Spinner";

interface LiveProps {
  feed: Feed;
  status: string;
  running: boolean;
  columns: number;
  maxLines: number;
  interruptible: boolean;
}

export function Live({ feed, status, running, columns, maxLines, interruptible }: LiveProps) {
  const elapsed = useElapsed(running);
  const pending = feed.pending;
  const tail = pending ? pending.text.slice(pending.committed) : "";
  const view = tailLines(tail, columns - 2, maxLines);
  return (
    <Box flexDirection="column">
      {pending && view.text.trim() !== "" ? (
        <Box flexDirection="column" marginBottom={1} maxHeight={maxLines} overflow="hidden" justifyContent="flex-end">
          {pending.first ? (
            <Text color={theme.accent} bold>
              ● plural
            </Text>
          ) : null}
          <Box paddingLeft={2} flexDirection="column">
            {view.hidden ? <Text color={theme.dim}>…</Text> : null}
            <Markdown text={view.text} width={columns - 2} />
          </Box>
        </Box>
      ) : null}
      {feed.tools.map((tool) => (
        <Box key={tool.call.id}>
          <Spinner color={theme.info} />
          <Text>
            {" "}
            <Text bold>{tool.call.name}</Text>
            {tool.call.subject ? <Text color={theme.dim}> {tool.call.subject}</Text> : null}
          </Text>
        </Box>
      ))}
      {running ? (
        <Box>
          <Spinner />
          <Text color={theme.dim}>
            {" "}
            {status.replace(/^…\s*/, "") || "working"} · {elapsed}s{interruptible ? " · esc to interrupt" : ""}
          </Text>
        </Box>
      ) : null}
    </Box>
  );
}
