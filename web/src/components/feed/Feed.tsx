import { Alert, Button, Chip } from "@heroui/react";
import { PencilSimple } from "@phosphor-icons/react";
import { useState, type ReactNode } from "react";
import type { Mentionable } from "@plural/client";
import { MentionPeople } from "./Mentions";
import type { FeedItem } from "@plural/client";
import type { Activity as Current } from "../../lib/activity";
import { cx } from "../../lib/cx";
import { docTitle, isDocument, lineCount, toolDoc } from "../../lib/canvas";
import { segments } from "../../lib/quote";
import { LogoMark } from "../LogoMark";
import { PersonAvatar } from "../PersonAvatar";
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
    const last = out.at(-1);
    // The same notice twice in a row (a reconnect repeats them) says nothing new.
    if (item.kind === "notice" && last?.kind === "notice" && last.text === item.text) {
      continue;
    }
    if (item.kind !== "tool") {
      out.push(item);
      continue;
    }
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
  people?: Mentionable[];
  meId?: string | null;
  activity?: Current | null;
  // Given, long code and documents show as cards that open in the canvas.
  onOpenDoc?: (id: string) => void;
  onOpenBoard?: () => void;
}

export function Feed({ items, people = [], meId = null, activity = null, onOpenDoc, onOpenBoard }: FeedProps) {
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
    <MentionPeople.Provider value={people}><div className={styles.feed}>
      {blocks(items).map((block) =>
        block.kind === "steps" ? (
          <div key={block.id} className={styles.steps}>
            {block.tools.map((tool) => (
              <ToolLine
                key={tool.id}
                item={tool}
                expanded={opened.has(tool.id)}
                onToggle={() => toggle(tool.id)}
                onOpen={onOpenDoc && toolDoc(tool) !== null ? () => onOpenDoc(tool.id) : undefined}
              />
            ))}
          </div>
        ) : (
          <Entry key={block.id} item={block} meId={meId} onOpenDoc={onOpenDoc} onOpenBoard={onOpenBoard} />
        ),
      )}
      <Activity activity={activity} />
    </div>
  </MentionPeople.Provider>);
}

// A message's own text, with the parts it quotes set apart.
function Text({ text, anchor }: { text: string; anchor: string }) {
  return (
    <div className={styles.text} data-anchor={anchor}>
      {segments(text).map((segment, index) =>
        segment.quote ? (
          <blockquote key={index} className={styles.quote}>
            {segment.text}
          </blockquote>
        ) : (
          <span key={index}>{segment.text}</span>
        ),
      )}
    </div>
  );
}

// The agent's side of the conversation: its mark, then full-width text.
function AgentEntry({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <article className={styles.agent}>
      <span className={styles.agentMark} aria-hidden="true"><LogoMark size={18} /></span>
      <div className={styles.agentBody}>
        <div className={styles.agentName}>{label}</div>
        {children}
      </div>
    </article>
  );
}

interface EntryProps {
  item: Exclude<FeedItem, { kind: "tool" }>;
  meId: string | null;
  onOpenDoc?: ((id: string) => void) | undefined;
  onOpenBoard?: (() => void) | undefined;
}

function Entry({ item, meId, onOpenDoc, onOpenBoard }: EntryProps) {
  switch (item.kind) {
    case "banner":
      return null;
    case "user": {
      const mine = item.participantId === meId;
      return (
        <article className={cx(styles.row, mine && styles.mine)}>
          {mine ? null : <PersonAvatar seed={item.name} />}
          <div className={styles.column}>
          {mine ? null : <div className={styles.who}>{item.name}</div>}
          <div className={styles.bubble}>
            <Text text={item.text} anchor={item.id} />
            {item.full ? (
              <details className={styles.meta}>
                <summary>what /{item.via ?? "plugin"} sent the agent</summary>
                <pre className={styles.full}>{item.full}</pre>
              </details>
            ) : null}
            {item.files && item.files.length > 0 ? (
              <ul className={styles.files}>
                {item.files.map((file, index) => (
                  <li key={index}>📎 {file}</li>
                ))}
              </ul>
            ) : null}
          </div>
          {item.viaProposal || item.role === "viewer" || item.via ? (
            <div className={styles.meta}>{[item.via ? `via /${item.via}` : null, item.viaProposal ? "approved by the host" : item.role === "viewer" ? item.role : null].filter(Boolean).join(" · ")}</div>
          ) : null}
          </div>
        </article>
      );
    }
    case "chat": {
      const direct = item.to !== null;
      const head = direct ? (item.mine ? `to ${item.toName ?? "someone"}` : `${item.name} to you`) : item.mine ? "to the team" : `${item.name} to the team`;
      return (
        <article className={cx(styles.row, item.mine && styles.mine)}>
          {item.mine ? null : <PersonAvatar seed={item.name} />}
          <div className={styles.column}>
            <div className={styles.who}>{head}</div>
            <div className={cx(styles.bubble, styles.chat, direct && styles.private, item.mentioned && styles.mentioned)}>
              <Text text={item.text} anchor={item.id} />
            </div>
            <div className={styles.meta}>
              {direct ? "private, the agent does not see it" : "the agent does not see it"}
              {item.mentioned && !direct ? " · mentions you" : ""}
            </div>
          </div>
        </article>
      );
    }
    case "assistant":
      return (
        <AgentEntry label="Agent">
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
            <div data-anchor={item.id}>
              <Markdown text={item.text} streaming={item.streaming} onOpenCode={onOpenDoc && ((index) => onOpenDoc(`${item.id}:${index}`))} />
            </div>
          )}
        </AgentEntry>
      );
    case "briefing":
      return (
        <AgentEntry label={<>Briefing from {item.from}{item.update ? <Chip size="sm" variant="soft" className="ml-2"><Chip.Label>Update</Chip.Label></Chip> : null}</>}>
          <div data-anchor={item.id}>
            <Text text={item.text} anchor={item.id} />
          </div>
        </AgentEntry>
      );
    case "shown":
      return (
        <AgentEntry label={<>{item.title}<span className="ml-2 font-normal text-muted">/{item.command}, only you see this</span></>}>
          <div data-anchor={item.id}>
            <Text text={item.text} anchor={item.id} />
          </div>
        </AgentEntry>
      );
    case "notice":
      if (item.action === "board") {
        return (
          <div className={styles.event}>
            <span className={styles.eventIcon} aria-hidden="true">
              <PencilSimple size={16} />
            </span>
            <span className={styles.eventText}>{item.text}</span>
            {onOpenBoard ? (
              <Button size="sm" onPress={onOpenBoard}>Open board</Button>
            ) : null}
          </div>
        );
      }
      if (item.code && item.text.startsWith(item.code)) {
        // A long command stays on one line, cut short; the whole of it is in the title.
        return (
          <div className={cx(styles.notice, styles.decision, styles[item.tone])}>
            <code title={item.code}>{item.code}</code>
            <span>{item.text.slice(item.code.length).replace(/^:\s*/, "")}</span>
          </div>
        );
      }
      if (item.tone === "warn" || item.tone === "danger") {
        return (
          <Alert status={item.tone === "warn" ? "warning" : "danger"} className={styles.alert}>
            <Alert.Indicator />
            <Alert.Content>
              <Alert.Description className="whitespace-pre-wrap">{item.text}</Alert.Description>
            </Alert.Content>
          </Alert>
        );
      }
      return <div className={cx(styles.notice, styles[item.tone])}>{item.text}</div>;
  }
}
