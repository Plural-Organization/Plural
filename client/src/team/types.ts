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
