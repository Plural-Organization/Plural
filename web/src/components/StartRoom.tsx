import { Button, Description, Input, Label, Spinner, TextField } from "@heroui/react";
import { ArrowLeft, Folder, FolderOpen } from "@phosphor-icons/react";
import { useState } from "react";
import { parseLink, type JoinLink } from "@plural/client";
import { useDaemon } from "../hooks/useDaemon";
import type { Account } from "../lib/accounts";
import { DaemonError, daemonMessage, type PickedFolder, pickFolder, startRoom } from "../lib/daemon";
import { INSTALL } from "../lib/install";
import { CopyBox } from "./CopyBox";

interface StartRoomProps {
  account: Account;
  onBack: () => void;
  onOpen: (link: JoinLink, name: string) => void;
}

function Steps({ unlinked }: { unlinked: boolean }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-2xl border border-border bg-background p-4">
        <p className="text-[15px] font-medium">{unlinked ? "Plural is running, but not signed in" : "Plural is not running on this computer"}</p>
        <p className="mt-1 text-sm leading-relaxed text-muted text-pretty">
          {unlinked ? "Link it to your account, then this page picks it up on its own." : "Start it once and this page picks it up on its own."}
        </p>
      </div>
      {unlinked ? null : (
        <section className="flex flex-col gap-2">
          <h3 className="text-[15px] font-medium">1. Install Plural</h3>
          <CopyBox text={INSTALL} label="Copy the install command" />
        </section>
      )}
      <section className="flex flex-col gap-2">
        <h3 className="text-[15px] font-medium">{unlinked ? "1" : "2"}. Sign in from the terminal</h3>
        <CopyBox text="plural login" label="Copy the login command" />
        <p className="text-sm text-muted">It opens your browser to approve this computer.</p>
      </section>
      {unlinked ? null : (
        <section className="flex flex-col gap-2">
          <h3 className="text-[15px] font-medium">3. Let this page start rooms</h3>
          <CopyBox text="plural daemon" label="Copy the daemon command" />
          <p className="text-sm leading-relaxed text-muted text-pretty">
            Your browser will ask to access your local network. Choose <strong className="font-medium text-foreground">Allow</strong>: that is how this page talks to Plural on your own computer, and to nothing else.
          </p>
        </section>
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
    startRoom(folder.folder, title)
      .then((room) => onOpen(parseLink(room.host_link), account.name !== "" ? account.name : account.email.split("@")[0] ?? "host"))
      .catch((error: unknown) => {
        fail(error);
        setBusy(null);
      });
  };

  return (
    <div className="enter flex flex-col gap-4">
      <button type="button" className="link-button -ml-1 self-start" onClick={onBack}>
        <ArrowLeft size={14} /> Back
      </button>
      <div>
        <h2 className="text-2xl font-medium tracking-[-0.02em]">Start a room</h2>
        <p className="mt-1.5 text-[15px] leading-relaxed text-muted text-pretty">
          A room runs on your computer, with your agent and your key, in a folder you choose. Only people you let in can join.
        </p>
      </div>

      {phase === "ready" ? (
        <div className="flex flex-col gap-4">
          <p className="flex items-center gap-2 text-sm text-success">
            <span className="size-2 rounded-full bg-success" aria-hidden="true" />
            Plural is running on this computer
          </p>
          <div className="flex items-center gap-3 rounded-2xl border border-border bg-background px-3.5 py-3">
            {folder === null ? <Folder size={20} className="flex-none text-muted" /> : <FolderOpen size={20} weight="fill" className="flex-none" />}
            <div className="min-w-0 flex-1">
              <p className="truncate text-[15px] font-medium">{folder === null ? "No folder chosen" : folder.name}</p>
              <p className="text-sm text-muted">{folder === null ? "The agent works only inside it." : "The agent works only inside this folder."}</p>
            </div>
            <Button size="sm" variant="secondary" onPress={choose} isDisabled={busy !== null}>
              {busy === "folder" ? <Spinner size="sm" color="current" /> : null}
              {folder === null ? "Choose folder" : "Change"}
            </Button>
          </div>
          <TextField value={title} onChange={setTitle} name="title">
            <Label>Room name</Label>
            <Input placeholder="Optional" maxLength={80} autoComplete="off" />
            <Description>Shown to the people you invite.</Description>
          </TextField>
          {problem === null ? null : <p className="text-sm text-danger">{problem}</p>}
          <Button fullWidth size="lg" onPress={start} isDisabled={folder === null || busy !== null}>
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
