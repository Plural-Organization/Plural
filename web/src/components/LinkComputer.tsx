import { Button, Spinner, Tabs } from "@heroui/react";
import { ArrowsClockwise, Check } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { AccountState } from "../hooks/useAccount";
import { useNow } from "../hooks/useNow";
import { activeMachines, type Claim, createClaim } from "../lib/accounts";
import { agentPrompt, linkCommand } from "../lib/agentPrompt";
import { CopyBox } from "./CopyBox";

import { INSTALL } from "../lib/install";
const POLL_MS = 3000;

// Install Plural, then link this computer to the account: a code that works once, and the page watches for the computer to appear.
export function LinkComputer({ state }: { state: AccountState }) {
  const [claim, setClaim] = useState<Claim | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const known = useRef(state.account === null ? 0 : activeMachines(state.account).length);
  const [linked, setLinked] = useState(false);
  const now = useNow(claim !== null && !linked);
  const { refresh } = state;

  const newCode = useCallback(() => {
    setProblem(null);
    createClaim()
      .then(setClaim)
      .catch((error: unknown) => setProblem(error instanceof Error ? error.message : String(error)));
  }, []);

  useEffect(newCode, [newCode]);

  useEffect(() => {
    if (claim === null || linked) {
      return;
    }
    const timer = setInterval(() => {
      void refresh().then((next) => {
        if (next !== null && activeMachines(next).length > known.current) {
          setLinked(true);
        }
      });
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [claim, linked, refresh]);

  if (linked) {
    return (
      <div className="enter flex items-center gap-3 rounded-2xl border border-success/40 bg-success/10 px-4 py-3.5 text-[15px]">
        <Check size={18} weight="bold" className="flex-none text-success" />
        This computer is linked to your account.
      </div>
    );
  }

  const left = claim === null ? 0 : Math.max(0, Math.ceil((Date.parse(claim.expires_at) - now) / 1000));
  const expired = claim !== null && left === 0;

  return (
    <div className="flex flex-col gap-5">
      <section className="flex flex-col gap-2.5">
        <h3 className="text-[15px] font-medium">1. Install Plural</h3>
        <Tabs defaultSelectedKey="terminal">
          <Tabs.ListContainer>
            <Tabs.List aria-label="How to install">
              <Tabs.Tab id="terminal">Terminal<Tabs.Indicator /></Tabs.Tab>
              <Tabs.Tab id="agent">Ask your AI agent<Tabs.Indicator /></Tabs.Tab>
            </Tabs.List>
          </Tabs.ListContainer>
          <Tabs.Panel id="terminal" className="flex flex-col gap-2.5 px-0! pb-0! pt-3">
            <CopyBox text={INSTALL} label="Copy the install command" />
            <p className="text-sm text-muted">macOS and Linux. On Windows use WSL.</p>
          </Tabs.Panel>
          <Tabs.Panel id="agent" className="flex flex-col gap-2.5 px-0! pb-0! pt-3">
            {claim === null || expired ? (
              <p className="text-sm text-muted">The prompt carries your code, so it needs a fresh one.</p>
            ) : (
              <CopyBox text={agentPrompt(claim.code)} label="Copy the prompt" multiline />
            )}
            <p className="text-sm text-muted">Paste it into Claude Code, Codex, Cursor or another agent that can run commands. It asks before it runs anything.</p>
          </Tabs.Panel>
        </Tabs>
      </section>

      <section className="flex flex-col gap-2.5">
        <h3 className="text-[15px] font-medium">2. Link this computer</h3>
        {problem !== null ? <p className="text-sm text-danger">{problem}</p> : null}
        {claim === null ? (
          problem === null ? <Spinner size="sm" /> : null
        ) : (
          <>
            <CopyBox text={linkCommand(claim.code)} label="Copy the link command" />
            <div className="flex items-center justify-between gap-3 text-sm text-muted">
              <span className="flex items-center gap-2">
                {expired ? "The code expired." : (
                  <>
                    <Spinner size="sm" color="current" />
                    Waiting for the computer · {Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")}
                  </>
                )}
              </span>
              <Button size="sm" variant="ghost" onPress={newCode}>
                <ArrowsClockwise size={14} />
                New code
              </Button>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
