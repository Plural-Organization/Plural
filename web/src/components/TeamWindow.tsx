import { Alert, Button, Chip, Description, Label, ListBox, Modal, Spinner, Tabs } from "@heroui/react";
import { teamJoinLink, type MemberView } from "@plural/client";
import { useEffect, useState } from "react";
import type { TeamState } from "../hooks/useTeam";
import { Confirm } from "./Confirm";
import { CopyBox } from "./CopyBox";
import { PersonAvatar } from "./PersonAvatar";

type Asking = { kind: "remove" | "owner"; member: MemberView } | { kind: "leave" | "disband" } | null;

const words = (error: unknown) => (error instanceof Error ? error.message : String(error));

function Members({ team, members, owner, onAsk }: { team: TeamState; members: MemberView[] | null; owner: boolean; onAsk: (asking: Asking) => void }) {
  const me = team.team?.profile.member.id;
  if (members === null) {
    return (
      <p className="flex items-center gap-2 py-4 text-sm text-muted">
        <Spinner size="sm" color="current" />
        Reading the members…
      </p>
    );
  }
  return (
    <ListBox aria-label="Members" selectionMode="none">
      {members.map((member) => (
        <ListBox.Item key={member.id} id={member.id} textValue={member.name}>
          <PersonAvatar seed={member.name} />
          <div className="flex min-w-0 flex-1 flex-col">
            <Label className="truncate">
              {member.name}
              {member.id === me ? <span className="ml-1.5 font-normal text-muted">you</span> : null}
            </Label>
            <Description>Joined {new Date(member.joined_at).toLocaleDateString()}</Description>
          </div>
          {member.role === "owner" ? (
            <Chip size="sm" variant="soft" color="accent" className="flex-none">
              <Chip.Label>Owner</Chip.Label>
            </Chip>
          ) : owner && member.id !== me ? (
            <span className="flex flex-none gap-1">
              <Button size="sm" variant="ghost" onPress={() => onAsk({ kind: "owner", member })}>
                Make owner
              </Button>
              <Button size="sm" variant="ghost" className="text-danger" onPress={() => onAsk({ kind: "remove", member })}>
                Remove
              </Button>
            </span>
          ) : null}
        </ListBox.Item>
      ))}
    </ListBox>
  );
}

function Invite({ team }: { team: TeamState }) {
  const [link, setLink] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const profile = team.team?.profile ?? null;
  if (profile === null) return null;
  const make = () => {
    setBusy(true);
    setProblem(null);
    team
      .invite()
      .then(({ code }) => setLink(teamJoinLink(profile, code, window.location)))
      .catch((error: unknown) => setProblem(words(error)))
      .finally(() => setBusy(false));
  };
  return (
    <div className="flex flex-col gap-3">
      {link === null ? null : <CopyBox text={link} label="Copy the invite link" />}
      <Description>An invite link lets anyone who has it join, until you remove them. It does not expire, so share it only with your team.</Description>
      {problem === null ? null : <p className="text-sm text-danger">{problem}</p>}
      <Button variant={link === null ? "primary" : "secondary"} className="self-start" onPress={make} isDisabled={busy}>
        {busy ? <Spinner size="sm" color="current" /> : null}
        {link === null ? "Make an invite link" : "Make another"}
      </Button>
    </div>
  );
}

function Leave({ owner, alone, onAsk }: { owner: boolean; alone: boolean; onAsk: (asking: Asking) => void }) {
  return (
    <div className="flex flex-col gap-3">
      {owner ? (
        <>
          <Description>{alone ? "You are the only member. Disbanding deletes the team for good." : "An owner cannot leave. Make someone else the owner in Members first, or disband the team for everyone."}</Description>
          <Button variant="danger" className="self-start" onPress={() => onAsk({ kind: "disband" })}>
            Disband the team
          </Button>
        </>
      ) : (
        <>
          <Description>You stop seeing the team's sessions. Coming back needs a new invite.</Description>
          <Button variant="danger" className="self-start" onPress={() => onAsk({ kind: "leave" })}>
            Leave the team
          </Button>
        </>
      )}
    </div>
  );
}

// Everything about the team in view: who is in it, inviting, and leaving or disbanding.
export function TeamWindow({ team, onClose }: { team: TeamState; onClose: () => void }) {
  const [members, setMembers] = useState<MemberView[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [asking, setAsking] = useState<Asking>(null);
  const [round, setRound] = useState(0);
  const profile = team.team?.profile ?? null;
  const owner = profile?.member.role === "owner";
  const { members: readMembers } = team;

  useEffect(() => {
    let alive = true;
    setMembers(null);
    readMembers()
      .then((found) => alive && setMembers(found))
      .catch((error: unknown) => {
        if (!alive) return;
        setProblem(words(error));
        setMembers([]);
      });
    return () => {
      alive = false;
    };
  }, [readMembers, round, profile?.team_id]);

  if (profile === null) return null;
  const reload = () => setRound((value) => value + 1);

  const confirm = (() => {
    if (asking === null) return null;
    switch (asking.kind) {
      case "remove":
        return { title: `Remove ${asking.member.name}?`, body: `${asking.member.name} stops seeing ${profile.team_name}'s sessions at once and needs a new invite to come back.`, action: "Remove", run: async () => { await team.remove(asking.member.id); reload(); } };
      case "owner":
        return { title: `Make ${asking.member.name} the owner?`, body: `${asking.member.name} can then invite, remove people and disband the team. You stay a member and can leave.`, action: "Make owner", run: async () => { await team.handOver(asking.member.id); reload(); } };
      case "leave":
        return { title: `Leave ${profile.team_name}?`, body: "You stop seeing the team's sessions. Coming back needs a new invite.", action: "Leave", run: async () => { await team.leave(); onClose(); } };
      case "disband":
        return { title: `Disband ${profile.team_name}?`, body: "The team is deleted for everyone in it. This cannot be undone.", action: "Disband", run: async () => { await team.disband(); onClose(); } };
    }
  })();

  return (
    <>
      <Modal.Backdrop isOpen onOpenChange={(open) => !open && onClose()}>
        <Modal.Container scroll="inside">
          <Modal.Dialog className="sm:max-w-[32rem]">
            <Modal.CloseTrigger />
            <Modal.Header className="gap-1">
              <Modal.Heading className="font-display text-2xl font-medium tracking-[-0.02em]">{profile.team_name}</Modal.Heading>
              <Description>You are {profile.member.name}{owner ? ", the owner" : ""}.</Description>
            </Modal.Header>
            <Modal.Body>
              {problem === null ? null : (
                <Alert status="danger" className="mb-3">
                  <Alert.Indicator />
                  <Alert.Content>
                    <Alert.Description>{problem}</Alert.Description>
                  </Alert.Content>
                </Alert>
              )}
              <Tabs defaultSelectedKey="members">
                <Tabs.ListContainer>
                  <Tabs.List aria-label="The team">
                    <Tabs.Tab id="members">
                      Members{members === null ? "" : ` · ${members.length}`}
                      <Tabs.Indicator />
                    </Tabs.Tab>
                    {owner ? (
                      <Tabs.Tab id="invite">
                        Invite
                        <Tabs.Indicator />
                      </Tabs.Tab>
                    ) : null}
                    <Tabs.Tab id="leave">
                      {owner ? "Disband" : "Leave"}
                      <Tabs.Indicator />
                    </Tabs.Tab>
                  </Tabs.List>
                </Tabs.ListContainer>
                <Tabs.Panel id="members" className="px-0! pb-0! pt-3">
                  <Members team={team} members={members} owner={owner} onAsk={setAsking} />
                </Tabs.Panel>
                {owner ? (
                  <Tabs.Panel id="invite" className="px-0! pb-0! pt-3">
                    <Invite team={team} />
                  </Tabs.Panel>
                ) : null}
                <Tabs.Panel id="leave" className="px-0! pb-0! pt-3">
                  <Leave owner={owner} alone={(members?.length ?? 0) <= 1} onAsk={setAsking} />
                </Tabs.Panel>
              </Tabs>
            </Modal.Body>
            <Modal.Footer>
              <Button slot="close">Done</Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
      {confirm === null ? null : <Confirm title={confirm.title} body={confirm.body} action={confirm.action} onConfirm={confirm.run} onClose={() => setAsking(null)} />}
    </>
  );
}
