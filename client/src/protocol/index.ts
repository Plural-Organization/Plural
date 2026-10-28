import type { CommandsSchema } from "./commands";
import type { EventsSchema } from "./events";

export type {
  ApprovalDecision,
  ClientInfo,
  ProposalDecision,
} from "./commands";
export type {
  ApprovalRequested,
  ApprovalView,
  AgentView,
  AttachmentMeta,
  BoardCursor,
  BoardShape,
  BoardStroke,
  BoardView,
  ChatEntry,
  JoinRequestView,
  ContextView,
  Envelope,
  ErrorCode,
  ErrorInfo,
  EventRecord,
  JsonValue,
  McpServerView,
  Participant,
  PermissionMode,
  PolicyRuleView,
  PromptMode,
  ProposalView,
  Provenance,
  Role,
  RunEndReason,
  RunView,
  SessionState,
  SkillHit,
  SkillScope,
  SkillView,
  TextSelection,
  ToolCallView,
  TranscriptEntry,
  Usage,
  UsageLine,
} from "./events";

export type Event = EventsSchema["event"];
export type EventType = Event["type"];
export type EventOf<T extends EventType> = Extract<Event, { type: T }>;

type WithType<T> = T extends { type?: infer U } ? Omit<T, "type"> & { type: NonNullable<U> } : never;
export type Command = WithType<CommandsSchema["command"]>;
export type CommandType = Command["type"];
export type CommandOf<T extends CommandType> = Extract<Command, { type: T }>;

export const PROTOCOL_VERSION = 1;
