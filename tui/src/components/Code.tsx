import { Box, Text } from "ink";
import { highlightLines, type Span } from "../lib/highlight";
import { theme } from "../theme";

function Spans({ spans }: { spans: Span[] }) {
  return (
    <>
      {spans.map((span, index) => (
        <Text key={index} color={span.color} bold={span.bold} italic={span.italic}>
          {span.text}
        </Text>
      ))}
    </>
  );
}

export function CodeBlock({ code, language }: { code: string; language?: string | undefined }) {
  const lines = highlightLines(code.replace(/\n$/, ""), language);
  return (
    <Box flexDirection="column" borderStyle="round" borderColor={theme.dim} paddingX={1}>
      {language ? <Text color={theme.dim}>{language}</Text> : null}
      {lines.map((spans, index) => (
        <Text key={index} wrap="wrap">
          {spans.length === 0 ? " " : <Spans spans={spans} />}
        </Text>
      ))}
    </Box>
  );
}

export function DiffBlock({ diff, limit = 24 }: { diff: string; limit?: number }) {
  const lines = diff.replace(/\n$/, "").split("\n");
  const shown = lines.slice(0, limit);
  return (
    <Box flexDirection="column">
      {shown.map((line, index) => {
        if (line.startsWith("+") && !line.startsWith("+++")) {
          return (
            <Text key={index} color={theme.ok} backgroundColor={theme.addBg}>
              {line}
            </Text>
          );
        }
        if (line.startsWith("-") && !line.startsWith("---")) {
          return (
            <Text key={index} color={theme.danger} backgroundColor={theme.removeBg}>
              {line}
            </Text>
          );
        }
        if (line.startsWith("@@")) {
          return (
            <Text key={index} color={theme.info}>
              {line}
            </Text>
          );
        }
        return (
          <Text key={index} color={theme.dim}>
            {line}
          </Text>
        );
      })}
      {lines.length > limit ? <Text color={theme.dim}>… +{lines.length - limit} more lines</Text> : null}
    </Box>
  );
}
