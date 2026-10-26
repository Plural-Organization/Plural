import { Box, Text } from "ink";
import type { FeedItem, Tone } from "../feed";
import { previewLines } from "../lib/wrap";
import { colorFor, theme } from "../theme";
import { DiffBlock } from "./Code";
import { Markdown } from "./Markdown";

const TONES: Record<Tone, { color: string; mark: string }> = {
  dim: { color: theme.dim, mark: "·" },
  ok: { color: theme.ok, mark: "✓" },
  warn: { color: theme.warn, mark: "!" },
  danger: { color: theme.danger, mark: "✗" },
  accent: { color: theme.accent, mark: "◆" },
};

const OUTPUT_LINES = 6;

export function Banner({ item }: { item: Extract<FeedItem, { kind: "banner" }> }) {
  return (
    <Box flexDirection="column" borderStyle="round" borderColor={theme.accent} paddingX={2} marginBottom={1}>
      <Text>
        <Text color={theme.accent} bold>
          ◆ plural
        </Text>
        <Text color={theme.dim}>  v{item.version}</Text>
      </Text>
      <Text color={theme.dim}>room {item.room}</Text>
      {item.guestLink ? (
        <Box flexDirection="column" marginTop={1}>
          <Text color={theme.dim}>invite a teammate with</Text>
          <Text color={theme.info}>plural join "{item.guestLink}"</Text>
        </Box>
      ) : null}
      <Box marginTop={1}>
        <Text color={theme.dim}>/help for commands · esc interrupts · ctrl+c twice quits</Text>
      </Box>
    </Box>
  );
}

export function UserCard({ item }: { item: Extract<FeedItem, { kind: "user" }> }) {
  const color = colorFor(item.participantId);
  return (
    <Box borderStyle="bold" borderColor={color} borderTop={false} borderBottom={false} borderRight={false} paddingLeft={1} marginBottom={1}>
      <Box flexDirection="column" flexShrink={1}>
        <Text>
          <Text color={color} bold>
            {item.name}
          </Text>
          <Text color={theme.dim}>
            {"  "}
            {item.role}
            {item.viaProposal ? " · approved by host" : ""}
          </Text>
        </Text>
        <Text>{item.text}</Text>
      </Box>
    </Box>
  );
}

export function AssistantCard({ item, width }: { item: Extract<FeedItem, { kind: "assistant" }>; width: number }) {
  return (
    <Box flexDirection="column" marginBottom={1}>
      {item.first ? (
        <Text color={theme.accent} bold>
          ● plural
        </Text>
      ) : null}
      <Box paddingLeft={2}>
        <Markdown text={item.text} width={width - 2} />
      </Box>
    </Box>
  );
}

export function ToolCard({ item }: { item: Extract<FeedItem, { kind: "tool" }> }) {
  const ok = item.ok === true;
  const color = ok ? theme.ok : theme.danger;
  const output = previewLines(ok ? item.output.replace(/\n?\[exit 0\]\s*$/, "") : item.output, OUTPUT_LINES);
  return (
    <Box flexDirection="column" marginBottom={1}>
      <Text>
        <Text color={color}>{ok ? "✓" : "✗"} </Text>
        <Text bold>{item.call.name}</Text>
        {item.call.subject ? <Text color={theme.dim}> {item.call.subject}</Text> : null}
      </Text>
      {item.diff ? (
        <Box paddingLeft={2}>
          <DiffBlock diff={item.diff} />
        </Box>
      ) : output.lines.length > 0 && output.lines.some((line) => line.trim() !== "") ? (
        <Box flexDirection="column" paddingLeft={2}>
          {output.lines.map((line, index) => (
            <Text key={index} color={ok ? theme.dim : theme.danger} wrap="truncate-end">
              {index === 0 ? "⎿ " : "  "}
              {line}
            </Text>
          ))}
          {output.more > 0 ? <Text color={theme.dim}>  … +{output.more} lines</Text> : null}
        </Box>
      ) : null}
    </Box>
  );
}

export function NoticeCard({ item }: { item: Extract<FeedItem, { kind: "notice" }> }) {
  const tone = TONES[item.tone];
  return (
    <Box marginBottom={item.text.includes("\n") ? 1 : 0}>
      <Text color={tone.color}>{tone.mark} </Text>
      <Text color={item.tone === "dim" ? theme.dim : undefined}>{item.text}</Text>
    </Box>
  );
}

export function FeedItemView({ item, width }: { item: FeedItem; width: number }) {
  switch (item.kind) {
    case "banner":
      return <Banner item={item} />;
    case "user":
      return <UserCard item={item} />;
    case "assistant":
      return <AssistantCard item={item} width={width} />;
    case "tool":
      return <ToolCard item={item} />;
    case "notice":
      return <NoticeCard item={item} />;
  }
}
