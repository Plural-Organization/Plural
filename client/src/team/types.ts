export type SessionStatus = "idle" | "running" | "waiting";

export interface Conflict {
  owner: string;
  room: string;
  branch: string | null;
  paths: string[];
  same_branch: boolean;
  latest: string;
}

export interface SessionCard {
  room: string;
  repo: string;
  branch: string | null;
  title: string | null;
  status: SessionStatus;
  viewers: number;
  endpoints: { kind: "relay" | "direct"; url: string }[];
  owner: string;
  owner_id: string;
  updated_at: string;
  repo_id?: string | null;
  conflicts?: Conflict[];
  // The agent the session runs, as its host names it; older hosts leave it out.
  agent?: string | null;
}

export interface TeamProfile {
  relay: string;
  team_id: string;
  team_name: string;
  team_key: string;
  certificate: string;
  member: { id: string; name: string; role: string };
}

export interface TeamInvite {
  code: string;
  relay: string;
}

export interface TeamView {
  name: string;
  me: string;
  member: string;
  sessions: SessionCard[];
  error: string | null;
}

// That a device belongs to an account (ADR 0016): a browser sends a ticket for "teams", a computer its
// certificate with a signature over `accountProofMessage(ts, nonce)`.
export interface AccountProof {
  ticket?: string;
  certificate?: string;
  ts?: number;
  nonce?: string;
  signature?: string;
}

export interface MemberView {
  id: string;
  name: string;
  key: string;
  role: "owner" | "member";
  joined_at: string;
}

export interface TeamGrant {
  team_id: string;
  team_name: string;
  team_key: string;
  certificate: string;
  member: MemberView;
  invite?: string | null;
}
