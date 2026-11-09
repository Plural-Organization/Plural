import { Button, Chip, Modal } from "@heroui/react";
import { Plus, SignOut } from "@phosphor-icons/react";
import { useState } from "react";
import type { AccountState } from "../hooks/useAccount";
import { activeMachines, planLine, revokeMachine } from "../lib/accounts";
import { LinkComputer } from "./LinkComputer";
import { PersonAvatar } from "./PersonAvatar";

function when(stamp: string | null): string {
  return stamp === null ? "never connected" : `last seen ${new Date(stamp).toLocaleDateString([], { month: "short", day: "numeric" })}`;
}

export function AccountModal({ state, onClose }: { state: AccountState; onClose: () => void }) {
  const account = state.account;
  const [linking, setLinking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  if (account === null) {
    return null;
  }
  const machines = activeMachines(account);

  const revoke = (id: string) => {
    setProblem(null);
    revokeMachine(id)
      .then(() => state.refresh())
      .catch((error: unknown) => setProblem(error instanceof Error ? error.message : String(error)));
  };

  return (
    <Modal.Backdrop isOpen onOpenChange={(open) => !open && onClose()}>
      <Modal.Container>
        <Modal.Dialog className="sm:max-w-[34rem]">
          <Modal.CloseTrigger />
          <Modal.Header>
            <Modal.Heading className="font-display text-2xl font-medium tracking-[-0.02em]">Your account</Modal.Heading>
          </Modal.Header>
          <Modal.Body className="flex flex-col gap-5">
            <div className="flex items-center gap-3">
              <PersonAvatar seed={account.email} size="md" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-[15px] font-medium">{account.email}</p>
                <p className="text-sm text-muted">{planLine(account)}</p>
              </div>
              <Chip size="sm" variant="soft" color={account.plan === null ? "warning" : "success"}>
                <Chip.Label>{account.plan === null ? "No plan" : account.plan === "paid" ? "Paid" : "Trial"}</Chip.Label>
              </Chip>
            </div>

            <section className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <h3 className="text-[15px] font-medium">Your computers</h3>
                {linking ? null : (
                  <Button size="sm" variant="tertiary" onPress={() => setLinking(true)}>
                    <Plus size={15} />
                    Link a computer
                  </Button>
                )}
              </div>
              {machines.length === 0 ? (
                <p className="text-sm text-muted">No computer is linked yet.</p>
              ) : (
                <ul className="flex flex-col divide-y divide-border rounded-2xl border border-border">
                  {machines.map((machine) => (
                    <li key={machine.id} className="flex items-center gap-3 px-3.5 py-2.5">
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-mono text-[13px]">{machine.id}</p>
                        <p className="text-xs text-muted">{when(machine.last_seen_at)}</p>
                      </div>
                      <Button size="sm" variant="ghost" onPress={() => revoke(machine.id)}>
                        Remove
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
              {problem !== null ? <p className="text-sm text-danger">{problem}</p> : null}
            </section>

            {linking ? <LinkComputer state={state} /> : null}
          </Modal.Body>
          <Modal.Footer>
            <Button
              variant="ghost"
              onPress={() => {
                void state.signOut().then(onClose);
              }}
            >
              <SignOut size={16} />
              Sign out
            </Button>
            <Button slot="close">Done</Button>
          </Modal.Footer>
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
  );
}
