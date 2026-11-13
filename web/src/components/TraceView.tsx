import { Button, Card, Drawer, Kbd, ListBox, Select, Skeleton, Tabs, Tooltip, type Key } from "@heroui/react";
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
import type { Trace, TraceTab } from "../hooks/useSession";
import { layoutGraph, NODE } from "../lib/traceGraph";
import { kindColor, SpanDetail, StatusChip } from "./SpanDetail";
import styles from "./TraceView.module.css";

const KINDS: { kind: SpanKind; label: string }[] = [
  { kind: "llm", label: "model" },
  { kind: "tool", label: "tool" },
  { kind: "agent", label: "sub-agent" },
  { kind: "approval", label: "approval" },
];

const GRAPH_KINDS: Record<GraphNode["kind"], string> = { person: "run", agent: "agent", model: "llm", tool: "tool" };

type Name = (actorId: string | null) => string;

function Field({ label, value, bad = false }: { label: string; value: string; bad?: boolean }) {
  return (
    <span className={styles.field}>
      <span className={styles.fieldLabel}>{label}</span>
      <span className={`${styles.fieldValue} ${bad ? styles.bad : ""}`}>{value}</span>
    </span>
  );
}

function Tiles({ node }: { node: TraceNode }) {
  const cached = cachedShare(node.totals);
  const tiles: [string, string][] = [
    [compactTokens(totalTokens(node.totals)), "tokens"],
    [cached === null ? "·" : `${Math.round(cached * 100)}%`, "from cache"],
    [String(node.totals.models), "model calls"],
    [String(node.totals.tools), "tool calls"],
    [compactDuration(node.durationMs), node.span.status === "running" ? "so far" : "in all"],
  ];
  return (
    <div className={styles.tiles}>
      {tiles.map(([value, label]) => (
        <Card key={label} className={styles.tile}>
          <span className={styles.tileValue}>{value}</span>
          <span className={styles.tileLabel}>{label}</span>
        </Card>
      ))}
    </div>
  );
}

function RunTimeline({ spans, name }: { spans: readonly Span[]; name: Name }) {
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
  const at = nodes.indexOf(shown);
  // Up and down step through the rows, the way a list of calls is read.
  const step = (by: number) => {
    const next = nodes[Math.min(nodes.length - 1, Math.max(0, at + by))];
    if (next !== undefined) {
      setPicked(next.span.id);
      document.getElementById(`span-${next.span.id}`)?.focus();
    }
  };
  return (
    <>
      <Tiles node={root} />
      <div className={styles.split}>
        <div className={styles.scroll}>
          <div
            className={styles.rows}
            role="grid"
            aria-label="The run's steps"
            onKeyDown={(event) => {
              if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                event.preventDefault();
                step(event.key === "ArrowDown" ? 1 : -1);
              }
            }}
          >
            <div className={styles.head} role="row">
              <span role="columnheader">step</span>
              <span role="columnheader" className={styles.num}>
                tokens
              </span>
              <span role="columnheader" className={styles.ticks}>
                {[0, 0.5].map((tick) => (
                  <span key={tick} className={styles.tick} style={{ left: `${tick * 100}%` }}>
                    {compactDuration(length * tick)}
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
                  id={`span-${span.id}`}
                  type="button"
                  role="row"
                  className={styles.row}
                  aria-selected={shown.span.id === span.id}
                  tabIndex={shown.span.id === span.id ? 0 : -1}
                  style={kindColor(span.kind)}
                  onClick={() => setPicked(span.id)}
                >
                  <span role="gridcell" className={styles.name} style={{ paddingLeft: node.depth * 14 }}>
                    <span className={styles.dot} />
                    <span className={styles.title}>{spanTitle(span)}</span>
                    <span className={styles.detail}>{span.kind === "llm" ? span.model : span.detail}</span>
                    {bad ? <span className={styles.flag}>✕</span> : null}
                  </span>
                  <span role="gridcell" className={`${styles.num} ${tokens === 0 ? styles.quiet : ""}`}>
                    {tokens === 0 ? "" : compactTokens(tokens)}
                  </span>
                  <span role="gridcell" className={styles.track}>
                    <span className={styles.grid} style={{ left: "50%" }} />
                    <span
                      className={styles.span}
                      data-status={span.status}
                      style={{ left: `${((span.started_ms - start) / length) * 100}%`, width: `${(node.durationMs / length) * 100}%` }}
                    />
                  </span>
                  <span role="gridcell" className={`${styles.num} ${styles.quiet}`}>
                    {compactDuration(node.durationMs)}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
        <SpanDetail key={shown.span.id} node={shown} name={name} />
      </div>
    </>
  );
}

function SessionGraph({ spans, name }: { spans: readonly Span[]; name: Name }) {
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
  const runs = traceTree(spans).length;
  const tokens = layout.nodes.filter((node) => node.kind === "person").reduce((sum, node) => sum + node.tokens, 0);
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
              aria-label={`${node.label}: ${node.calls} ${node.kind === "person" ? "runs" : "calls"}${node.tokens > 0 ? `, ${compactTokens(node.tokens)} tokens` : ""}`}
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
      <Card className={styles.inspect} aria-live="polite">
        {shown === null ? (
          <>
            <Field label="runs" value={String(runs)} />
            <Field label="tokens" value={compactTokens(tokens)} />
            <span className={styles.hint}>point at a node to see what it called and what called it</span>
          </>
        ) : (
          <>
            <span className={styles.factsHead} style={kindColor(GRAPH_KINDS[shown.kind])}>
              <span className={styles.dot} />
              <span className={styles.title}>{shown.label}</span>
              <span className={styles.detail}>{shown.kind}</span>
            </span>
            <Field label={shown.kind === "person" ? "runs started" : "calls"} value={String(shown.calls)} />
            {shown.tokens > 0 ? <Field label="tokens" value={compactTokens(shown.tokens)} /> : null}
            {shown.durationMs > 0 ? <Field label="time in it" value={compactDuration(shown.durationMs)} /> : null}
            {shown.failed > 0 ? <Field label="failed" value={String(shown.failed)} bad /> : null}
          </>
        )}
      </Card>
    </>
  );
}

function Loading() {
  return (
    <div className={styles.loading} aria-busy="true" aria-label="Loading the trace">
      <div className={styles.tiles}>
        {[0, 1, 2, 3, 4].map((index) => (
          <Skeleton key={index} className="h-[58px] rounded-xl" />
        ))}
      </div>
      {[0, 1, 2, 3, 4, 5].map((index) => (
        <Skeleton key={index} className="h-6 rounded-lg" style={{ width: `${92 - index * 9}%` }} />
      ))}
    </div>
  );
}

function runLabel(run: Span, name: Name): string {
  const at = new Date(run.started_ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const what = run.detail === "" ? run.name : run.detail;
  return `${at} · ${name(run.actor_id)} · ${what.length > 44 ? `${what.slice(0, 43)}…` : what}`;
}

export function TraceView({ trace, projection, send, onClose }: { trace: Trace; projection: Projection; send: (command: Command) => void; onClose: () => void }) {
  const [tab, setTab] = useState<TraceTab>(trace.tab);
  const participants = projection.state.participants;
  const name = useMemo<Name>(() => (actorId) => (actorId === null ? "the host" : (participants[actorId]?.name ?? "someone")), [participants]);
  const run = trace.run;
  const runId = run?.run_id ?? null;
  const running = run?.spans.some((span) => span.status === "running") ?? false;
  const ask = (next: TraceTab, id: string | null = runId) =>
    send(next === "session" ? { type: "trace.get", run_id: null, everything: true } : { type: "trace.get", run_id: id, everything: false });

  // A run still going is asked about again, so the picture follows it.
  useEffect(() => {
    if (tab !== "run" || !running) return;
    const timer = setInterval(() => ask("run"), 1500);
    return () => clearInterval(timer);
  }, [tab, running, runId]);

  const choose = (key: Key) => {
    const next = key === "session" ? "session" : "run";
    setTab(next);
    if ((next === "session" ? trace.session : trace.run) === null) ask(next);
  };
  const runs = run?.runs ?? trace.session?.runs ?? [];
  const body =
    tab === "run" ? (
      run === null ? (
        trace.waiting ? (
          <Loading />
        ) : (
          <div className={styles.empty}>No run has been traced yet. Ask the agent something and it shows here.</div>
        )
      ) : (
        <RunTimeline key={run.run_id ?? ""} spans={run.spans} name={name} />
      )
    ) : trace.session === null ? (
      <Loading />
    ) : (
      <SessionGraph spans={trace.session.spans} name={name} />
    );

  return (
    <Drawer.Backdrop isOpen variant="transparent" onOpenChange={(open) => !open && onClose()}>
      <Drawer.Content placement="right">
        <Drawer.Dialog className={styles.drawer} aria-label="Trace">
          <Drawer.Header className={styles.header}>
            <Drawer.Heading className="font-display text-xl font-medium tracking-[-0.02em]">Trace</Drawer.Heading>
            {running ? <StatusChip status="running" /> : null}
            <span className="grow" />
            <Tooltip delay={300}>
              <Button isIconOnly size="sm" variant="ghost" aria-label="Refresh" onPress={() => ask(tab)}>
                <ArrowClockwise size={16} />
              </Button>
              <Tooltip.Content>Ask the host again</Tooltip.Content>
            </Tooltip>
            <Tooltip delay={300}>
              <Drawer.CloseTrigger />
              <Tooltip.Content>
                Close <Kbd className="ml-1 h-5 px-1 text-[11px]"><Kbd.Content>esc</Kbd.Content></Kbd> or{" "}
                <Kbd className="h-5 px-1 text-[11px]"><Kbd.Content>t</Kbd.Content></Kbd>
              </Tooltip.Content>
            </Tooltip>
          </Drawer.Header>
          <Drawer.Body className={styles.body}>
            <div className={styles.trace}>
              <div className={styles.bar}>
                <Tabs selectedKey={tab} onSelectionChange={choose}>
                  <Tabs.ListContainer>
                    <Tabs.List aria-label="What to show">
                      <Tabs.Tab id="run">
                        One run
                        <Tabs.Indicator />
                      </Tabs.Tab>
                      <Tabs.Tab id="session">
                        Whole session
                        <Tabs.Indicator />
                      </Tabs.Tab>
                    </Tabs.List>
                  </Tabs.ListContainer>
                </Tabs>
                {tab === "run" && runs.length > 1 && runId !== null ? (
                  <Select aria-label="Which run" className={styles.pick} value={runId} onChange={(value) => ask("run", String(value as Key))}>
                    <Select.Trigger>
                      <Select.Value />
                      <Select.Indicator />
                    </Select.Trigger>
                    <Select.Popover>
                      <ListBox>
                        {runs.map((item) => (
                          <ListBox.Item key={item.run_id} id={item.run_id} textValue={runLabel(item, name)}>
                            {runLabel(item, name)}
                            <ListBox.ItemIndicator />
                          </ListBox.Item>
                        ))}
                      </ListBox>
                    </Select.Popover>
                  </Select>
                ) : null}
                <div className={styles.legend} aria-label="Colors">
                  {KINDS.map((item) => (
                    <span key={item.kind} className={styles.key} style={kindColor(item.kind)}>
                      <span className={styles.swatch} />
                      {item.label}
                    </span>
                  ))}
                </div>
              </div>
              {body}
            </div>
          </Drawer.Body>
        </Drawer.Dialog>
      </Drawer.Content>
    </Drawer.Backdrop>
  );
}
