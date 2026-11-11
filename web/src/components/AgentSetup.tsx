import { Alert, Button, ComboBox, Description, Disclosure, Input, Label, ListBox, Select, Spinner, TextField, type Key } from "@heroui/react";
import { CheckCircle, Lock } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import type { AgentSetupState } from "../hooks/useAgentSetup";
import { forgetKey, installExtra, installTool, signIn, testAgent } from "../lib/agent";
import { type Step, modelOptions, stepFor } from "../lib/agentSetup";
import { DaemonError, daemonMessage } from "../lib/daemon";
import { CopyBox } from "./CopyBox";
import { ProviderPicker } from "./ProviderPicker";

const SIGN_IN_POLL_MS = 2500;
const SIGN_IN_WAIT_MS = 3 * 60 * 1000;

const words = (error: unknown): string => (error instanceof DaemonError ? daemonMessage(error) : "Something went wrong. Try again.");

// What this provider still needs, as one thing to do: a button the page can press for the person,
// or a command to copy when only a terminal can do it.
function Needs({ setup }: { setup: AgentSetupState }) {
  const provider = setup.provider;
  const [busy, setBusy] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const step: Step | null = provider === null ? null : stepFor(provider);
  const ready = provider?.readiness.state === "ready";
  const { refresh } = setup;

  // After a sign-in window opens, look again until the CLI says it is signed in.
  useEffect(() => {
    if (!waiting) return;
    if (ready) {
      setWaiting(false);
      return;
    }
    const poll = setInterval(refresh, SIGN_IN_POLL_MS);
    const stop = setTimeout(() => setWaiting(false), SIGN_IN_WAIT_MS);
    return () => {
      clearInterval(poll);
      clearTimeout(stop);
    };
  }, [waiting, ready, refresh]);

  if (provider === null || step === null) return null;

  const run = (work: () => Promise<unknown>, then?: () => void) => {
    setProblem(null);
    setBusy(true);
    work()
      .then(() => {
        refresh();
        then?.();
      })
      .catch((error: unknown) => setProblem(error instanceof DaemonError && error.code === "no_terminal" ? `${error.message} Run it yourself: ${provider.readiness.command ?? ""}` : words(error)))
      .finally(() => setBusy(false));
  };

  const action: Record<Exclude<Step["kind"], "command">, { title: string; button: string; go: () => void }> = {
    install: {
      title: provider.readiness.detail,
      button: `Install ${provider.label}`,
      go: () => step.kind === "install" && run(() => installTool(step.tool)),
    },
    sdk: {
      title: "A small library is needed first",
      button: "Install it",
      go: () => step.kind === "sdk" && run(() => installExtra(step.extra)),
    },
    "sign-in": {
      title: provider.readiness.detail,
      button: "Sign in",
      go: () => step.kind === "sign-in" && run(() => signIn(step.tool), () => setWaiting(true)),
    },
  };

  return (
    <div className="flex flex-col gap-2.5">
      <Alert status="warning">
        <Alert.Indicator />
        <Alert.Content>
          <Alert.Title>{step.kind === "command" ? (provider.readiness.detail === "" ? "One more step" : provider.readiness.detail) : action[step.kind].title}</Alert.Title>
          {step.kind === "sign-in" ? <Alert.Description>A terminal window opens on your computer. Finish signing in there and this page notices.</Alert.Description> : null}
        </Alert.Content>
      </Alert>
      {step.kind === "command" ? (
        <CopyBox text={step.command} label="Copy the command" />
      ) : (
        <div className="flex items-center gap-3">
          <Button size="sm" onPress={action[step.kind].go} isDisabled={busy || waiting}>
            {busy || waiting ? <Spinner size="sm" color="current" /> : null}
            {waiting ? "Waiting for sign-in…" : busy ? "Working…" : action[step.kind].button}
          </Button>
          {provider.readiness.command !== null && step.kind !== "sdk" ? <span className="truncate font-mono text-xs text-muted">{provider.readiness.command}</span> : null}
        </div>
      )}
      {problem === null ? null : <p className="text-sm text-danger">{problem}</p>}
    </div>
  );
}

// The API key: typed here, kept on the computer, and never shown again.
function KeyField({ setup }: { setup: AgentSetupState }) {
  const provider = setup.provider;
  const [busy, setBusy] = useState(false);
  if (provider === null || !(provider.needsKey || provider.id === "custom")) return null;
  const facts = provider.key;
  const remove = () => {
    setBusy(true);
    forgetKey(provider.id)
      .then(setup.refresh)
      .catch(() => undefined)
      .finally(() => setBusy(false));
  };
  return (
    <TextField value={setup.typedKey} onChange={setup.setTypedKey} name="agent-key" type="password">
      <Label>{provider.needsKey ? "API key" : "API key (optional)"}</Label>
      <Input placeholder={facts.set ? "Type a new key to replace it" : "Paste your key"} autoComplete="off" spellCheck={false} />
      {facts.set ? (
        <Description className="flex items-center gap-1.5">
          <CheckCircle size={14} weight="fill" className="flex-none text-success" />
          {facts.source === "environment" ? `Using ${provider.keyEnv[0] ?? "the key"} from this computer's environment.` : `A key is saved on this computer${facts.last4 === null ? "" : `, ending ${facts.last4}`}.`}
          {facts.source === "saved" ? (
            <Button size="sm" variant="ghost" className="ml-auto h-6 min-w-0 px-2" onPress={remove} isDisabled={busy}>
              Remove
            </Button>
          ) : null}
        </Description>
      ) : (
        <Description className="flex items-center gap-1.5">
          <Lock size={13} className="flex-none" />
          Saved on this computer. It is never sent back to this page.
        </Description>
      )}
    </TextField>
  );
}

function Model({ setup }: { setup: AgentSetupState }) {
  const { provider, choice, catalog } = setup;
  if (provider === null || choice === null || catalog === null || provider.provider === "fake") return null;
  const options = modelOptions(provider, catalog.local);
  return (
    <ComboBox allowsCustomValue fullWidth menuTrigger="focus" inputValue={choice.model} onInputChange={(model) => setup.edit({ model })} onSelectionChange={(key: Key | null) => key !== null && setup.edit({ model: String(key) })}>
      <Label>Model</Label>
      <ComboBox.InputGroup>
        <Input placeholder={options[0] ?? "Model id"} autoComplete="off" spellCheck={false} />
        {options.length > 0 ? <ComboBox.Trigger /> : null}
      </ComboBox.InputGroup>
      <Description>{options.length > 0 ? "Pick one, or type any model id." : "Type the model id."}</Description>
      {options.length > 0 ? (
        <ComboBox.Popover>
          <ListBox>
            {options.map((model) => (
              <ListBox.Item key={model} id={model} textValue={model}>
                {model}
                <ListBox.ItemIndicator />
              </ListBox.Item>
            ))}
          </ListBox>
        </ComboBox.Popover>
      ) : null}
    </ComboBox>
  );
}

function Advanced({ setup }: { setup: AgentSetupState }) {
  const { provider, choice } = setup;
  if (provider === null || choice === null || provider.provider === "fake") return null;
  return (
    <Disclosure>
      <Disclosure.Heading>
        <Disclosure.Trigger className="flex w-full items-center justify-between text-sm text-muted">
          More options
          <Disclosure.Indicator />
        </Disclosure.Trigger>
      </Disclosure.Heading>
      <Disclosure.Content>
        <Disclosure.Body className="flex flex-col gap-3 pt-2">
          {provider.editableUrl ? (
            <TextField value={choice.baseUrl} onChange={(baseUrl) => setup.edit({ baseUrl })} name="agent-endpoint">
              <Label>Endpoint</Label>
              <Input placeholder={provider.baseUrl === "" ? "http://127.0.0.1:11434/v1" : provider.baseUrl} autoComplete="off" spellCheck={false} />
              <Description>The address of an OpenAI-compatible server.</Description>
            </TextField>
          ) : null}
          {provider.contextWindow ? (
            <TextField value={choice.contextWindow} onChange={(contextWindow) => setup.edit({ contextWindow })} name="agent-window" inputMode="numeric">
              <Label>Context window</Label>
              <Input placeholder="Default" autoComplete="off" />
              <Description>Tokens the server really accepts, so long chats are summarised in time.</Description>
            </TextField>
          ) : null}
          <Select value={choice.fastModel === "off" ? "off" : "auto"} onChange={(value) => setup.edit({ fastModel: String(value as Key) === "off" ? "off" : "" })}>
            <Label>Fast model</Label>
            <Select.Trigger>
              <Select.Value />
              <Select.Indicator />
            </Select.Trigger>
            <Select.Popover>
              <ListBox>
                <ListBox.Item id="auto" textValue="Automatic">
                  Automatic
                  <ListBox.ItemIndicator />
                </ListBox.Item>
                <ListBox.Item id="off" textValue="Off">
                  Off
                  <ListBox.ItemIndicator />
                </ListBox.Item>
              </ListBox>
            </Select.Popover>
            <Description>Summaries and helper agents use a cheaper model when one is reachable.</Description>
          </Select>
        </Disclosure.Body>
      </Disclosure.Content>
    </Disclosure>
  );
}

function TestConnection({ setup }: { setup: AgentSetupState }) {
  const [state, setState] = useState<{ phase: "idle" | "testing" } | { phase: "ok" | "failed"; text: string }>({ phase: "idle" });
  const { provider, choice, typedKey, blocker } = setup;
  // A different provider or model starts a fresh test.
  useEffect(() => setState({ phase: "idle" }), [provider?.id, choice?.model]);
  if (provider === null || choice === null) return null;
  const test = () => {
    setState({ phase: "testing" });
    testAgent({ ...choice, model: choice.model.trim() }, typedKey.trim())
      .then((result) => setState({ phase: "ok", text: result.message }))
      .catch((error: unknown) => setState({ phase: "failed", text: words(error) }));
  };
  return (
    <div className="flex flex-col gap-2.5">
      <Button variant="secondary" size="sm" className="self-start" onPress={test} isDisabled={blocker !== null || state.phase === "testing"}>
        {state.phase === "testing" ? <Spinner size="sm" color="current" /> : null}
        Test connection
      </Button>
      {state.phase === "ok" || state.phase === "failed" ? (
        <Alert status={state.phase === "ok" ? "success" : "danger"}>
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Description>{state.phase === "ok" ? `${provider.label} ${state.text}.` : state.text}</Alert.Description>
          </Alert.Content>
        </Alert>
      ) : null}
    </div>
  );
}

// Which agent runs, set up on the computer that runs it: provider, account, model, a test.
// The same screen starts a room and changes a running one.
export function AgentSetup({ setup }: { setup: AgentSetupState }) {
  if (setup.error !== null) {
    return (
      <Alert status="danger">
        <Alert.Indicator />
        <Alert.Content>
          <Alert.Description>{setup.error}</Alert.Description>
        </Alert.Content>
      </Alert>
    );
  }
  if (setup.catalog === null || setup.provider === null) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted">
        <Spinner size="sm" color="current" />
        Reading the agents on this computer…
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-4">
      <ProviderPicker providers={setup.catalog.presets} value={setup.provider} onPick={setup.pick} />
      <Needs setup={setup} />
      <KeyField setup={setup} />
      <Model setup={setup} />
      <Advanced setup={setup} />
      <TestConnection setup={setup} />
    </div>
  );
}
