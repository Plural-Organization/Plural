import { useEffect, useState } from "react";
import { createTeamInvite, fetchSessions, joinTeam, leaveTeam, forgetTeam, loadTeam, renewIfDue, type SessionCard, type Team, type TeamInvite } from "../lib/team";

// As in the terminal's side panel, the team's sessions are asked for every few seconds.
const REFRESH_MS = 5000;

export interface TeamState {
  team: Team | null;
  // True while the browser still reads its team.
  loading: boolean;
  sessions: SessionCard[];
  error: string | null;
  join: (invite: TeamInvite, name: string) => Promise<void>;
  invite: () => Promise<{ code: string; expires_at: string }>;
  leave: () => Promise<void>;
}

const messageOf = (error: unknown) => (error instanceof Error ? error.message : String(error));

export function useTeam(): TeamState {
  const [team, setTeam] = useState<Team | null>(null);
  const [loading, setLoading] = useState(true);
  const [sessions, setSessions] = useState<SessionCard[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    void loadTeam()
      .then(async (loaded) => (loaded === null ? null : renewIfDue(loaded).catch(() => loaded)))
      .then((loaded) => alive && setTeam(loaded))
      .catch((problem: unknown) => alive && setError(messageOf(problem)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (team === null) {
      setSessions([]);
      return;
    }
    let alive = true;
    let busy = false;
    const refresh = async () => {
      if (busy) {
        return;
      }
      busy = true;
      try {
        // A tab left open renews the certificate too; a renewed team starts this over.
        const current = await renewIfDue(team).catch(() => team);
        if (current !== team) {
          if (alive) {
            setTeam(current);
          }
          return;
        }
        const next = await fetchSessions(team);
        if (alive) {
          setSessions(next);
          setError(null);
        }
      } catch (problem) {
        if (alive) {
          setError(messageOf(problem));
        }
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

  return {
    team,
    loading,
    sessions,
    error,
    join: async (invite, name) => {
      setTeam(await joinTeam(invite, name));
      setError(null);
    },
    invite: () => {
      if (team === null) {
        return Promise.reject(new Error("you are not in a team"));
      }
      return createTeamInvite(team);
    },
    leave: async () => {
      if (team === null) {
        return;
      }
      try {
        await leaveTeam(team);
        setError(null);
      } catch (problem) {
        // A team that is gone, or a member already removed, is left here all the same.
        await forgetTeam().catch(() => undefined);
        setError(`left ${team.profile.team_name} here, but the relay did not hear it: ${messageOf(problem)}`);
      }
      setTeam(null);
    },
  };
}
