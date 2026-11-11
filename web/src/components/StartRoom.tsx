import { Alert, Button, Card, Chip, Description, Disclosure, Input, Label, Spinner, TextField } from "@heroui/react";
import { ArrowLeft, Folder, FolderOpen } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { parseLink, type JoinLink } from "@plural/client";
import { useAgentSetup } from "../hooks/useAgentSetup";
import { useDaemon } from "../hooks/useDaemon";
import type { Account } from "../lib/accounts";
import { saveAgent } from "../lib/agent";
import { DaemonError, daemonMessage, type PickedFolder, pickFolder, relayProblem, roomDefaults, startRoom } from "../lib/daemon";
import { INSTALL } from "../lib/install";
import { AgentCard } from "./AgentCard";
import { CopyBox } from "./CopyBox";

interface StartRoomProps {
  account: Account;
  onBack: () => void;
  onOpen: (link: JoinLink, name: string) => void;
}

function Step({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card variant="secondary">
      <Card.Header>
        <Card.Title className="text-[15px]">{title}</Card.Title>
      </Card.Header>
      <Card.Content className="gap-2.5">{children}</Card.Content>
    </Card>
  );
}

// Shown while no Plural answers on this computer: what to run, and that the page notices on its own.
function Steps({ unlinked }: { unlinked: boolean }) {
  return (
    <div className="flex flex-col gap-3">
      <Alert status="warning">
        <Alert.Indicator />
        <Alert.Content>
          <Alert.Title>{unlinked ? "Plural is running, but not signed in" : "Plural is not running on this computer"}</Alert.Title>
          <Alert.Description>
            {unlinked ? "Link it to your account and this page picks it up on its own." : "Start it once and this page picks it up on its own."}
          </Alert.Description>
        </Alert.Content>
      </Alert>
      {unlinked ? null : (
        <Step title="1. Install Plural">
          <CopyBox text={INSTALL} label="Copy the install command" />
        </Step>
      )}
      <Step title={`${unlinked ? "1" : "2"}. Sign in from the terminal`}>
        <CopyBox text="plural login" label="Copy the login command" />
        <Description>It opens your browser to approve this computer.</Description>
      </Step>
      {unlinked ? null : (
        <Step title="3. Let this page start rooms">
          <CopyBox text="plural daemon" label="Copy the daemon command" />
          <Description>
            Your browser will ask to access your local network. Choose <strong className="font-medium text-foreground">Allow</strong>: that is how this page talks to Plural on your own computer, and to nothing else.
          </Description>
        </Step>
      )}
      <p className="flex items-center gap-2 text-sm text-muted">
        <Spinner size="sm" color="current" />
        Looking for Plural on this computer…
      </p>
    </div>
  );
}

// Start a room on this computer from the page: the folder comes from the system's own dialog.
export function StartRoom({ account, onBack, onOpen }: StartRoomProps) {
  const { phase, check } = useDaemon(true);
  const agent = useAgentSetup(phase === "ready");
  const [relay, setRelay] = useState<string | null>(null);
  const relayWrong = relay === null ? null : relayProblem(relay);

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
      .then((choice) => startRoom(folder.folder, title, { ...(choice === undefined ? {} : { agent: choice }), ...(relay === null || agent.outdated ? {} : { relay }) }))
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
          A room runs on your computer, with your agent and your key, in a folder you choose. Only people you let in can join.
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
          {agent.outdated ? null : (
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
        <p className="flex items-center gap-2 text-sm text-muted">
          <Spinner size="sm" color="current" />
          Looking for Plural on this computer…
        </p>
      ) : (
        <Steps unlinked={phase === "unlinked"} />
      )}
    </div>
  );
}
