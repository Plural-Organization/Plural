import { Button, Card, Chip, Disclosure, ScrollShadow, Tabs, Tooltip } from "@heroui/react";
import { Check, Copy } from "@phosphor-icons/react";
import { useState, type CSSProperties } from "react";
import { cachedShare, compactDuration, compactTokens, spanTitle, totalTokens, type Span, type TraceNode } from "@plural/client";
import { copyText } from "../lib/clipboard";
import { copyable, spanInput, spanOutput, type ChatPart, type Content } from "../lib/traceContent";
import styles from "./TraceView.module.css";

export const STATUS: Record<Span["status"], { word: string; color: "success" | "warning" | "danger" | "default" }> = {
  ok: { word: "finished", color: "success" },
  running: { word: "running", color: "warning" },
  error: { word: "failed", color: "danger" },
  denied: { word: "denied", color: "danger" },
  cancelled: { word: "stopped", color: "default" },
};

export const kindColor = (kind: string): CSSProperties => ({ "--kind": `var(--kind-${kind})` }) as CSSProperties;

export function StatusChip({ status }: { status: Span["status"] }) {
  return (
    <Chip size="sm" variant="soft" color={STATUS[status].color}>
      <Chip.Label>{STATUS[status].word}</Chip.Label>
    </Chip>
  );
}

const ROLE_WORDS: Record<string, string> = { user: "user", assistant: "assistant", tool: "tool result" };

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Tooltip delay={300}>
      <Button
        isIconOnly
        size="sm"
        variant="ghost"
        aria-label={label}
        isDisabled={text === ""}
        onPress={() =>
          void copyText(text).then((ok) => {
            setCopied(ok);
            setTimeout(() => setCopied(false), 1400);
          })
        }
      >
        {copied ? <Check size={15} /> : <Copy size={15} />}
      </Button>
      <Tooltip.Content>{copied ? "Copied" : label}</Tooltip.Content>
    </Tooltip>
  );
}

function Message({ part }: { part: ChatPart }) {
  return (
    <Card className={styles.message} data-role={part.role} data-error={part.error || undefined}>
      <div className={styles.messageHead}>
        <span className={styles.role}>{ROLE_WORDS[part.role] ?? part.role}</span>
        {part.images > 0 ? <span className={styles.hint}>{part.images} image{part.images === 1 ? "" : "s"} not kept</span> : null}
        {part.error ? (
          <Chip size="sm" variant="soft" color="danger">
            <Chip.Label>error</Chip.Label>
          </Chip>
        ) : null}
      </div>
      {part.content !== "" ? <pre className={styles.pre}>{part.content}</pre> : null}
      {part.calls.map((call, index) => (
        <div key={index} className={styles.call}>
          <span className={styles.callName}>→ {call.name}</span>
          <pre className={styles.pre}>{call.args}</pre>
        </div>
      ))}
    </Card>
  );
}

function ContentView({ content }: { content: Content }) {
  switch (content.kind) {
    case "empty":
      return <div className={styles.emptySmall}>{content.note}</div>;
    case "text":
      return <pre className={`${styles.pre} ${styles.block}`}>{content.text}</pre>;
    case "json":
      return <pre className={`${styles.pre} ${styles.block} ${styles.json}`}>{content.text}</pre>;
    case "chat":
      return (
        <div className={styles.chat}>
          {content.system !== "" ? (
            <Disclosure className={styles.system}>
              <Disclosure.Heading>
                <Disclosure.Trigger className={styles.systemTrigger}>
                  <span className={styles.role}>system prompt</span>
                  <span className={styles.hint}>{compactTokens(content.system.length)} chars</span>
                  {content.tools.length > 0 ? <span className={styles.hint}>· {content.tools.length} tools</span> : null}
                  <Disclosure.Indicator />
                </Disclosure.Trigger>
              </Disclosure.Heading>
              <Disclosure.Content>
                <Disclosure.Body>
                  <pre className={styles.pre}>{content.system}</pre>
                  {content.tools.length > 0 ? <p className={styles.hint}>tools: {content.tools.join(", ")}</p> : null}
                </Disclosure.Body>
              </Disclosure.Content>
            </Disclosure>
          ) : null}
          {content.omitted > 0 ? <div className={styles.hint}>… {content.omitted} earlier messages, sent in the calls before</div> : null}
          {content.parts.map((part, index) => (
            <Message key={index} part={part} />
          ))}
        </div>
      );
  }
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: "bad" }) {
  return (
    <div className={styles.metric}>
      <span className={styles.metricLabel}>{label}</span>
      <span className={`${styles.metricValue} ${tone === "bad" ? styles.bad : ""}`}>{value}</span>
    </div>
  );
}

/** One step opened: how long it took, what it cost, what went in and what came out. */
export function SpanDetail({ node, name }: { node: TraceNode; name: (actorId: string | null) => string }) {
  const { span, totals } = node;
  const [tab, setTab] = useState<string>(span.kind === "approval" ? "metadata" : "output");
  const cached = cachedShare(totals);
  const sent = totals.input + totals.cached + totals.written;
  const metrics: [string, string, ("bad" | undefined)?][] = [
    ["duration", compactDuration(node.durationMs)],
    ...(span.kind === "llm" && span.first_ms !== null ? [["first token", compactDuration(span.first_ms)] as [string, string]] : []),
    ...(sent > 0 ? [["input", `${compactTokens(sent)} tok`] as [string, string]] : []),
    ...(totals.output > 0 ? [["output", `${compactTokens(totals.output)} tok`] as [string, string]] : []),
    ...(cached !== null ? [["cached", `${Math.round(cached * 100)}%`] as [string, string]] : []),
    ...(span.kind === "llm" && span.context_tokens > 0 ? [["context", `${compactTokens(span.context_tokens)} tok`] as [string, string]] : []),
    ...(span.chars > 0 ? [["result", `${compactTokens(span.chars)} chars`] as [string, string]] : []),
  ];
  const started = new Date(span.started_ms);
  const meta: [string, string][] = [
    ["kind", span.kind],
    ["name", span.name],
    ...(span.model ? [["model", span.model] as [string, string]] : []),
    ...(span.detail ? [["subject", span.detail] as [string, string]] : []),
    ["started", started.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })],
    ...(span.actor_id !== null ? [[span.kind === "approval" ? "answered by" : "by", name(span.actor_id)] as [string, string]] : []),
    ...(node.children.length > 0 ? [["inside", `${totals.models} model · ${totals.tools} tool calls · ${compactTokens(totalTokens(totals))} tokens`] as [string, string]] : []),
    ["span", span.id],
    ...(span.parent_id ? [["parent", span.parent_id] as [string, string]] : []),
    ["run", span.run_id],
  ];
  return (
    <div className={styles.inspector} style={kindColor(span.kind)}>
      <div className={styles.detailHead}>
        <span className={styles.dot} />
        <span className={styles.detailTitle}>{spanTitle(span)}</span>
        <span className={styles.detailSub}>{span.kind === "llm" ? span.model : span.detail}</span>
        <StatusChip status={span.status} />
      </div>
      <div className={styles.metrics}>
        {metrics.map(([label, value, tone]) => (
          <Metric key={label} label={label} value={value} tone={tone} />
        ))}
      </div>
      {span.error !== "" ? <div className={styles.errorBox}>{span.error}</div> : null}
      <Tabs selectedKey={tab} onSelectionChange={(key) => setTab(String(key))} className={styles.detailTabs}>
        <div className={styles.detailBar}>
          <Tabs.ListContainer>
            <Tabs.List aria-label="What to show of this step">
              <Tabs.Tab id="input">
                Input
                <Tabs.Indicator />
              </Tabs.Tab>
              <Tabs.Tab id="output">
                Output
                <Tabs.Indicator />
              </Tabs.Tab>
              <Tabs.Tab id="metadata">
                Metadata
                <Tabs.Indicator />
              </Tabs.Tab>
            </Tabs.List>
          </Tabs.ListContainer>
          {tab === "metadata" ? null : <CopyButton text={copyable(span, tab === "input" ? "input" : "output")} label={`Copy the ${tab}`} />}
        </div>
        <Tabs.Panel id="input" className={styles.panel}>
          <ScrollShadow className={styles.panelScroll}>
            <ContentView content={spanInput(span)} />
          </ScrollShadow>
        </Tabs.Panel>
        <Tabs.Panel id="output" className={styles.panel}>
          <ScrollShadow className={styles.panelScroll}>
            <ContentView content={spanOutput(span)} />
          </ScrollShadow>
        </Tabs.Panel>
        <Tabs.Panel id="metadata" className={styles.panel}>
          <ScrollShadow className={styles.panelScroll}>
            <dl className={styles.meta}>
              {meta.map(([label, value]) => (
                <div key={label} className={styles.metaRow}>
                  <dt>{label}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          </ScrollShadow>
        </Tabs.Panel>
      </Tabs>
    </div>
  );
}
