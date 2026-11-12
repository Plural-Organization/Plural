import { Chip } from "@heroui/react";
import { Desktop } from "@phosphor-icons/react";
import type { DaemonPhase } from "../hooks/useDaemon";

const WORDS: Record<Exclude<DaemonPhase, "checking">, { text: string; hint: string; color: "success" | "warning" }> = {
  ready: { text: "Computer connected", hint: "Plural runs on this computer and can start rooms.", color: "success" },
  unlinked: { text: "Computer not signed in", hint: "Run plural login on this computer.", color: "warning" },
  absent: { text: "Computer not found", hint: "Plural is not running on this computer. Press to set it up.", color: "warning" },
};

// One line in the rail that says whether this page can reach Plural on this computer, so a room that will not
// start never comes as a surprise. Pressing it opens the setup when something is missing.
export function ComputerStatus({ phase, stuck, onFix }: { phase: DaemonPhase; stuck: boolean; onFix: () => void }) {
  if (phase === "checking" && !stuck) return null;
  const { text, hint, color } = phase === "checking" ? { text: "Allow local network access", hint: "Your browser is asking whether this page may reach Plural on your computer. Choose Allow near the address bar.", color: "warning" as const } : WORDS[phase];
  return (
    <button
      type="button"
      title={hint}
      onClick={phase === "ready" || phase === "checking" ? undefined : onFix}
      className="flex w-full items-center gap-2 rounded-xl px-2.5 py-1.5 text-left text-[13px] text-muted outline-none transition-colors enabled:hover:bg-surface-secondary data-[focus-visible=true]:ring-2 data-[focus-visible=true]:ring-focus"
      disabled={phase === "ready" || phase === "checking"}
    >
      <Desktop size={15} className="flex-none" />
      <span className="min-w-0 flex-1 truncate">{text}</span>
      <Chip size="sm" variant="soft" color={color} className="flex-none">
        <Chip.Label>{phase === "ready" ? "On" : phase === "checking" ? "Wait" : "Off"}</Chip.Label>
      </Chip>
    </button>
  );
}
