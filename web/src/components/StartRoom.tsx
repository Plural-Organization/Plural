import { Alert, Button, Card, Chip, Description, Disclosure, Input, Label, ListBox, Select, Spinner, Tabs, TextField, type Key } from "@heroui/react";
import { ArrowLeft, Folder, FolderOpen } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { parseLink, type JoinLink } from "@plural/client";
import { useAgentSetup } from "../hooks/useAgentSetup";
import { useDaemon } from "../hooks/useDaemon";
import type { Account } from "../lib/accounts";
import { saveAgent } from "../lib/agent";
import { daemonPrompt, manualSteps } from "../lib/agentPrompt";
import { type ComputerTeam, computerTeams, DaemonError, daemonMessage, type PickedFolder, pickFolder, relayProblem, roomDefaults, startRoom } from "../lib/daemon";
import { AgentCard } from "./AgentCard";
import { CopyBox } from "./CopyBox";

interface StartRoomProps {
  account: Account;
  onBack: () => void;
  onOpen: (link: JoinLink, name: string) => void;
  // A team to show the room to from the start, when the person began from that team.
  team?: string | null;
}

// Shown while no Plural answers on this computer. The agent does everything, or the person runs three
// commands; either way the page notices the daemon on its own.
function Setup({ unlinked }: { unlinked: boolean }) {
  return (
    <div className="flex flex-col gap-3">
      <p className="text-[15px] font-medium">{unlinked ? "Plural is running, but not signed in." : "Plural is not running on this computer yet."}</p>
      <Tabs defaultSelectedKey="agent">
        <Tabs.ListContainer>
          <Tabs.List aria-label="How to set Plural up">
            <Tabs.Tab id="agent">
              Let my agent do it
              <Tabs.Indicator />
            </Tabs.Tab>
            <Tabs.Tab id="self">
              I&apos;ll do it myself
              <Tabs.Indicator />
            </Tabs.Tab>
          </Tabs.List>
        </Tabs.ListContainer>
        <Tabs.Panel id="agent" className="flex flex-col gap-2.5 px-0! pb-0! pt-3">
          <CopyBox text={daemonPrompt()} label="Copy the prompt" multiline />
          <Description>Paste it into Claude Code, Codex, Cursor or another agent that can run commands. It installs Plural and signs in, and tells you the two things only you can do.</Description>
        </Tabs.Panel>
        <Tabs.Panel id="self" className="flex flex-col gap-2.5 px-0! pb-0! pt-3">
          <ol className="flex flex-col gap-3">
            {(unlinked ? manualSteps().slice(1) : manualSteps()).map((step, index) => (
              <li key={step.command} className="flex flex-col gap-1.5">
                <span className="text-sm text-muted">{unlinked ? step.title : `${index + 1}. ${step.title}`}</span>
                <CopyBox text={step.command} label={`Copy: ${step.command}`} />
              </li>
            ))}
          </ol>
          <Description>Run these in a terminal, one after another (macOS and Linux). Signing in opens your browser to approve this computer and starts Plural in the background; when your browser asks to access the local network, choose Allow.</Description>
        </Tabs.Panel>
      </Tabs>
      <p className="flex items-center gap-2 text-sm text-muted">
        <Spinner size="sm" color="current" />
        Waiting for Plural on this computer…
      </p>
      <Description>Still not found after signing in? Run <code>plural daemon</code> in a terminal and leave it open.</Description>
    </div>
  );
}

// Start a room on this computer from the page: the folder comes from the system's own dialog.
export function StartRoom({ account, onBack, onOpen, team = null }: StartRoomProps) {
  const { phase, stuck, check } = useDaemon(true);
  const agent = useAgentSetup(phase === "ready");
  const [relay, setRelay] = useState<string | null>(null);
  const relayWrong = relay === null ? null : relayProblem(relay);
  // Who sees the room: only the people invited (null), or one of this computer's teams.
  const [teams, setTeams] = useState<ComputerTeam[]>([]);
  const [showTo, setShowTo] = useState<string | null>(null);

  useEffect(() => {
    if (phase !== "ready") return;
    let alive = true;
    computerTeams()
      .then((found) => {
        if (!alive) return;
        setTeams(found ?? []);
        // Started from a team: show the room to it, as long as this computer knows the team.
        if (team !== null && (found ?? []).some((item) => item.id === team)) setShowTo((chosen) => chosen ?? team);
      })
      .catch(() => alive && setTeams([]));
    return () => {
      alive = false;
    };
  }, [phase]);

  // The relay this computer already uses, so a self-hosted relay is kept without typing it again.
  useEffect(() => {
    if (phase !== "ready" || relay !== null) return;
    roomDefaults()
      .then((found) => setRelay(found.relay))
      .catch(() => setRelay(""));
  }, [phase, relay]);
  const [folder, setFolder] = useState<PickedFolder | null>(null);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState<"folder" | "room" | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const fail = (error: unknown) => {
    setProblem(error instanceof DaemonError ? daemonMessage(error, account.email) : "Something went wrong. Try again.");
    if (error instanceof DaemonError && (error.code === "unreachable" || error.code === "not_linked")) {
      check();
    }
  };

  const choose = () => {
    setProblem(null);
    setBusy("folder");
    pickFolder()
      .then((picked) => picked !== null && setFolder(picked))
      .catch(fail)
      .finally(() => setBusy(null));
  };

  const start = () => {
    if (folder === null) {
      return;
    }
    setProblem(null);
    setBusy("room");
    // An outdated daemon starts the room with the agent it is set to, as before agent setup.
    (agent.outdated ? Promise.resolve(undefined) : agent.commit().then(async (choice) => {
      await saveAgent(choice);
      return choice;
    }))
      .then((choice) => startRoom(folder.folder, title, { ...(choice === undefined ? {} : { agent: choice }), ...(relay === null || agent.outdated ? {} : { relay }), ...(showTo === null || agent.outdated ? {} : { team: showTo }) }))
      .then((room) => onOpen(parseLink(room.host_link), account.name !== "" ? account.name : (account.email.split("@")[0] ?? "host")))
      .catch((error: unknown) => {
        if (error instanceof Error && !(error instanceof DaemonError)) {
          setProblem(error.message);
        } else {
          fail(error);
        }
        setBusy(null);
      });
  };

  return (
    <div className="enter flex flex-col gap-4">
      <Button variant="ghost" size="sm" className="-ml-2 self-start" onPress={onBack}>
        <ArrowLeft size={15} />
        Back
      </Button>
      <div>
        <h2 className="text-2xl font-medium tracking-[-0.02em]">Start a room</h2>
        <p className="mt-1.5 text-[15px] leading-relaxed text-muted text-pretty">
          A room runs on your computer, with your agent, in a folder you choose.
        </p>
      </div>

      {phase === "ready" ? (
        <div className="flex flex-col gap-4">
          <Chip color="success" variant="soft" className="self-start">
            <Chip.Label>Plural is running on this computer</Chip.Label>
          </Chip>
          <Card variant="secondary">
            <Card.Content className="flex-row items-center gap-3">
              {folder === null ? <Folder size={20} className="flex-none text-muted" /> : <FolderOpen size={20} weight="fill" className="flex-none" />}
              <div className="min-w-0 flex-1">
                <p className="truncate text-[15px] font-medium">{folder === null ? "No folder chosen" : folder.name}</p>
                <Description>The agent works only inside {folder === null ? "the folder you choose" : "this folder"}.</Description>
              </div>
              <Button size="sm" variant="secondary" onPress={choose} isDisabled={busy !== null}>
                {busy === "folder" ? <Spinner size="sm" color="current" /> : null}
                {folder === null ? "Choose folder" : "Change"}
              </Button>
            </Card.Content>
          </Card>
          <AgentCard setup={agent} />
          <TextField value={title} onChange={setTitle} name="title">
            <Label>Room name</Label>
            <Input placeholder="Optional" maxLength={80} autoComplete="off" />
            <Description>Shown to the people you invite.</Description>
          </TextField>
          {teams.length === 0 ? null : (
            <Select value={showTo ?? "invited"} onChange={(value) => setShowTo(String(value as Key) === "invited" ? null : String(value as Key))}>
              <Label>Show to</Label>
              <Select.Trigger>
                <Select.Value />
                <Select.Indicator />
              </Select.Trigger>
              <Select.Popover>
                <ListBox>
                  <ListBox.Item id="invited" textValue="Only people I invite">
                    Only people I invite
                    <ListBox.ItemIndicator />
                  </ListBox.Item>
                  {teams.map((item) => (
                    <ListBox.Item key={item.id} id={item.id} textValue={item.name}>
                      {item.name}
                      <ListBox.ItemIndicator />
                    </ListBox.Item>
                  ))}
                </ListBox>
              </Select.Popover>
              <Description>{showTo === null ? "People join with the room link, and you let them in." : "Your team sees the room in its list and can open it to read along."}</Description>
            </Select>
          )}
          {agent.outdated || showTo !== null ? null : (
          <Disclosure>
            <Disclosure.Heading>
              <Disclosure.Trigger className="flex w-full items-center justify-between gap-3 text-sm text-muted">
                <span className="min-w-0 truncate">Relay: {relay === null || relay.trim() === "" ? "the Plural relay" : relay.trim()}</span>
                <Disclosure.Indicator />
              </Disclosure.Trigger>
            </Disclosure.Heading>
            <Disclosure.Content>
              <Disclosure.Body className="pt-2">
                <TextField value={relay ?? ""} onChange={setRelay} name="relay" isInvalid={relayWrong !== null}>
                  <Label>Relay</Label>
                  <Input placeholder="The Plural relay" autoComplete="off" spellCheck={false} />
                  <Description className={relayWrong === null ? undefined : "text-danger"}>
                    {relayWrong ?? "Empty for the Plural relay, or your own, like wss://relay.example.com. This computer remembers it."}
                  </Description>
                </TextField>
              </Disclosure.Body>
            </Disclosure.Content>
          </Disclosure>
          )}
          {problem === null ? null : (
            <Alert status="danger">
              <Alert.Indicator />
              <Alert.Content>
                <Alert.Description>{problem}</Alert.Description>
              </Alert.Content>
            </Alert>
          )}
          <Button fullWidth size="lg" onPress={start} isDisabled={folder === null || busy !== null || (!agent.outdated && agent.blocker !== null) || relayWrong !== null}>
            {busy === "room" ? "Starting…" : "Start room"}
          </Button>
        </div>
      ) : phase === "checking" ? (
        <div className="flex flex-col gap-2">
          <p className="flex items-center gap-2 text-sm text-muted">
            <Spinner size="sm" color="current" />
            Looking for Plural on this computer…
          </p>
          {stuck ? (
            <Alert status="warning">
              <Alert.Indicator />
              <Alert.Content>
                <Alert.Title>Your browser may be waiting for you</Alert.Title>
                <Alert.Description>Look near the address bar: when it asks to access the local network (devices on your network), choose Allow. Plural talks only to your own computer. Nothing happens? Reload the page.</Alert.Description>
              </Alert.Content>
            </Alert>
          ) : null}
        </div>
      ) : (
        <Setup unlinked={phase === "unlinked"} />
      )}
    </div>
  );
}
