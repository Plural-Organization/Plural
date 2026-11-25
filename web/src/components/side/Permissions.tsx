import { Button, Chip } from "@heroui/react";
import { ShieldCheck, Warning } from "@phosphor-icons/react";
import type { PermissionMode } from "@plural/client";
import { PERMISSIONS } from "../../lib/roomSettings";
import { Section } from "./Section";

// How much the agent does without asking the host. Everyone sees it, since in the danger zone a guest's
// request runs on the host's computer straight away; the host can change it from here.
export function Permissions({ mode, isHost, onChange }: { mode: PermissionMode; isHost: boolean; onChange?: () => void }) {
  const option = PERMISSIONS.find((item) => item.id === mode);
  const danger = mode === "danger";
  return (
    <Section title="agent may" tour="permissions">
      <div className="mb-1.5 flex items-center gap-2">
        <Chip size="sm" variant="soft" color={danger ? "danger" : "default"}>
          {danger ? <Warning size={13} weight="bold" /> : <ShieldCheck size={13} weight="bold" />}
          <Chip.Label>{option?.label ?? mode}</Chip.Label>
        </Chip>
        <span className="grow" />
        {isHost && onChange ? (
          <Button size="sm" variant="ghost" className="h-7 px-2" onPress={onChange}>
            Change
          </Button>
        ) : null}
      </div>
      <p className={danger ? "text-danger" : "muted"}>{option?.says ?? ""}</p>
    </Section>
  );
}
