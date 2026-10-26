import { Box, Text } from "ink";
import { label, type ApprovalView, type ProposalView, type SessionState } from "@plural/client";
import { colorFor, theme } from "../theme";

export type InboxItem =
  | { kind: "approval"; id: string; approval: ApprovalView }
  | { kind: "proposal"; id: string; proposal: ProposalView };

export function inboxItems(state: SessionState): InboxItem[] {
  return [
    ...Object.values(state.approvals).map((approval): InboxItem => ({ kind: "approval", id: approval.id, approval })),
    ...Object.values(state.proposals).map((proposal): InboxItem => ({ kind: "proposal", id: proposal.id, proposal })),
  ];
}

function from(state: SessionState, participantId: string): string {
  const participant = state.participants[participantId];
  return participant ? label(state, participant) : participantId;
}

function Keys({ items }: { items: [string, string][] }) {
  return (
    <Text>
      {items.map(([key, action], index) => (
        <Text key={key}>
          {index > 0 ? "   " : ""}
          <Text color={theme.accent} bold>
            {key}
          </Text>
          <Text color={theme.dim}> {action}</Text>
        </Text>
      ))}
    </Text>
  );
}

interface InboxProps {
  items: InboxItem[];
  state: SessionState;
  selected: number;
  focused: boolean;
  now: number;
}

export function Inbox({ items, state, selected, focused, now }: InboxProps) {
  const item = items[Math.min(selected, items.length - 1)];
  if (!item) {
    return null;
  }
  const border = focused ? theme.warn : theme.dim;
  return (
    <Box flexDirection="column" borderStyle="round" borderColor={border} paddingX={1} marginTop={1}>
      <Text>
        <Text color={theme.warn} bold>
          {item.kind === "approval" ? "approval needed" : "proposal"}
        </Text>
        <Text color={theme.dim}>
          {"  "}
          {Math.min(selected, items.length - 1) + 1}/{items.length}
        </Text>
      </Text>
      {item.kind === "approval" ? (
        <ApprovalBody approval={item.approval} state={state} now={now} focused={focused} />
      ) : (
        <ProposalBody proposal={item.proposal} state={state} focused={focused} />
      )}
    </Box>
  );
}

function ApprovalBody({ approval, state, now, focused }: { approval: ApprovalView; state: SessionState; now: number; focused: boolean }) {
  const call = approval.call;
  const seconds = Math.max(0, Math.round((Date.parse(approval.timeout_at) - now) / 1000));
  const origin = approval.provenance.origin === "proposal" ? "via proposal" : "direct";
  const pattern = approval.suggested_patterns[0];
  return (
    <>
      <Text>
        <Text bold>{call.name}</Text>
        <Text color={call.risk === "exec" ? theme.danger : call.risk === "write" ? theme.warn : theme.dim}> {call.risk}</Text>
        <Text color={theme.dim}>
          {" "}
          · {from(state, approval.provenance.initiator_id)} ({origin}) · expires in {seconds}s
        </Text>
      </Text>
      <Text color={theme.info}>{call.name === "bash" ? `$ ${call.subject}` : call.subject}</Text>
      {focused ? (
        <Keys
          items={[
            ["y", "once"],
            ...(pattern ? ([["a", `always ${pattern}`]] as [string, string][]) : ([["a", "always"]] as [string, string][])),
            ["n", "reject"],
            ["b", "block this kind"],
          ]}
        />
      ) : (
        <Text color={theme.dim}>tab to answer</Text>
      )}
    </>
  );
}

function ProposalBody({ proposal, state, focused }: { proposal: ProposalView; state: SessionState; focused: boolean }) {
  const author = state.participants[proposal.author_id];
  return (
    <>
      <Text>
        <Text color={colorFor(proposal.author_id)} bold>
          {from(state, proposal.author_id)}
        </Text>
        <Text color={theme.dim}> {author?.role ?? ""} proposes</Text>
      </Text>
      <Text>{proposal.text}</Text>
      {focused ? (
        <Keys
          items={[
            ["y", "approve"],
            ["e", "edit first"],
            ["n", "reject"],
          ]}
        />
      ) : (
        <Text color={theme.dim}>tab to answer</Text>
      )}
    </>
  );
}
