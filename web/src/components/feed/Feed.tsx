import { useState, type CSSProperties } from "react";
import type { FeedItem } from "@plural/client";
import { colorFor } from "../../lib/colors";
import { cx } from "../../lib/cx";
import { Markdown } from "./Markdown";
import { ToolLine } from "./ToolLine";
import styles from "./Feed.module.css";

export function Feed({ items }: { items: FeedItem[] }) {
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
      {items.map((item) =>
        item.kind === "tool" ? (
          <ToolLine key={item.id} item={item} expanded={opened.has(item.id)} onToggle={() => toggle(item.id)} />
        ) : (
          <Entry key={item.id} item={item} />
        ),
      )}
    </div>
  );
}

function Entry({ item }: { item: Exclude<FeedItem, { kind: "tool" }> }) {
  switch (item.kind) {
    case "banner":
      return null;
    case "user":
      return (
        <article className={cx(styles.msg, styles.user)} style={{ "--who": colorFor(item.participantId) } as CSSProperties}>
          <header>
            <span className={styles.who}>{item.name}</span>
            <span className="muted">
              {item.role} · to agent
              {item.viaProposal ? " · approved by the host" : ""}
            </span>
          </header>
          <div className={styles.text}>{item.text}</div>
        </article>
      );
    case "chat": {
      const direct = item.to !== null;
      const head = direct ? (item.mine ? `you → ${item.toName ?? "someone"}` : `${item.name} → you`) : item.mine ? "you · to the room" : `${item.name} · to the room`;
      return (
        <article
          className={cx(styles.msg, styles.chat, direct && styles.private, item.mentioned && styles.mentioned)}
          style={{ "--who": colorFor(item.authorId) } as CSSProperties}
        >
          <header>
            <span className={styles.who}>✉ {head}</span>
            <span className="muted">
              {direct ? "private, the agent does not see it" : "the agent does not see it"}
              {item.mentioned && !direct ? " · mentions you" : ""}
            </span>
          </header>
          <div className={styles.text}>{item.text}</div>
        </article>
      );
    }
    case "assistant":
      return (
        <article className={styles.msg}>
          <header>
            <span className={styles.who}>agent</span>
            {item.streaming ? <span className="muted">writing…</span> : null}
          </header>
          {item.text ? <Markdown text={item.text} streaming={item.streaming} /> : <div className="muted">…</div>}
        </article>
      );
    case "notice":
      return <div className={cx(styles.notice, styles[item.tone])}>{item.text}</div>;
  }
}
