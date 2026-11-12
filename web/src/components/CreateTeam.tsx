import { Alert, Button, Description, Input, Label, Modal, Spinner, TextField } from "@heroui/react";
import { teamJoinLink } from "@plural/client";
import { useState } from "react";
import type { TeamState } from "../hooks/useTeam";
import { memberNameProblem, suggestedName, teamNameProblem } from "../lib/teamNames";
import { CopyBox } from "./CopyBox";

interface CreateTeamProps {
  team: TeamState;
  email: string | null;
  onClose: () => void;
  // Offered once the team exists: the next step is a room in it.
  onStartRoom?: () => void;
}

// A new team in two fields; then the invite link to share, once.
export function CreateTeam({ team, email, onClose, onStartRoom }: CreateTeamProps) {
  const [name, setName] = useState("");
  const [memberName, setMemberName] = useState(() => suggestedName(email));
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [link, setLink] = useState<string | null>(null);

  const create = () => {
    const why = teamNameProblem(name) ?? memberNameProblem(memberName);
    if (why !== null) {
      setProblem(why);
      return;
    }
    setBusy(true);
    setProblem(null);
    team
      .create(name.trim(), memberName.trim())
      .then(({ profile, invite }) => setLink(invite === null ? "" : teamJoinLink(profile, invite, window.location)))
      .catch((error: unknown) => setProblem(error instanceof Error ? error.message : String(error)))
      .finally(() => setBusy(false));
  };

  return (
    <Modal.Backdrop isOpen onOpenChange={(open) => !open && onClose()}>
      <Modal.Container>
        <Modal.Dialog className="sm:max-w-[28rem]">
          <Modal.CloseTrigger />
          <Modal.Header>
            <Modal.Heading className="font-display text-2xl font-medium tracking-[-0.02em]">{link === null ? "Create a team" : "Invite your team"}</Modal.Heading>
          </Modal.Header>
          <Modal.Body className="flex flex-col gap-4">
            {link === null ? (
              <>
                <TextField value={name} onChange={setName} name="team-name" autoFocus>
                  <Label>Team name</Label>
                  <Input placeholder="Backend" maxLength={60} autoComplete="off" />
                </TextField>
                <TextField value={memberName} onChange={setMemberName} name="member-name">
                  <Label>Your name in the team</Label>
                  <Input placeholder="alia" maxLength={32} autoComplete="nickname" />
                  <Description>What teammates see and @name uses.</Description>
                </TextField>
                <Description>{email === null ? "Without signing in, the team lives in this browser only." : `Your other devices signed in as ${email} see this team too.`}</Description>
                {problem === null ? null : (
                  <Alert status="danger">
                    <Alert.Indicator />
                    <Alert.Content>
                      <Alert.Description>{problem}</Alert.Description>
                    </Alert.Content>
                  </Alert>
                )}
              </>
            ) : link === "" ? (
              <Description>The team is ready. Make an invite link from the team's window, or start its first room now.</Description>
            ) : (
              <>
                <CopyBox text={link} label="Copy the invite link" />
                <Description>Anyone with this link can join until you remove them. It does not expire.</Description>
              </>
            )}
          </Modal.Body>
          <Modal.Footer>
            {link === null ? (
              <Button onPress={create} isDisabled={busy}>
                {busy ? <Spinner size="sm" color="current" /> : null}
                Create team
              </Button>
            ) : (
              <>
                <Button slot="close" variant="secondary">Done</Button>
                {onStartRoom === undefined ? null : <Button onPress={onStartRoom}>Start the first room</Button>}
              </>
            )}
          </Modal.Footer>
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
  );
}
