import { useCallback, useEffect, useMemo, useState } from "react";
import type { MemberView, SessionCard, TeamInvite, TeamProfile } from "@plural/client";
import {
  accountTeams,
  createTeam,
  createTeamInvite,
  currentTeam,
  disbandTeam,
  fetchMembers,
  fetchSessions,
  forgetTeam,
  handOver,
  joinTeam,
  leaveTeam,
  loadTeams,
  mergeTeams,
  rememberCurrent,
  removeMember,
  renewIfDue,
  TEAM_RELAY,
  type Team,
} from "../lib/team";

// As in the terminal's side panel, the team's sessions are asked for every few seconds.
const REFRESH_MS = 5000;

export interface TeamState {
  // The team the rail shows, or null for the rooms joined by link.
  team: Team | null;
  teams: Team[];
  // True while the browser still reads its teams.
  loading: boolean;
  sessions: SessionCard[];
  error: string | null;
  select: (teamId: string | null) => void;
  // The new team's profile, and its invite code to share once.
  create: (name: string, memberName: string) => Promise<{ profile: TeamProfile; invite: string | null }>;
  join: (invite: TeamInvite, name: string) => Promise<void>;
  invite: () => Promise<{ code: string; expires_at: string | null }>;
  members: () => Promise<MemberView[]>;
  remove: (member: string) => Promise<void>;
  handOver: (member: string) => Promise<void>;
  leave: () => Promise<void>;
  disband: () => Promise<void>;
}

const messageOf = (error: unknown) => (error instanceof Error ? error.message : String(error));

// The teams of this browser and of the signed-in account, and the sessions of the one in view.
export function useTeam(signedIn: boolean): TeamState {
  const [teams, setTeams] = useState<Team[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [sessions, setSessions] = useState<SessionCard[]>([]);
  const [error, setError] = useState<string | null>(null);

  const team = useMemo(() => teams.find((item) => item.profile.team_id === currentId) ?? null, [teams, currentId]);

  const select = useCallback((teamId: string | null) => {
    setCurrentId(teamId);
    setSessions([]);
    void rememberCurrent(teamId);
  }, []);

  // What this browser kept, then what the account has on the relays it knows.
  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const stored = await Promise.all((await loadTeams()).map((item) => renewIfDue(item).catch(() => item)));
        const remembered = await currentTeam();
        if (!alive) return;
        setTeams(stored);
        setCurrentId(remembered ?? stored[0]?.profile.team_id ?? null);
        if (signedIn) {
          const relays = [TEAM_RELAY, ...stored.map((item) => item.profile.relay)];
          const { teams: fresh } = await accountTeams(relays);
          if (!alive) return;
          setTeams((before) => mergeTeams(before, fresh));
          setCurrentId((before) => before ?? fresh[0]?.profile.team_id ?? null);
        }
      } catch (problem) {
        if (alive) setError(messageOf(problem));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [signedIn]);

  useEffect(() => {
    if (team === null) {
      setSessions([]);
      return;
    }
    let alive = true;
    let busy = false;
    const refresh = async () => {
      if (busy) return;
      busy = true;
      try {
        // A tab left open renews the certificate too; a renewed team starts this over.
        const current = await renewIfDue(team).catch(() => team);
        if (current !== team) {
          if (alive) setTeams((before) => mergeTeams(before, [current]));
          return;
        }
        const next = await fetchSessions(team);
        if (alive) {
          setSessions(next);
          setError(null);
        }
      } catch (problem) {
        if (alive) setError(messageOf(problem));
      } finally {
        busy = false;
      }
    };
    void refresh();
    const timer = setInterval(() => void refresh(), REFRESH_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [team]);

  const need = useCallback((): Team => {
    if (team === null) throw new Error("choose a team first");
    return team;
  }, [team]);

  // A team that is gone for this browser, whatever the relay said.
  const drop = useCallback(
    (gone: Team) => {
      setTeams((before) => before.filter((item) => item.profile.team_id !== gone.profile.team_id));
      if (currentId === gone.profile.team_id) select(null);
    },
    [currentId, select],
  );

  // Stable while the team in view is the same, so a window can read the members once per team.
  const members = useCallback(() => fetchMembers(need()), [need]);

  return {
    team,
    teams,
    loading,
    sessions,
    error,
    select,
    create: async (name, memberName) => {
      const made = await createTeam(TEAM_RELAY, name, memberName, signedIn);
      setTeams((before) => mergeTeams(before, [made.team]));
      select(made.team.profile.team_id);
      setError(null);
      return { profile: made.team.profile, invite: made.invite };
    },
    join: async (invite, name) => {
      const joined = await joinTeam(invite, name, signedIn);
      setTeams((before) => mergeTeams(before, [joined]));
      select(joined.profile.team_id);
      setError(null);
    },
    invite: () => createTeamInvite(need()),
    members,
    remove: (member) => removeMember(need(), member),
    handOver: async (member) => {
      const current = need();
      await handOver(current, member);
      // The certificate still says owner until renewed; the rail should not offer owner actions.
      setTeams((before) => mergeTeams(before, [{ ...current, profile: { ...current.profile, member: { ...current.profile.member, role: "member" } } }]));
    },
    leave: async () => {
      const current = need();
      try {
        await leaveTeam(current);
        setError(null);
      } catch (problem) {
        // A team that is gone, or a member already removed, is left here all the same.
        await forgetTeam(current.profile.team_id).catch(() => undefined);
        setError(`left ${current.profile.team_name} here, but the relay did not hear it: ${messageOf(problem)}`);
      }
      drop(current);
    },
    disband: async () => {
      const current = need();
      await disbandTeam(current);
      drop(current);
    },
  };
}
