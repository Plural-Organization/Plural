import { Alert, Button, Card, Chip, Description, Disclosure, Input, Label, Spinner, TextField } from "@heroui/react";
import { CheckCircle, Lock } from "@phosphor-icons/react";
import { useState } from "react";
import { useBridges } from "../hooks/useBridges";
import { type BridgeProvider, type BridgeState, removeBridge, removeOwner, renewPairing, saveBridge, testBridge } from "../lib/bridges";
import { DaemonError, daemonMessage } from "../lib/daemon";
import { CopyBox } from "./CopyBox";

const words = (error: unknown): string => (error instanceof DaemonError ? daemonMessage(error) : "Something went wrong. Try again.");

const STATE: Record<BridgeState, { label: string; color: "success" | "warning" | "danger" | "default" }> = {
  running: { label: "Connected", color: "success" },
  starting: { label: "Connecting…", color: "warning" },
  failed: { label: "Failed", color: "danger" },
  idle: { label: "Waiting to start", color: "warning" },
  off: { label: "Off", color: "default" },
};

// How the person makes themselves the bot's owner: the code goes to the bot in a private chat.
function Owners({ provider, refresh }: { provider: BridgeProvider; refresh: () => void }) {
  const [code, setCode] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const shown = provider.pairing ?? code;
  const bot = provider.identity === "" ? "the bot" : provider.identity;
  const act = (work: () => Promise<unknown>) => {
    setProblem(null);
    work()
      .then(refresh)
      .catch((error: unknown) => setProblem(words(error)));
  };
  return (
    <div className="flex flex-col gap-2.5">
      <p className="text-[15px] font-medium">Who controls it</p>
      {provider.owners.length === 0 ? (
        <Description>Nobody yet. Only an owner links chats to sessions, answers what the agent asks to allow, and stops runs.</Description>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {provider.owners.map((owner) => (
            <li key={owner.id} className="flex items-center gap-2 text-sm">
              <CheckCircle size={14} weight="fill" className="flex-none text-success" />
              <span className="min-w-0 flex-1 truncate">{owner.name || owner.id}</span>
              <Button size="sm" variant="ghost" className="h-6 min-w-0 px-2" onPress={() => act(() => removeOwner(provider.id, owner.id))}>
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}
      {shown === null ? (
        <Button size="sm" variant="secondary" className="self-start" onPress={() => act(() => renewPairing(provider.id).then(setCode))}>
          Add another owner
        </Button>
      ) : (
        <>
          <Description>
            Send this to {bot} in a <b>private</b> chat. It works once.
          </Description>
          <CopyBox text={`/pair ${shown}`} label="Copy the pairing message" />
        </>
      )}
      {problem === null ? null : <p className="text-sm text-danger">{problem}</p>}
    </div>
  );
}

// One chat service: what to do in it, the fields it needs, a test, and the switch.
function Provider({ provider, refresh }: { provider: BridgeProvider; refresh: () => void }) {
  const [typed, setTyped] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<"save" | "test" | "toggle" | "remove" | null>(null);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const missing = provider.fields.some((field) => field.required && (typed[field.id] ?? "") === "" && !provider.set.includes(field.id));
  const state = STATE[provider.configured && !provider.enabled ? "off" : provider.state];

  const run = (kind: NonNullable<typeof busy>, work: () => Promise<string | undefined>) => {
    setResult(null);
    setBusy(kind);
    work()
      .then((text) => {
        if (text !== undefined) setResult({ ok: true, text });
        refresh();
      })
      .catch((error: unknown) => setResult({ ok: false, text: words(error) }))
      .finally(() => setBusy(null));
  };

  const save = () =>
    run("save", async () => {
      await saveBridge(provider.id, typed, true);
      setTyped({});
      return "Saved. Connecting…";
    });

  return (
    <Card variant="secondary">
      <Card.Header className="flex-row items-center gap-3">
        <div className="min-w-0 flex-1">
          <Card.Title className="text-[15px]">{provider.label}</Card.Title>
          <Card.Description className="truncate">{provider.state === "running" && provider.enabled ? `${provider.identity} · ${provider.chats} chat${provider.chats === 1 ? "" : "s"}` : provider.summary}</Card.Description>
        </div>
        <Chip size="sm" variant="soft" color={state.color} className="flex-none">
          <Chip.Label>{state.label}</Chip.Label>
        </Chip>
      </Card.Header>
      <Card.Content className="gap-4">
        {provider.state === "failed" && provider.enabled && provider.error !== "" ? (
          <Alert status="danger">
            <Alert.Indicator />
            <Alert.Content>
              <Alert.Description>{provider.error}</Alert.Description>
            </Alert.Content>
          </Alert>
        ) : null}
        <Disclosure defaultExpanded={!provider.configured}>
          <Disclosure.Heading>
            <Disclosure.Trigger className="flex w-full items-center justify-between text-sm text-muted">
              {provider.configured ? "Settings" : "How to set it up"}
              <Disclosure.Indicator />
            </Disclosure.Trigger>
          </Disclosure.Heading>
          <Disclosure.Content>
            <Disclosure.Body className="flex flex-col gap-4 pt-2">
              <ol className="flex list-decimal flex-col gap-1 pl-5 text-sm text-muted">
                {provider.steps.map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ol>
              {provider.fields.map((field) => (
                <TextField key={field.id} value={typed[field.id] ?? (field.secret ? "" : (provider.values[field.id] ?? ""))} onChange={(value) => setTyped((before) => ({ ...before, [field.id]: value }))} name={`${provider.id}-${field.id}`} type={field.secret ? "password" : "text"}>
                  <Label>{field.required ? field.label : `${field.label} (optional)`}</Label>
                  <Input placeholder={field.secret && provider.set.includes(field.id) ? "Type a new one to replace it" : field.placeholder} autoComplete="off" spellCheck={false} />
                  {field.secret ? (
                    <Description className="flex items-center gap-1.5">
                      {provider.set.includes(field.id) ? <CheckCircle size={14} weight="fill" className="flex-none text-success" /> : <Lock size={13} className="flex-none" />}
                      {provider.set.includes(field.id) ? "Saved on this computer." : "Saved on this computer. It is never sent back to this page."}
                    </Description>
                  ) : (
                    <Description>{field.help}</Description>
                  )}
                </TextField>
              ))}
              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm" onPress={save} isDisabled={busy !== null || missing}>
                  {busy === "save" ? <Spinner size="sm" color="current" /> : null}
                  {provider.configured ? "Save" : "Save and connect"}
                </Button>
                <Button size="sm" variant="secondary" isDisabled={busy !== null || missing} onPress={() => run("test", async () => `Reached ${await testBridge(provider.id, typed)}.`)}>
                  {busy === "test" ? <Spinner size="sm" color="current" /> : null}
                  Test
                </Button>
                {provider.configured ? (
                  <>
                    <Button size="sm" variant="secondary" isDisabled={busy !== null} onPress={() => run("toggle", async () => void (await saveBridge(provider.id, {}, !provider.enabled)))}>
                      {provider.enabled ? "Turn off" : "Turn on"}
                    </Button>
                    <Button size="sm" variant="ghost" className="ml-auto text-danger" isDisabled={busy !== null} onPress={() => run("remove", async () => void (await removeBridge(provider.id)))}>
                      Remove
                    </Button>
                  </>
                ) : null}
              </div>
            </Disclosure.Body>
          </Disclosure.Content>
        </Disclosure>
        {result === null ? null : (
          <Alert status={result.ok ? "success" : "danger"}>
            <Alert.Indicator />
            <Alert.Content>
              <Alert.Description>{result.text}</Alert.Description>
            </Alert.Content>
          </Alert>
        )}
        {provider.configured ? <Owners provider={provider} refresh={refresh} /> : null}
      </Card.Content>
    </Card>
  );
}

// Chat apps: the services a session can be reached from. Set up on the computer that runs the sessions, because
// that is where the bot's token is kept and the bridge runs.
export function ChatApps({ active }: { active: boolean }) {
  const { providers, error, refresh } = useBridges(active);
  if (error !== null) {
    return (
      <Alert status="danger">
        <Alert.Indicator />
        <Alert.Content>
          <Alert.Description>{error}</Alert.Description>
        </Alert.Content>
      </Alert>
    );
  }
  if (providers === null) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted">
        <Spinner size="sm" color="current" />
        Reading the chat apps on this computer…
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <Description>Talk to a session from Telegram or Discord: mention the bot, see the agent work, answer its requests with a button. Then send /link to the bot to pick the session.</Description>
      {providers.map((provider) => (
        <Provider key={provider.id} provider={provider} refresh={refresh} />
      ))}
    </div>
  );
}
