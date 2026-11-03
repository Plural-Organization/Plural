import { label, type AccessRequestView, type BriefingRequestView, type ApprovalView, type JoinRequestView, type ProposalView, type SessionState } from "@plural/client";
import { colorFor, theme } from "../theme";

export type InboxItem =
  | { kind: "join"; id: string; request: JoinRequestView }
  | { kind: "access"; id: string; request: AccessRequestView }
  | { kind: "briefing"; id: string; request: BriefingRequestView }
  | { kind: "approval"; id: string; approval: ApprovalView }
  | { kind: "proposal"; id: string; proposal: ProposalView }
  | { kind: "plan"; id: string };

export function inboxItems(state: SessionState): InboxItem[] {
  return [
    ...Object.values(state.join_requests).map((request): InboxItem => ({ kind: "join", id: request.id, request })),
    ...Object.values(state.access_requests).map((request): InboxItem => ({ kind: "access", id: request.participant_id, request })),
    ...Object.values(state.briefing_requests).map((request): InboxItem => ({ kind: "briefing", id: request.id, request })),
    ...Object.values(state.approvals).map((approval): InboxItem => ({ kind: "approval", id: approval.id, approval })),
    ...Object.values(state.proposals).map((proposal): InboxItem => ({ kind: "proposal", id: proposal.id, proposal })),
  ];
}

function from(state: SessionState, participantId: string): string {
  const participant = state.participants[participantId];
  return participant ? label(state, participant) : participantId;
}

// What an approval may be answered with, in the order its keys are shown.
export const APPROVAL_DECISIONS = ["once", "always", "reject", "block"] as const;

// A folder request is answered with how far the folder opens, or not at all.
export const FOLDER_DECISIONS = ["read", "write", "reject"] as const;

export function decisionsOf(approval: ApprovalView): readonly string[] {
  return approval.folder ? FOLDER_DECISIONS : APPROVAL_DECISIONS;
}

// Enter on a folder request refuses until you move to a wider answer, so a stray Enter opens nothing.
export function defaultChoice(approval: ApprovalView): number {
  return approval.folder ? FOLDER_DECISIONS.length - 1 : 0;
}

export function isFolderRequest(item: InboxItem | undefined): boolean {
  return item?.kind === "approval" && Boolean(item.approval.folder);
}

// With `selected`, that choice is marked and Enter takes it.
function Keys({ items, selected }: { items: [string, string][]; selected?: number }) {
  return (
    <text>
      {items.map(([key, action], index) => (
        <span key={key}>
          {index > 0 ? "   " : ""}
          <span fg={index === selected ? theme.bg : theme.accent} bg={index === selected ? theme.accent : undefined}>
            <b>{key}</b>
            {index === selected ? <span> {action}</span> : null}
          </span>
          {index === selected ? null : <span fg={theme.dim}> {action}</span>}
        </span>
      ))}
    </text>
  );
}

interface InboxProps {
  items: InboxItem[];
  state: SessionState;
  selected: number;
  focused: boolean;
  now: number;
  approvalChoice?: { id: string; index: number } | null;
}

export function Inbox({ items, state, selected, focused, now, approvalChoice }: InboxProps) {
  const index = Math.min(selected, items.length - 1);
  const item = items[index];
  if (!item) {
    return null;
  }
  return (
    <box
      flexDirection="column"
      border
      borderStyle={isFolderRequest(item) ? "heavy" : "rounded"}
      borderColor={isFolderRequest(item) ? theme.danger : focused ? theme.warn : theme.dim}
      paddingX={1}
      marginX={2}
      flexShrink={0}
    >
      {item.kind === "approval" ? null : (
      <text>
        <span fg={theme.warn}>
          <b>{item.kind === "join" ? "wants to join" : item.kind === "access" ? "wants to write" : item.kind === "briefing" ? "wants a briefing" : item.kind === "plan" ? "plan ready" : "proposal"}</b>
        </span>
        <span fg={theme.dim}>
          {"  "}
          {index + 1}/{items.length}
        </span>
      </text>
      )}
      {item.kind === "join" ? (
        <JoinBody request={item.request} now={now} focused={focused} />
      ) : item.kind === "access" ? (
        <AccessBody request={item.request} now={now} focused={focused} />
      ) : item.kind === "briefing" ? (
        <BriefingBody request={item.request} now={now} focused={focused} />
      ) : item.kind === "approval" ? (
        <ApprovalBody approval={item.approval} state={state} now={now} focused={focused} selected={approvalChoice?.id === item.id ? approvalChoice.index : defaultChoice(item.approval)} place={items.length > 1 ? `${index + 1}/${items.length}` : ""} />
      ) : item.kind === "plan" ? (
        <PlanBody focused={focused} />
      ) : (
        <ProposalBody proposal={item.proposal} state={state} focused={focused} />
      )}
    </box>
  );
}

function JoinBody({ request, now, focused }: { request: JoinRequestView; now: number; focused: boolean }) {
  const seconds = Math.max(0, Math.round((now - Date.parse(request.requested_at)) / 1000));
  return (
    <>
      <text>
        <span fg={colorFor(request.id)}>
          <b>{request.name}</b>
        </span>
        <span fg={theme.dim}>
          {" "}
          · {request.client} · waiting {seconds}s · came in with the room link
        </span>
      </text>
      {focused ? (
        <Keys items={[["y", "let in"], ["v", "as a viewer"], ["n", "refuse"]]} />
      ) : (
        <text fg={theme.dim}>tab to answer</text>
      )}
    </>
  );
}

function BriefingBody({ request, now, focused }: { request: BriefingRequestView; now: number; focused: boolean }) {
  const seconds = Math.max(0, Math.round((now - Date.parse(request.requested_at)) / 1000));
  return (
    <>
      <text>
        <span fg={colorFor(request.participant_id)}>
          <b>{request.name}</b>
        </span>
        <span fg={theme.dim}> · asks your agent to brief them{request.update ? " (an update)" : ""} · {seconds}s ago</span>
      </text>
      {request.focus ? <text>{request.focus}</text> : null}
      {focused ? <Keys items={[["y", "write it"], ["n", "not now"]]} /> : <text fg={theme.dim}>tab to answer</text>}
    </>
  );
}

function AccessBody({ request, now, focused }: { request: AccessRequestView; now: number; focused: boolean }) {
  const seconds = Math.max(0, Math.round((now - Date.parse(request.requested_at)) / 1000));
  return (
    <>
      <text>
        <span fg={colorFor(request.participant_id)}>
          <b>{request.name}</b>
        </span>
        <span fg={theme.dim}> · watching · asked {seconds}s ago</span>
      </text>
      {request.note ? <text>{request.note}</text> : null}
      {focused ? <Keys items={[["y", "let them write"], ["n", "not now"]]} /> : <text fg={theme.dim}>tab to answer</text>}
    </>
  );
}

function FolderBody({ approval, state, now, focused, selected, place }: { approval: ApprovalView; state: SessionState; now: number; focused: boolean; selected: number; place: string }) {
  const folder = approval.folder;
  if (!folder) {
    return null;
  }
  const call = approval.call;
  const seconds = Math.max(0, Math.round((Date.parse(approval.timeout_at) - now) / 1000));
  const who = from(state, approval.provenance.initiator_id);
  const labels = ["read", "read + write", "refuse"];
  const meaning = [
    "the agent may only look at files in this folder, for this one call",
    "the agent may also change files in this folder, for this one call",
    "open nothing",
  ];
  return (
    <>
      <text wrapMode="word" fg={theme.danger}>
        <b>⚠ FOLDER OUTSIDE THE SESSION · {who} asks the agent to {folder.write ? "CHANGE" : "READ"} files here</b>
      </text>
      <text wrapMode="word" fg={theme.danger}>
        <b>{folder.folder}</b>
      </text>
      <text wrapMode="word" fg={theme.dim}>
        for: {call.name} {call.subject}
      </text>
      {folder.broad ? (
        <text wrapMode="word" fg={theme.danger}>
          <b>⚠ this is your whole disk or your home folder, not a project</b>
        </text>
      ) : null}
      <text wrapMode="word">
        {FOLDER_DECISIONS.map((decision, index) => (
          <span key={decision}>
            {index > 0 ? "  " : ""}
            {focused && index === selected ? (
              <span fg={theme.bg} bg={theme.danger}>
                <b>{` ${labels[index]} `}</b>
              </span>
            ) : (
              <span fg={focused ? theme.danger : theme.dim}>{labels[index]}</span>
            )}
          </span>
        ))}
      </text>
      <text fg={theme.dim}>
        {focused ? `r read · w read + write · n refuse · ←/→ choose, enter confirms · ${meaning[selected] ?? ""}` : "tab to answer"}
      </text>
      <text fg={theme.dim}>
        {`asked every time, nothing is remembered · expires in ${seconds}s${place ? ` · ${place}` : ""}`}
      </text>
    </>
  );
}

function ApprovalBody({ approval, state, now, focused, selected, place }: { approval: ApprovalView; state: SessionState; now: number; focused: boolean; selected: number; place: string }) {
  if (approval.folder) {
    return <FolderBody approval={approval} state={state} now={now} focused={focused} selected={selected} place={place} />;
  }
  const call = approval.call;
  const seconds = Math.max(0, Math.round((Date.parse(approval.timeout_at) - now) / 1000));
  const origin = approval.provenance.origin === "proposal" ? "via proposal" : "direct";
  const pattern = approval.suggested_patterns[0];
  const what = call.name === "bash" ? call.subject : `${call.name} ${call.subject}`.trim();
  const meaning = [
    "run it this once",
    pattern ? `allow ${pattern} for the session` : "allow it for the session",
    "refuse this call",
    "refuse this kind of call",
  ];
  const risk = call.risk === "exec" ? theme.danger : call.risk === "write" ? theme.warn : theme.dim;
  return (
    <>
      <text wrapMode="word">
        <b>Approve </b>
        <span fg={theme.warn}>
          <b>{what}</b>
        </span>
        <b>?</b>
        {"  "}
        {APPROVAL_DECISIONS.map((decision, index) => (
          <span key={decision}>
            {index > 0 ? "  " : ""}
            {focused && index === selected ? (
              <span fg={theme.bg} bg={theme.text}>
                {` ${decision} `}
              </span>
            ) : (
              <span fg={focused ? theme.text : theme.dim}>{decision}</span>
            )}
          </span>
        ))}
      </text>
      {(approval.warnings ?? []).map((warning) => (
        <text key={warning} fg={theme.warn}>
          ⚠ {warning}
        </text>
      ))}
      <text fg={theme.dim}>
        {focused ? `←/→ choose · enter confirm · ${meaning[selected] ?? ""}` : "tab to answer"}
      </text>
      <text fg={theme.dim}>
        <span fg={risk}>{call.risk}</span>
        {` · ${from(state, approval.provenance.initiator_id)} (${origin}) · expires in ${seconds}s${place ? ` · ${place}` : ""}`}
      </text>
    </>
  );
}

function ProposalBody({ proposal, state, focused }: { proposal: ProposalView; state: SessionState; focused: boolean }) {
  const author = state.participants[proposal.author_id];
  return (
    <>
      <text>
        <span fg={colorFor(proposal.author_id)}>
          <b>{from(state, proposal.author_id)}</b>
        </span>
        <span fg={theme.dim}> {author?.role ?? ""} proposes</span>
      </text>
      <text>{proposal.text}</text>
      {focused ? (
        <Keys items={[["y", "approve"], ["e", "edit first"], ["n", "reject"]]} />
      ) : (
        <text fg={theme.dim}>tab to answer</text>
      )}
    </>
  );
}

function PlanBody({ focused }: { focused: boolean }) {
  return (
    <>
      <text>The agent finished planning. Start the work?</text>
      {focused ? (
        <Keys items={[["a", "yes, auto mode"], ["e", "yes, accept edits"], ["y", "yes, ask before changes"], ["n", "keep planning"]]} />
      ) : (
        <text fg={theme.dim}>tab to answer</text>
      )}
    </>
  );
}
