import { Button, Modal } from "@heroui/react";
import { ArrowClockwise } from "@phosphor-icons/react";
import { useEffect, useMemo, useState, type CSSProperties } from "react";
import {
  cachedShare,
  callGraph,
  compactDuration,
  compactTokens,
  flattenTrace,
  spanTitle,
  totalTokens,
  traceTree,
  type Command,
  type GraphNode,
  type Projection,
  type Span,
  type SpanKind,
  type TraceNode,
} from "@plural/client";
import type { Trace } from "../hooks/useSession";
import { layoutGraph, NODE } from "../lib/traceGraph";
import styles from "./TraceView.module.css";

type Tab = "run" | "session";

const KINDS: { kind: SpanKind; label: string }[] = [
  { kind: "llm", label: "model call" },
  { kind: "tool", label: "tool call" },
  { kind: "agent", label: "sub-agent" },
  { kind: "approval", label: "waiting for approval" },
];

const GRAPH_KINDS: Record<GraphNode["kind"], string> = { person: "run", agent: "agent", model: "llm", tool: "tool" };

const kindColor = (kind: string): CSSProperties => ({ "--kind": `var(--kind-${kind})` }) as CSSProperties;

const STATUS_WORDS: Record<Span["status"], string> = { ok: "finished", running: "running", error: "failed", denied: "denied", cancelled: "stopped" };

function Field({ label, value, bad = false }: { label: string; value: string; bad?: boolean }) {
  return (
    <span className={styles.field}>
      <span className={styles.fieldLabel}>{label}</span>
      <span className={`${styles.fieldValue} ${bad ? styles.bad : ""}`}>{value}</span>
    </span>
  );
}

/** Everything known about one step, in words: the row's bar says when, this says what. */
function SpanFacts({ node, name }: { node: TraceNode; name: (actorId: string | null) => string }) {
  const { span, totals } = node;
  const cached = cachedShare(totals);
  const bad = span.status === "error" || span.status === "denied";
  return (
    <>
      <Field label={spanTitle(span)} value={span.kind === "llm" ? span.model : span.detail || "·"} />
      <Field label="status" value={STATUS_WORDS[span.status]} bad={bad} />
      <Field label="took" value={compactDuration(node.durationMs)} />
      {totalTokens(totals) > 0 ? (
        <>
          <Field label="sent" value={compactTokens(totals.input + totals.cached + totals.written)} />
          {cached !== null ? <Field label="from cache" value={`${Math.round(cached * 100)}%`} /> : null}
          <Field label="received" value={compactTokens(totals.output)} />
        </>
      ) : null}
      {span.kind === "llm" && span.context_tokens > 0 ? <Field label="context then" value={compactTokens(span.context_tokens)} /> : null}
      {span.kind === "llm" && span.first_ms !== null ? <Field label="first token" value={compactDuration(span.first_ms)} /> : null}
      {span.kind !== "llm" && node.children.length > 0 ? <Field label="inside" value={`${totals.models} model · ${totals.tools} tool calls`} /> : null}
      {span.chars > 0 ? <Field label="result" value={`${compactTokens(span.chars)} chars`} /> : null}
      {span.actor_id !== null ? <Field label={span.kind === "approval" ? "answered by" : "by"} value={name(span.actor_id)} /> : null}
      {span.error !== "" ? <Field label="error" value={span.error} bad /> : null}
    </>
  );
}

function RunTimeline({ spans, name }: { spans: readonly Span[]; name: (actorId: string | null) => string }) {
  // A run still going is measured up to now, so its bars grow between answers.
  const roots = useMemo(() => traceTree(spans), [spans]);
  const nodes = useMemo(() => flattenTrace(roots), [roots]);
  const [picked, setPicked] = useState<string | null>(null);
  const root = roots[0];
  if (root === undefined) {
    return <div className={styles.empty}>Nothing was traced for this run.</div>;
  }
  const start = root.span.started_ms;
  const length = Math.max(1, ...nodes.map((node) => node.span.started_ms + node.durationMs - start));
  const shown = nodes.find((node) => node.span.id === picked) ?? root;
  const cached = cachedShare(root.totals);
  return (
    <>
      <div className={styles.tiles}>
        {[
          [compactTokens(totalTokens(root.totals)), "tokens"],
          [cached === null ? "·" : `${Math.round(cached * 100)}%`, "of the prompt from cache"],
          [String(root.totals.models), "model calls"],
          [String(root.totals.tools), "tool calls"],
          [compactDuration(root.durationMs), root.span.status === "running" ? "so far" : "in all"],
        ].map(([value, label]) => (
          <div key={label} className={styles.tile}>
            <div className={styles.tileValue}>{value}</div>
            <div className={styles.tileLabel}>{label}</div>
          </div>
        ))}
      </div>
      <div className={styles.scroll}>
        <div className={styles.rows} role="table" aria-label="The run's steps">
          <div className={styles.head} role="row">
            <span role="columnheader">step</span>
            <span role="columnheader" className={styles.num}>
              tokens
            </span>
            <span role="columnheader" className={styles.ticks}>
              {[0, 0.25, 0.5, 0.75].map((at) => (
                <span key={at} className={styles.tick} style={{ left: `${at * 100}%` }}>
                  {compactDuration(length * at)}
                </span>
              ))}
            </span>
            <span role="columnheader" className={styles.num}>
              time
            </span>
          </div>
          {nodes.map((node) => {
            const { span } = node;
            const tokens = totalTokens(node.totals);
            const bad = span.status === "error" || span.status === "denied";
            return (
              <button
                key={span.id}
                type="button"
                role="row"
                className={styles.row}
                aria-selected={shown.span.id === span.id}
                style={kindColor(span.kind)}
                onClick={() => setPicked(span.id)}
                onMouseEnter={() => setPicked(span.id)}
                onFocus={() => setPicked(span.id)}
              >
                <span role="cell" className={styles.name} style={{ paddingLeft: node.depth * 16 }}>
                  <span className={styles.dot} />
                  <span className={styles.title}>{spanTitle(span)}</span>
                  <span className={styles.detail}>{span.kind === "llm" ? span.model : span.detail}</span>
                  {bad ? <span className={styles.flag}>✕ {STATUS_WORDS[span.status]}</span> : null}
                </span>
                <span role="cell" className={`${styles.num} ${tokens === 0 ? styles.quiet : ""}`}>
                  {tokens === 0 ? "" : compactTokens(tokens)}
                </span>
                <span role="cell" className={styles.track}>
                  {[0.25, 0.5, 0.75].map((at) => (
                    <span key={at} className={styles.grid} style={{ left: `${at * 100}%` }} />
                  ))}
                  <span
                    className={styles.span}
                    data-status={span.status}
                    style={{ left: `${((span.started_ms - start) / length) * 100}%`, width: `${(node.durationMs / length) * 100}%` }}
                  />
                </span>
                <span role="cell" className={`${styles.num} ${styles.quiet}`}>
                  {compactDuration(node.durationMs)}
                </span>
              </button>
            );
          })}
        </div>
      </div>
      <div className={styles.inspect} aria-live="polite">
        <SpanFacts node={shown} name={name} />
      </div>
    </>
  );
}

function SessionGraph({ spans, name }: { spans: readonly Span[]; name: (actorId: string | null) => string }) {
  const graph = useMemo(() => callGraph(spans, name), [spans, name]);
  const layout = useMemo(() => layoutGraph(graph), [graph]);
  const [picked, setPicked] = useState<string | null>(null);
  if (layout.nodes.length === 0) {
    return <div className={styles.empty}>No run has been traced in this session yet.</div>;
  }
  const near = new Set<string>(picked === null ? [] : [picked]);
  for (const edge of layout.edges) {
    if (edge.from === picked) near.add(edge.to);
    if (edge.to === picked) near.add(edge.from);
  }
  const shown = layout.nodes.find((node) => node.id === picked) ?? null;
  const runs = spans.filter((span) => span.parent_id === null).length;
  return (
    <>
      <div className={styles.scroll}>
        <svg className={styles.graph} width={layout.width} height={layout.height} role="img" aria-label="Who called what in this session">
          {layout.edges.map((edge) => (
            <path
              key={`${edge.from}>${edge.to}`}
              className={styles.edge}
              d={edge.path}
              strokeWidth={edge.width}
              data-on={picked === null ? undefined : edge.from === picked || edge.to === picked}
            >
              <title>{`${edge.calls} call${edge.calls === 1 ? "" : "s"}${edge.tokens > 0 ? ` · ${compactTokens(edge.tokens)} tokens` : ""}`}</title>
            </path>
          ))}
          {layout.nodes.map((node) => (
            <g
              key={node.id}
              className={styles.node}
              transform={`translate(${node.x} ${node.y})`}
              tabIndex={0}
              style={kindColor(GRAPH_KINDS[node.kind])}
              data-on={picked === null ? undefined : near.has(node.id)}
              onMouseEnter={() => setPicked(node.id)}
              onMouseLeave={() => setPicked(null)}
              onFocus={() => setPicked(node.id)}
              onBlur={() => setPicked(null)}
            >
              <rect className={styles.box} width={NODE.width} height={NODE.height} rx={10} />
              <rect className={styles.stripe} x={0} y={12} width={3} height={NODE.height - 24} rx={1.5} />
              <text className={styles.nodeLabel} x={14} y={24}>
                {node.label.length > 22 ? `${node.label.slice(0, 21)}…` : node.label}
              </text>
              <text className={styles.nodeMeta} x={14} y={43}>
                {`${node.calls}× ${node.kind === "person" ? "runs" : "calls"}${node.tokens > 0 ? ` · ${compactTokens(node.tokens)}` : ""}`}
              </text>
              {node.failed > 0 ? (
                <text className={styles.nodeBad} x={NODE.width - 12} y={43} textAnchor="end">
                  {`${node.failed} failed`}
                </text>
              ) : null}
            </g>
          ))}
        </svg>
      </div>
      <div className={styles.inspect} aria-live="polite">
        {shown === null ? (
          <Field label={`${runs} run${runs === 1 ? "" : "s"}`} value="point at a node to see what it called and what called it" />
        ) : (
          <>
            <Field label={shown.kind} value={shown.label} />
            <Field label={shown.kind === "person" ? "runs started" : "calls"} value={String(shown.calls)} />
            {shown.tokens > 0 ? <Field label="tokens" value={compactTokens(shown.tokens)} /> : null}
            {shown.durationMs > 0 ? <Field label="time in it" value={compactDuration(shown.durationMs)} /> : null}
            {shown.failed > 0 ? <Field label="failed" value={String(shown.failed)} bad /> : null}
          </>
        )}
      </div>
    </>
  );
}

function runLabel(run: Span, name: (actorId: string | null) => string): string {
  const at = new Date(run.started_ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const what = run.detail === "" ? run.name : run.detail;
  return `${at} · ${name(run.actor_id)} · ${what.length > 48 ? `${what.slice(0, 47)}…` : what}`;
}

export function TraceView({ trace, projection, send, onClose }: { trace: Trace; projection: Projection; send: (command: Command) => void; onClose: () => void }) {
  const [tab, setTab] = useState<Tab>(trace.run === null ? "session" : "run");
  const participants = projection.state.participants;
  const name = useMemo(() => (actorId: string | null) => (actorId === null ? "the host" : (participants[actorId]?.name ?? "someone")), [participants]);
  const run = trace.run;
  const runId = run?.run_id ?? null;
  const running = run?.spans.some((span) => span.status === "running") ?? false;
  const ask = (next: Tab, id: string | null = runId) => send(next === "session" ? { type: "trace.get", run_id: null, everything: true } : { type: "trace.get", run_id: id, everything: false });

  // A run still going is asked about again, so the picture follows it.
  useEffect(() => {
    if (tab !== "run" || !running) return;
    const timer = setInterval(() => ask("run"), 1500);
    return () => clearInterval(timer);
  }, [tab, running, runId]);

  const open = (next: Tab) => {
    setTab(next);
    if ((next === "session" ? trace.session : trace.run) === null) ask(next);
  };
  const runs = run?.runs ?? trace.session?.runs ?? [];

  return (
    <Modal.Backdrop isOpen onOpenChange={(isOpen) => !isOpen && onClose()}>
      <Modal.Container>
        <Modal.Dialog className="sm:max-w-[min(72rem,96vw)]">
          <Modal.CloseTrigger />
          <Modal.Header>
            <Modal.Heading className="font-display text-2xl font-medium tracking-[-0.02em]">Trace</Modal.Heading>
          </Modal.Header>
          <Modal.Body>
            <div className={styles.trace}>
              <div className={styles.bar}>
                <div className={styles.tabs} role="tablist" aria-label="What to show">
                  <button type="button" role="tab" className={styles.tab} aria-selected={tab === "run"} onClick={() => open("run")}>
                    One run
                  </button>
                  <button type="button" role="tab" className={styles.tab} aria-selected={tab === "session"} onClick={() => open("session")}>
                    Whole session
                  </button>
                </div>
                {tab === "run" && runs.length > 0 ? (
                  <select className={styles.pick} aria-label="Which run" value={runId ?? ""} onChange={(event) => ask("run", event.target.value)}>
                    {runs.map((item) => (
                      <option key={item.run_id} value={item.run_id}>
                        {runLabel(item, name)}
                      </option>
                    ))}
                  </select>
                ) : null}
                <Button size="sm" variant="tertiary" aria-label="Refresh" onPress={() => ask(tab)}>
                  <ArrowClockwise size={15} />
                  Refresh
                </Button>
                <div className={styles.legend}>
                  {KINDS.map((item) => (
                    <span key={item.kind} className={styles.key} style={kindColor(item.kind)}>
                      <span className={styles.swatch} />
                      {item.label}
                    </span>
                  ))}
                </div>
              </div>
              {tab === "run" ? (
                run === null ? (
                  <div className={styles.empty}>No run has been traced yet. Ask the agent something, then open the trace again.</div>
                ) : (
                  <RunTimeline key={run.run_id ?? ""} spans={run.spans} name={name} />
                )
              ) : trace.session === null ? (
                <div className={styles.empty}>Adding the session up…</div>
              ) : (
                <SessionGraph spans={trace.session.spans} name={name} />
              )}
            </div>
          </Modal.Body>
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
  );
}
