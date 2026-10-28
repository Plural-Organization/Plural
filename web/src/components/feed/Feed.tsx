import { useState, type CSSProperties } from "react";
import type { FeedItem } from "@plural/client";
import type { Activity as Current } from "../../lib/activity";
import { colorFor } from "../../lib/colors";
import { cx } from "../../lib/cx";
import { docTitle, isDocument, lineCount, writtenFile } from "../../lib/canvas";
import { Activity } from "./Activity";
import { DocCard } from "./DocCard";
import { Markdown } from "./Markdown";
import { ToolLine } from "./ToolLine";
import styles from "./Feed.module.css";

type ToolItem = Extract<FeedItem, { kind: "tool" }>;
type Block = { kind: "steps"; id: string; tools: ToolItem[] } | Exclude<FeedItem, { kind: "tool" }>;

// Tool calls in a row read as one block of the agent's work, the way a chat shows steps.
function blocks(items: FeedItem[]): Block[] {
  const out: Block[] = [];
  for (const item of items) {
    if (item.kind !== "tool") {
      out.push(item);
      continue;
    }
    const last = out.at(-1);
    if (last?.kind === "steps") {
      last.tools.push(item);
    } else {
      out.push({ kind: "steps", id: `s_${item.id}`, tools: [item] });
    }
  }
  return out;
}

interface FeedProps {
  items: FeedItem[];
  meId?: string | null;
  activity?: Current | null;
  // Given, long code and documents show as cards that open in the canvas.
  onOpenDoc?: (id: string) => void;
}

export function Feed({ items, meId = null, activity = null, onOpenDoc }: FeedProps) {
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set());
  const toggle = (id: string) =>
    setOpened((current) => {
      const next = new Set(current);
      if (!next.delete(id)) {
        next.add(id);
      }
      return next;
    });

  return (
    <div className={styles.feed}>
      {blocks(items).map((block) =>
        block.kind === "steps" ? (
          <div key={block.id} className={styles.steps}>
            {block.tools.map((tool) => (
              <ToolLine
                key={tool.id}
                item={tool}
                expanded={opened.has(tool.id)}
                onToggle={() => toggle(tool.id)}
                onOpen={onOpenDoc && writtenFile(tool) !== null ? () => onOpenDoc(tool.id) : undefined}
              />
            ))}
          </div>
        ) : (
          <Entry key={block.id} item={block} meId={meId} onOpenDoc={onOpenDoc} />
        ),
      )}
      <Activity activity={activity} />
    </div>
  );
}

interface EntryProps {
  item: Exclude<FeedItem, { kind: "tool" }>;
  meId: string | null;
  onOpenDoc?: ((id: string) => void) | undefined;
}

function Entry({ item, meId, onOpenDoc }: EntryProps) {
  switch (item.kind) {
    case "banner":
      return null;
    case "user": {
      const mine = item.participantId === meId;
      return (
        <article className={cx(styles.row, mine && styles.mine)} style={{ "--who": colorFor(item.participantId) } as CSSProperties}>
          <div className={styles.bubble}>
            {mine ? null : <div className={styles.who}>{item.name}</div>}
            <div className={styles.text}>{item.text}</div>
          </div>
          {item.viaProposal || item.role === "viewer" ? (
            <div className={styles.meta}>{item.viaProposal ? "approved by the host" : item.role}</div>
          ) : null}
        </article>
      );
    }
    case "chat": {
      const direct = item.to !== null;
      const head = direct ? (item.mine ? `to ${item.toName ?? "someone"}` : `${item.name} to you`) : item.mine ? "to the team" : `${item.name} to the team`;
      return (
        <article className={cx(styles.row, item.mine && styles.mine)} style={{ "--who": colorFor(item.authorId) } as CSSProperties}>
          <div className={cx(styles.bubble, styles.chat, direct && styles.private, item.mentioned && styles.mentioned)}>
            <div className={styles.who}>{head}</div>
            <div className={styles.text}>{item.text}</div>
          </div>
          <div className={styles.meta}>
            {direct ? "private, the agent does not see it" : "the agent does not see it"}
            {item.mentioned && !direct ? " · mentions you" : ""}
          </div>
        </article>
      );
    }
    case "assistant":
      return (
        <article className={styles.agent}>
          <div className={styles.agentName}>agent</div>
          {item.text === "" ? (
            <div className="muted">…</div>
          ) : onOpenDoc && isDocument(item.text) ? (
            <DocCard
              title={docTitle(item.text)}
              meta={item.streaming ? "writing…" : `${lineCount(item.text)} lines`}
              preview={item.text}
              onOpen={() => onOpenDoc(item.id)}
            />
          ) : (
            <Markdown text={item.text} streaming={item.streaming} onOpenCode={onOpenDoc && ((index) => onOpenDoc(`${item.id}:${index}`))} />
          )}
        </article>
      );
    case "notice":
      return <div className={cx(styles.notice, styles[item.tone])}>{item.text}</div>;
  }
}
