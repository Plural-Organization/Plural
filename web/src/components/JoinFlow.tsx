import { Button, Description, FieldError, Input, Label, Separator, TextField } from "@heroui/react";
import { ArrowLeft, Copy, GithubLogo, GoogleLogo } from "@phosphor-icons/react";
import { useState, type FormEvent } from "react";
import { parseLink, parseTeamInvite, type JoinLink, type TeamInvite } from "@plural/client";
import type { TeamState } from "../hooks/useTeam";
import { copyText } from "../lib/clipboard";
import { blockedByMixedContent, hostOf, unwrapLink } from "../lib/links";
import { rememberName, savedName } from "../lib/saved";

const INSTALL = "curl -fsSL https://raw.githubusercontent.com/Plural-Organization/Plural/main/install.sh | sh";
// A team member's name: what teammates see and @name uses.
const MEMBER_NAME = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$/;

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
  onJoin: (link: JoinLink, name: string) => void;
  onTeamJoined: () => void;
}

export function JoinFlow({ team, onJoin, onTeamJoined }: JoinFlowProps) {
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

  const clearUrl = () => window.history.replaceState(null, "", window.location.pathname);

  const proceed = (event: FormEvent) => {
    event.preventDefault();
    const read = readShared(raw);
    if ("problem" in read) {
      setProblem(read.problem);
      return;
    }
    if (read.target.kind === "team" && team.team !== null) {
      setProblem(`This browser is already in ${team.team.profile.team_name}. Leave it first to join another team.`);
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
    if (!MEMBER_NAME.test(chosen)) {
      setProblem("Use 1 to 32 letters, digits, dots, dashes or underscores, starting with a letter or digit.");
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

  const back = (
    <Button
      variant="ghost"
      size="sm"
      className="-ml-2 self-start"
      onPress={() => {
        setTarget(null);
        setStarting(false);
        setProblem(null);
      }}
    >
      <ArrowLeft size={15} />
      Back
    </Button>
  );

  if (starting) {
    return (
      <div className="enter flex flex-col gap-4">
        {back}
        <div>
          <h2 className="text-2xl font-medium tracking-[-0.02em]">Start a room</h2>
          <p className="mt-1.5 text-[15px] leading-relaxed text-muted text-pretty">
            A room runs on your machine, with your agent and your key. Install Plural, then run <code>plural</code> in your project. The first line it prints is the link to share.
          </p>
        </div>
        <div className="flex items-center gap-2 rounded-2xl border border-border bg-background py-1.5 pr-1.5 pl-4">
          <code className="min-w-0 flex-1 truncate bg-transparent p-0 font-mono text-[13px]">{INSTALL}</code>
          <Button
            size="sm"
            variant="secondary"
            onPress={() => {
              void copyText(INSTALL).then((ok) => setCopied(ok));
            }}
          >
            <Copy size={15} />
            {copied ? "Copied" : "Copy"}
          </Button>
        </div>
        <p className="text-sm text-muted">Signing in with Google or GitHub is not connected yet.</p>
      </div>
    );
  }

  if (target !== null) {
    const isTeam = target.kind === "team";
    return (
      <form className="enter flex flex-col gap-4" onSubmit={enter}>
        {back}
        <div>
          <h2 className="text-2xl font-medium tracking-[-0.02em]">{isTeam ? "Join the team" : "Join the room"}</h2>
          <p className="mt-1.5 truncate font-mono text-[13px] text-muted">
            {isTeam ? hostOfRelay(target.invite.relay) : `${target.link.room} on ${hostOf(target.link.url)}`}
          </p>
        </div>
        <TextField value={name} onChange={(value) => { setName(value); setProblem(null); }} isInvalid={problem !== null} autoFocus name="name">
          <Label>Your name</Label>
          <Input placeholder="alia" maxLength={isTeam ? 32 : 40} autoComplete="nickname" />
          {isTeam ? <Description>What teammates see and @name uses.</Description> : <Description>The host sees it and lets you in.</Description>}
          {problem !== null ? <FieldError>{problem}</FieldError> : null}
        </TextField>
        <Button type="submit" fullWidth size="lg" isDisabled={busy || name.trim() === ""}>
          {busy ? "Joining…" : isTeam ? "Join the team" : "Ask to join"}
        </Button>
      </form>
    );
  }

  return (
    <div className="enter flex flex-col gap-5">
      <form className="flex flex-col gap-3" onSubmit={proceed}>
        <TextField value={raw} onChange={(value) => { setRaw(value); setProblem(null); }} isInvalid={problem !== null} name="shared" aria-label="Room link or team invite">
          <Input placeholder="Paste a room link or team invite" spellCheck={false} autoComplete="off" className="h-12" />
          {problem !== null ? <FieldError>{problem}</FieldError> : null}
        </TextField>
        <Button type="submit" fullWidth size="lg">Continue</Button>
      </form>
      <div className="flex items-center gap-3 text-sm text-muted">
        <Separator className="flex-1" />
        or start your own
        <Separator className="flex-1" />
      </div>
      <div className="flex flex-col gap-2.5">
        <Button variant="tertiary" fullWidth size="lg" onPress={() => setStarting(true)}>
          <GoogleLogo size={18} weight="bold" />
          Continue with Google
        </Button>
        <Button variant="tertiary" fullWidth size="lg" onPress={() => setStarting(true)}>
          <GithubLogo size={18} weight="fill" />
          Continue with GitHub
        </Button>
      </div>
    </div>
  );
}

function hostOfRelay(relay: string): string {
  return `Team on ${hostOf(relay)}`;
}
