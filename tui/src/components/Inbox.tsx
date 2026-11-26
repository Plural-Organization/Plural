import { approvalChoices, defaultApprovalChoice, participantName as from, type AccessRequestView, type BriefingRequestView, type ApprovalView, type HandoverView, type InboxRequest, type JoinRequestView, type ProposalView, type SessionState } from "@plural/client";
import { colorFor, theme } from "../theme";

// What waits for the host lives in @plural/client, for this client and the web one; the terminal adds a plan that is ready to start.
export type InboxItem = InboxRequest | { kind: "plan"; id: string };

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
  /** The person answering is a participant the host named, not the host: calls only, once or refuse. */
  approver?: boolean;
}

export function Inbox({ items, state, selected, focused, now, approvalChoice, approver = false }: InboxProps) {
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
      borderColor={isFolderRequest(item) ? theme.danger : focused ? theme.warn : theme.line}
      backgroundColor={theme.panel}
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
        <ApprovalBody approver={approver} approval={item.approval} state={state} now={now} focused={focused} selected={approvalChoice?.id === item.id ? approvalChoice.index : defaultApprovalChoice(item.approval)} place={items.length > 1 ? `${index + 1}/${items.length}` : ""} />
      ) : item.kind === "plan" ? (
        <PlanBody focused={focused} />
      ) : item.kind === "handover" ? (
        <HandoverBody offer={item.offer} state={state} focused={focused} />
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
      {request.focus ? <text fg={theme.text}>{request.focus}</text> : null}
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
      {request.note ? <text fg={theme.text}>{request.note}</text> : null}
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
        {approvalChoices(approval).map(({ decision }, index) => (
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

function ApprovalBody({ approver, approval, state, now, focused, selected, place }: { approver: boolean; approval: ApprovalView; state: SessionState; now: number; focused: boolean; selected: number; place: string }) {
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
      <text wrapMode="word" fg={theme.text}>
        <b>Approve </b>
        <span fg={theme.warn}>
          <b>{what}</b>
        </span>
        <b>?</b>
        {"  "}
        {approvalChoices(approval, approver).map(({ decision }, index) => (
          <span key={decision}>
            {index > 0 ? "  " : ""}
            {focused && index === selected ? (
              <span fg={theme.bg} bg={theme.text}>
                <b>{` ${decision} `}</b>
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
      <text fg={theme.text}>{proposal.text}</text>
      {focused ? (
        <Keys items={[["y", "approve"], ["e", "edit first"], ["n", "reject"]]} />
      ) : (
        <text fg={theme.dim}>tab to answer</text>
      )}
    </>
  );
}

function HandoverBody({ offer, state, focused }: { offer: HandoverView; state: SessionState; focused: boolean }) {
  const host = Object.values(state.participants).find((person) => person.role === "host");
  return (
    <>
      <text>
        <span fg={theme.warn}>
          <b>{host?.name ?? "the host"}</b>
        </span>
        <span fg={theme.text}> offers you the host of this room, {offer.name}</span>
      </text>
      <text fg={theme.dim} wrapMode="word">
        The session and its conversation move to this computer, the link stays the same. The agent will work in this folder with your model key, and what it runs, it runs here.
      </text>
      {focused ? <Keys items={[["y", "take it"], ["n", "decline"]]} /> : <text fg={theme.dim}>tab to answer</text>}
    </>
  );
}

function PlanBody({ focused }: { focused: boolean }) {
  return (
    <>
      <text fg={theme.text}>The agent finished planning. Start the work?</text>
      {focused ? (
        <Keys items={[["a", "yes, auto mode"], ["e", "yes, accept edits"], ["y", "yes, ask before changes"], ["n", "keep planning"]]} />
      ) : (
        <text fg={theme.dim}>tab to answer</text>
      )}
    </>
  );
}
