import type { SessionCard, TeamProfile, TeamView } from "./types";

export class TeamWatcher {
  private current: TeamView;
  private readonly listeners = new Set<(view: TeamView) => void>();
  private timer: ReturnType<typeof setInterval> | null = null;
  private refreshing = false;

  constructor(
    profile: TeamProfile,
    private readonly load: () => Promise<SessionCard[]>,
    private readonly everyMs = 5000,
  ) {
    this.current = { name: profile.team_name, me: profile.member.id, member: profile.member.name, sessions: [], error: null };
  }

  get view(): TeamView {
    return this.current;
  }

  subscribe(listener: (view: TeamView) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  start(): void {
    if (this.timer !== null) {
      return;
    }
    void this.refresh();
    this.timer = setInterval(() => void this.refresh(), this.everyMs);
  }

  stop(): void {
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  async refresh(): Promise<void> {
    if (this.refreshing) {
      return;
    }
    this.refreshing = true;
    try {
      this.set({ ...this.current, sessions: await this.load(), error: null });
    } catch (error) {
      this.set({ ...this.current, error: error instanceof Error ? error.message : String(error) });
    } finally {
      this.refreshing = false;
    }
  }

  private set(view: TeamView): void {
    this.current = view;
    this.listeners.forEach((listener) => listener(view));
  }
}
