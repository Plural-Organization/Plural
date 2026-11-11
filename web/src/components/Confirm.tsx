import { AlertDialog, Button, Spinner } from "@heroui/react";
import { useState } from "react";

interface ConfirmProps {
  title: string;
  body: string;
  action: string;
  onConfirm: () => Promise<void>;
  onClose: () => void;
}

// A step that cannot be taken back, asked once in HeroUI's alert dialog. A failure stays in the dialog.
export function Confirm({ title, body, action, onConfirm, onClose }: ConfirmProps) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const go = () => {
    setBusy(true);
    setProblem(null);
    onConfirm()
      .then(onClose)
      .catch((error: unknown) => setProblem(error instanceof Error ? error.message : String(error)))
      .finally(() => setBusy(false));
  };
  return (
    <AlertDialog.Backdrop isOpen onOpenChange={(open) => !open && onClose()}>
      <AlertDialog.Container>
        <AlertDialog.Dialog className="sm:max-w-[26rem]">
          <AlertDialog.Header>
            <AlertDialog.Icon status="danger" />
            <AlertDialog.Heading>{title}</AlertDialog.Heading>
          </AlertDialog.Header>
          <AlertDialog.Body>
            <p className="text-[15px] leading-relaxed text-muted">{body}</p>
            {problem === null ? null : <p className="mt-2 text-sm text-danger">{problem}</p>}
          </AlertDialog.Body>
          <AlertDialog.Footer>
            <Button slot="close" variant="tertiary">
              Cancel
            </Button>
            <Button variant="danger" onPress={go} isDisabled={busy}>
              {busy ? <Spinner size="sm" color="current" /> : null}
              {action}
            </Button>
          </AlertDialog.Footer>
        </AlertDialog.Dialog>
      </AlertDialog.Container>
    </AlertDialog.Backdrop>
  );
}
