import { ArrowLeft, Copy, GithubLogo, GoogleLogo } from "@phosphor-icons/react";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { parseLink, parseTeamInvite, type JoinLink, type TeamInvite } from "@plural/client";
import type { AccountState } from "../hooks/useAccount";
import type { TeamState } from "../hooks/useTeam";
import { memberNameProblem } from "../lib/teamNames";
import { signInUrl } from "../lib/accounts";
import { StartRoom } from "./StartRoom";
import { PersonAvatar } from "./PersonAvatar";
import { copyText } from "../lib/clipboard";
import { blockedByMixedContent, hostOf, unwrapLink } from "../lib/links";
import { rememberName, savedName } from "../lib/saved";
import { INSTALL } from "../lib/install";
import { ROOM_ART, TEAM_ART } from "../lib/pixelArt";

type Target = { kind: "room"; link: JoinLink } | { kind: "team"; invite: TeamInvite };
type Read = { target: Target } | { problem: string };

// One field takes whatever was shared: a room link, a team invite, or the command around either.
function readShared(raw: string): Read {
  const text = raw.trim();
  if (text === "") {
    return { problem: "Paste the link or invite someone shared with you." };
  }
  const invite = parseTeamInvite(text);
  if (invite !== null) {
    return blockedByMixedContent(invite.relay, window.location.protocol)
      ? { problem: "This page is served over https, so the browser cannot reach a team relay at ws://." }
      : { target: { kind: "team", invite } };
  }
  const unwrapped = unwrapLink(text);
  if (blockedByMixedContent(unwrapped, window.location.protocol)) {
    return { problem: "This page is served over https, so the browser blocks plain ws:// links. Ask the host to share the room through a relay." };
  }
  try {
    const link = parseLink(unwrapped);
    return link.invite === null && link.token === null && link.join === null
      ? { problem: "This link has no room code. Copy the whole line the host shared." }
      : { target: { kind: "room", link } };
  } catch {
    return { problem: "That doesn't look like a room link or a team invite." };
  }
}

function sharedOnLoad(): string {
  const query = new URLSearchParams(window.location.search).get("join");
  if (query !== null) {
    return query;
  }
  return parseTeamInvite(window.location.href) === null ? "" : window.location.href;
}

interface JoinFlowProps {
  team: TeamState;
  account: AccountState;
  onJoin: (link: JoinLink, name: string) => void;
  onTeamJoined: () => void;
  // Told when the person moves into a step (starting, or joining what they pasted) and back, so the
  // page around can step aside.
  onStep?: (inStep: boolean) => void;
  // Offered next to Start a room on the first page; left out where a team is already open.
  onCreateTeam?: () => void;
}

export function JoinFlow({ team, account, onJoin, onTeamJoined, onStep, onCreateTeam }: JoinFlowProps) {
  const [raw, setRaw] = useState(sharedOnLoad);
  const [target, setTarget] = useState<Target | null>(() => {
    const shared = sharedOnLoad();
    if (shared === "") {
      return null;
    }
    const read = readShared(shared);
    return "target" in read ? read.target : null;
  });
  const [starting, setStarting] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [name, setName] = useState(savedName);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const inStep = starting || target !== null;
  useEffect(() => onStep?.(inStep), [inStep, onStep]);

  const clearUrl = () => window.history.replaceState(null, "", window.location.pathname);

  const proceed = (event: FormEvent) => {
    event.preventDefault();
    const read = readShared(raw);
    if ("problem" in read) {
      setProblem(read.problem);
      return;
    }
    setProblem(null);
    setTarget(read.target);
  };

  const enter = (event: FormEvent) => {
    event.preventDefault();
    const chosen = name.trim();
    if (target === null) {
      return;
    }
    if (target.kind === "room") {
      if (chosen === "") {
        setProblem("Type the name the room will see.");
        return;
      }
      rememberName(chosen);
      clearUrl();
      onJoin(target.link, chosen);
      return;
    }
    const wrongName = memberNameProblem(chosen);
    if (wrongName !== null) {
      setProblem(wrongName);
      return;
    }
    setBusy(true);
    setProblem(null);
    team
      .join(target.invite, chosen)
      .then(() => {
        rememberName(chosen);
        clearUrl();
        onTeamJoined();
      })
      .catch((error: unknown) => setProblem(error instanceof Error ? error.message : String(error)))
      .finally(() => setBusy(false));
  };

  const leave = () => {
    setTarget(null);
    setStarting(false);
    setProblem(null);
  };
  const back = (
    <button type="button" className="pl-back" onClick={leave}>
      <ArrowLeft size={15} aria-hidden="true" />
      Back
    </button>
  );

  if (starting && account.status === "in" && account.account !== null) {
    return <StartRoom account={account.account} onBack={() => setStarting(false)} onOpen={onJoin} />;
  }

  // Starting needs an account, so this page can reach Plural on the person's computer: sign in first.
  if (starting && account.enabled) {
    const here = `${window.location.origin}${window.location.pathname}`;
    return (
      <div className="pl-step">
        {back}
        <img src={ROOM_ART} alt="" className="pl-step-art" />
        <div className="flex flex-col gap-2">
          <h1 className="pl-step-title">Start a room</h1>
          <p className="pl-step-text">Sign in so this page can set up the room on your computer.</p>
        </div>
        <div className="flex flex-col gap-2.5">
          <button type="button" className="pl-pill pl-pill-primary pl-pill-tall w-full" disabled={account.status === "loading"} onClick={() => window.location.assign(signInUrl(here))}>
            <GoogleLogo size={18} weight="bold" aria-hidden="true" />
            Continue with Google
          </button>
          <button type="button" className="pl-pill pl-pill-quiet pl-pill-tall w-full" disabled>
            <GithubLogo size={18} weight="fill" aria-hidden="true" />
            Continue with GitHub
            <span className="pl-soon">Soon</span>
          </button>
        </div>
      </div>
    );
  }

  if (starting) {
    return (
      <div className="pl-step">
        {back}
        <img src={ROOM_ART} alt="" className="pl-step-art" />
        <div className="flex flex-col gap-2">
          <h1 className="pl-step-title">Start a room</h1>
          <p className="pl-step-text">
            A room runs on your machine, with your agent and your key. Install Plural, then run <code>plural</code> in your project. The first line it prints is the link to share.
          </p>
        </div>
        <div className="pl-copy">
          <code className="min-w-0 flex-1 truncate font-mono text-[13px]">{INSTALL}</code>
          <button
            type="button"
            className="pl-pill pl-pill-secondary pl-pill-small"
            onClick={() => {
              void copyText(INSTALL).then((ok) => setCopied(ok));
            }}
          >
            <Copy size={15} aria-hidden="true" />
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      </div>
    );
  }

  if (target !== null) {
    const isTeam = target.kind === "team";
    const where = isTeam ? target.invite.relay : target.link.url;
    return (
      <form className="pl-step" onSubmit={enter}>
        {back}
        <h1 className="pl-step-title">{isTeam ? "Join the team" : "Join the room"}</h1>
        <div className="pl-target">
          <PersonAvatar seed={isTeam ? target.invite.relay : target.link.room} size="md" />
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="font-mono text-[15px] font-medium tracking-[-0.01em] [overflow-wrap:anywhere]">{isTeam ? "Team" : target.link.room}</span>
            <span className="font-mono text-[13px] text-muted [overflow-wrap:anywhere]">on {hostOf(where)}</span>
          </div>
        </div>
        <div className="flex flex-col gap-3">
          <label htmlFor="pl-name" className="pl-label">
            Your name
          </label>
          <input
            id="pl-name"
            className="pl-field"
            value={name}
            onChange={(event) => {
              setName(event.target.value);
              setProblem(null);
            }}
            placeholder={isTeam ? "What teammates see and @name uses" : "How others will see you"}
            maxLength={isTeam ? 32 : 40}
            autoComplete="nickname"
            autoFocus
            aria-invalid={problem !== null}
            aria-describedby={problem !== null ? "pl-name-problem" : undefined}
          />
          {problem !== null ? <Problem id="pl-name-problem">{problem}</Problem> : null}
          <button type="submit" className="pl-pill pl-pill-primary pl-pill-tall w-full" disabled={busy || name.trim() === ""}>
            {busy ? "Joining…" : isTeam ? "Join the team" : "Ask to join"}
          </button>
          <p className="text-center text-[13px] text-muted">{isTeam ? "You join the team on this browser." : "The host lets you in."}</p>
        </div>
      </form>
    );
  }

  return (
    <div className="flex flex-col gap-[clamp(14px,1.2vw,18px)]">
      <div className={onCreateTeam === undefined ? "grid gap-2.5" : "grid grid-cols-2 gap-[clamp(8px,0.9vw,12px)]"}>
        <Choice art={ROOM_ART} artLabel="One computer with the host's agent, people around it" title="One host" detail="Your computer, your agent." action="Start a room" primary onPress={() => setStarting(true)} />
        {onCreateTeam === undefined ? null : (
          <Choice art={TEAM_ART} artLabel="Three people, each at a computer of their own" title="Many hosts" detail="Everyone’s computers, one invite link." action="Create a team" onPress={onCreateTeam} />
        )}
      </div>
      <form className="flex flex-col gap-2.5" onSubmit={proceed} noValidate>
        <label htmlFor="pl-join" className="flex items-center gap-3 text-[13px] font-medium text-muted">
          <span className="whitespace-nowrap">Join with a link</span>
          <span aria-hidden="true" className="h-px flex-1 bg-separator" />
        </label>
        <div className="flex gap-2">
          <input
            id="pl-join"
            className="pl-field min-w-0 flex-1 font-mono text-sm"
            value={raw}
            onChange={(event) => {
              setRaw(event.target.value);
              setProblem(null);
            }}
            placeholder="Paste a room link or team invite"
            spellCheck={false}
            autoComplete="off"
            aria-invalid={problem !== null}
            aria-describedby={problem !== null ? "pl-join-problem" : undefined}
          />
          <button type="submit" className="pl-pill pl-pill-secondary pl-pill-tall shrink-0 px-[22px]">
            Join
          </button>
        </div>
        {problem !== null ? <Problem id="pl-join-problem">{problem}</Problem> : null}
      </form>
    </div>
  );
}

// One of the two ways to make something: what it is in two words, and the button that makes it.
function Choice({ art, artLabel, title, detail, action, primary = false, onPress }: { art: string; artLabel: string; title: string; detail: string; action: string; primary?: boolean; onPress: () => void }) {
  return (
    <div className="pl-tile">
      <div className="flex h-12 items-center">
        <img src={art} alt={artLabel} className="block h-auto max-h-12 w-auto max-w-24" />
      </div>
      <div className="flex flex-1 flex-col gap-1">
        <span className="text-[15px] font-semibold tracking-[-0.005em]">{title}</span>
        <span className="text-[13.5px] leading-[1.4] text-muted text-pretty">{detail}</span>
      </div>
      <button type="button" className={`pl-pill w-full ${primary ? "pl-pill-primary" : "pl-pill-secondary"}`} onClick={onPress}>
        {action}
      </button>
    </div>
  );
}

// A problem said in white with a white mark, as red is not one of the page's colours.
function Problem({ id, children }: { id: string; children: ReactNode }) {
  return (
    <div id={id} role="alert" className="flex items-start gap-2.5 pt-0.5 pr-1 pl-1.5 text-[13.5px] leading-[1.45]">
      <span aria-hidden="true" className="mt-px flex size-[18px] flex-none items-center justify-center rounded-full bg-foreground text-[12px] font-bold text-[#0b0b0d]">!</span>
      <span className="text-pretty">{children}</span>
    </div>
  );
}
