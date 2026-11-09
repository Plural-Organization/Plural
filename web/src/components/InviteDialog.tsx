import { Button, Label, Modal } from "@heroui/react";
import { Check, Copy } from "@phosphor-icons/react";
import { useState } from "react";
import type { Invite } from "../hooks/useSession";
import { copyText } from "../lib/clipboard";
import { browserJoinLink } from "../lib/links";

export function InviteDialog({ invite, onClose }: { invite: Invite; onClose: () => void }) {
  const [copied, setCopied] = useState<string | null>(null);
  const web = browserJoinLink(invite.link, window.location);
  const terminal = `plural join "${invite.link}"`;
  const expires = invite.expiresAt === null ? null : new Date(invite.expiresAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  const copy = (key: string, text: string) =>
    void copyText(text).then((ok) => {
      setCopied(ok ? key : null);
      setTimeout(() => setCopied(null), 1600);
    });

  const links = [
    { key: "web", label: "In the browser", text: web },
    { key: "terminal", label: "In a terminal", text: terminal },
  ];

  return (
    <Modal.Backdrop isOpen onOpenChange={(open) => !open && onClose()}>
      <Modal.Container>
        <Modal.Dialog className="sm:max-w-[36rem]">
          <Modal.CloseTrigger />
          <Modal.Header>
            <Modal.Heading className="font-display text-2xl font-medium tracking-[-0.02em]">{invite.reusable ? "The room link" : `Invite a ${invite.role}`}</Modal.Heading>
          </Modal.Header>
          <Modal.Body className="flex flex-col gap-4">
            {invite.reusable ? (
              <p className="text-[15px] leading-relaxed text-muted">
                This link stays the same and does not expire. Each person who uses it waits until you let them in, and you choose whether they take part or only watch.{" "}
                <code>/invite revoke</code> ends it.
              </p>
            ) : (
              <p className="text-[15px] leading-relaxed text-muted">
                The link works once and expires at {expires}. Anyone you send it to joins as a {invite.role}
                {invite.role === "viewer" ? " and can only watch." : " and can prompt the agent. Their writes and commands still ask you."}
              </p>
            )}
            {links.map((link) => (
              <div key={link.key} className="flex flex-col gap-1.5">
                <Label>{link.label}</Label>
                <div className="flex items-center gap-2 rounded-2xl border border-border bg-background py-1.5 pr-1.5 pl-4">
                  <code className="min-w-0 flex-1 truncate bg-transparent p-0 font-mono text-[13px]">{link.text}</code>
                  <Button size="sm" variant="tertiary" onPress={() => copy(link.key, link.text)}>
                    {copied === link.key ? <Check size={15} /> : <Copy size={15} />}
                    {copied === link.key ? "Copied" : "Copy"}
                  </Button>
                </div>
              </div>
            ))}
          </Modal.Body>
          <Modal.Footer>
            <Button slot="close">Done</Button>
          </Modal.Footer>
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
  );
}
