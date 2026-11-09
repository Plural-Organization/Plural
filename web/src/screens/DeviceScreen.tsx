import { Button, Spinner } from "@heroui/react";
import { Check, GoogleLogo, X } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { LogoMark } from "../components/LogoMark";
import type { AccountState } from "../hooks/useAccount";
import { type DeviceRequest, decideDevice, fetchDevice, signInUrl } from "../lib/accounts";

type Step = "asking" | "linked" | "refused";

function Card({ children }: { children: React.ReactNode }) {
  return (
    <main className="relative isolate flex min-h-full flex-col items-center justify-center overflow-hidden px-4 py-12">
      <div className="pixel-grid" aria-hidden="true" />
      <div className="w-full max-w-[26rem]">
        <LogoMark size={48} className="mx-auto text-foreground" />
        <div className="mt-8 rounded-[2rem] border border-white/[0.08] bg-white/[0.02] p-2">
          <div className="enter rounded-[calc(2rem-0.5rem)] bg-[#0b0b0d] p-6 shadow-[inset_0_1px_0_rgb(255_255_255/0.06)]">{children}</div>
        </div>
      </div>
    </main>
  );
}

// Where the browser lands when `plural login` opens it: the person confirms that the computer in front of them is the one asking.
export function DeviceScreen({ code, account }: { code: string; account: AccountState }) {
  const [request, setRequest] = useState<DeviceRequest | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [step, setStep] = useState<Step>("asking");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (account.status !== "in") {
      return;
    }
    fetchDevice(code)
      .then(setRequest)
      .catch((error: unknown) => setProblem(error instanceof Error ? error.message : String(error)));
  }, [account.status, code]);

  const decide = (approve: boolean) => {
    setBusy(true);
    decideDevice(code, approve)
      .then(() => setStep(approve ? "linked" : "refused"))
      .catch((error: unknown) => setProblem(error instanceof Error ? error.message : String(error)))
      .finally(() => setBusy(false));
  };

  const home = (
    <a href={window.location.pathname} className="link-button mt-5 inline-block">
      Open Plural
    </a>
  );

  if (account.status === "loading") {
    return (
      <Card>
        <Spinner size="sm" />
      </Card>
    );
  }

  if (account.status !== "in") {
    return (
      <Card>
        <h1 className="text-2xl font-medium tracking-[-0.02em]">Link this computer</h1>
        <p className="mt-2 text-[15px] leading-relaxed text-muted">Sign in to link the computer that is waiting in your terminal.</p>
        {account.loginError ? <p className="mt-3 text-sm text-danger">{account.loginError}</p> : null}
        <Button className="mt-5" fullWidth size="lg" variant="tertiary" isDisabled={!account.enabled} onPress={() => window.location.assign(signInUrl(window.location.href))}>
          <GoogleLogo size={18} weight="bold" />
          Continue with Google
        </Button>
      </Card>
    );
  }

  if (step === "linked") {
    return (
      <Card>
        <div className="flex items-center gap-3 text-[15px]">
          <Check size={20} weight="bold" className="flex-none text-success" />
          Done. This computer is linked, go back to your terminal.
        </div>
        {home}
      </Card>
    );
  }

  if (step === "refused") {
    return (
      <Card>
        <div className="flex items-center gap-3 text-[15px]">
          <X size={20} weight="bold" className="flex-none text-muted" />
          Nothing was linked. The terminal stops waiting.
        </div>
        {home}
      </Card>
    );
  }

  if (problem !== null && request === null) {
    return (
      <Card>
        <h1 className="text-2xl font-medium tracking-[-0.02em]">This code does not work</h1>
        <p className="mt-2 text-[15px] leading-relaxed text-muted">{problem} Run <code>plural login</code> again for a new one.</p>
        {home}
      </Card>
    );
  }

  return (
    <Card>
      <h1 className="text-2xl font-medium tracking-[-0.02em]">Link this computer?</h1>
      {request === null ? (
        <div className="mt-5">
          <Spinner size="sm" />
        </div>
      ) : (
        <>
          <p className="mt-2 text-[15px] leading-relaxed text-muted">
            <b className="font-medium text-foreground">{request.name || "A computer"}</b> asks to use your account{account.account ? ` (${account.account.email})` : ""}.
          </p>
          <div className="mt-4 flex items-center justify-between rounded-2xl border border-border bg-background px-4 py-3">
            <span className="text-sm text-muted">The terminal shows</span>
            <code className="bg-transparent p-0 font-mono text-[15px] tracking-wider">{code.toUpperCase()}</code>
          </div>
          <p className="mt-2 text-sm text-muted">Link it only if that code is the one in your terminal.</p>
          {problem !== null ? <p className="mt-3 text-sm text-danger">{problem}</p> : null}
          <div className="mt-5 flex gap-2">
            <Button fullWidth size="lg" variant="tertiary" isDisabled={busy} onPress={() => decide(false)}>
              Cancel
            </Button>
            <Button fullWidth size="lg" isDisabled={busy} onPress={() => decide(true)}>
              Link this computer
            </Button>
          </div>
        </>
      )}
    </Card>
  );
}
