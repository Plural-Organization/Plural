import { describe, expect, test } from "bun:test";
import { hostBridgeApi, type BridgeApp, type Runner } from "../src/bridges";
import { appsRows, type ModelState } from "../src/settingsModel";
import { DEFAULT_SETTINGS } from "../src/settings";
import { DEFAULT_CHOICE } from "../src/presets";

const telegram = (over: Partial<BridgeApp> = {}): BridgeApp => ({
  id: "telegram",
  label: "Telegram",
  summary: "Mention the bot in a group.",
  steps: ["Open @BotFather and send /newbot.", "Paste the token here."],
  fields: [
    { id: "token", label: "Bot token", secret: true, required: true, help: "From @BotFather.", placeholder: "" },
    { id: "names", label: "Names that call the bot", secret: false, required: false, help: "Words that call the bot.", placeholder: "" },
  ],
  configured: false,
  enabled: false,
  state: "off",
  identity: "",
  error: "",
  values: { token: "", names: "" },
  set: [],
  owners: [],
  pairing: null,
  chats: 0,
  links: { open: "", invite: "", autopair: false },
  ...over,
});

const state = (over: Partial<ModelState> = {}): ModelState => ({
  settings: DEFAULT_SETTINGS,
  choice: DEFAULT_CHOICE,
  keys: {},
  mode: "open",
  role: "host",
  canConfigure: true,
  apps: [telegram()],
  ...over,
});

const ids = (rows: { id: string }[]): string[] => rows.map((row) => row.id);

describe("chat apps rows", () => {
  test("a service that is not set up shows its steps and a save that waits for the token", () => {
    const rows = appsRows(state());
    expect(ids(rows)).toContain("app:telegram:step0");
    const save = rows.find((row) => row.id === "app:telegram:save");
    expect(save?.enabled).toBe(false);
    expect(rows.find((row) => row.id === "app:telegram:remove")).toBeUndefined();
  });

  test("a typed token enables saving and testing, and is shown masked", () => {
    const rows = appsRows(state({ drafts: { "telegram:token": "123456:ABCDEFGHIJ" } }));
    expect(rows.find((row) => row.id === "app:telegram:save")?.enabled).toBe(true);
    expect(rows.find((row) => row.id === "app:telegram:test")?.enabled).toBe(true);
    const token = rows.find((row) => row.id === "app:telegram:field:token");
    expect(token?.kind).toBe("secret");
    expect(token?.value).not.toContain("123456");
  });

  test("a saved token says it is saved and never shows it", () => {
    const rows = appsRows(state({ apps: [telegram({ configured: true, enabled: true, state: "running", identity: "@plural_bot", set: ["token"] })] }));
    const token = rows.find((row) => row.id === "app:telegram:field:token");
    expect(token?.value).toBe("saved");
    expect(rows[1]?.label).toContain("@plural_bot");
    expect(ids(rows)).toContain("app:telegram:toggle");
    expect(ids(rows)).toContain("app:telegram:remove");
  });

  test("the pairing code shows until there is an owner, then adding one is an action", () => {
    const base = { configured: true, enabled: true, state: "running" as const, identity: "@plural_bot", set: ["token"] };
    const waiting = appsRows(state({ apps: [telegram({ ...base, pairing: "482913" })] }));
    expect(waiting.find((row) => row.id === "app:telegram:pair")?.label).toContain("/pair 482913");
    const owned = appsRows(state({ apps: [telegram({ ...base, owners: [{ id: "7", name: "Askar" }] })] }));
    expect(owned.find((row) => row.id === "app:telegram:owners")?.label).toContain("Askar");
    expect(ids(owned)).toContain("app:telegram:renew");
  });

  test("a link that carries the code replaces typing it, and the invite is offered", () => {
    const links = { open: "https://t.me/plural_bot?start=482913", invite: "https://t.me/plural_bot?startgroup=true", autopair: true };
    const base = { configured: true, enabled: true, state: "running" as const, identity: "@plural_bot", set: ["token"], links };
    const rows = appsRows(state({ apps: [telegram({ ...base, pairing: "482913" })] }));
    const pair = rows.find((row) => row.id === "app:telegram:pair")?.label ?? "";
    expect(pair).toContain("https://t.me/plural_bot?start=482913");
    expect(pair).not.toContain("/pair");
    expect(rows.find((row) => row.id === "app:telegram:invite")?.label).toContain("startgroup");
  });

  test("a failed bridge shows why", () => {
    const rows = appsRows(state({ apps: [telegram({ configured: true, enabled: true, state: "failed", error: "Telegram does not know this token" })] }));
    expect(rows.find((row) => row.id === "app:telegram:error")?.label).toContain("does not know this token");
  });

  test("reading and failing are notes, not an empty list", () => {
    expect(appsRows(state({ apps: null }))[0]?.id).toBe("apps-wait");
    expect(appsRows(state({ appsError: "Update plural" }))[0]?.label).toBe("Update plural");
  });
});

describe("the host's bridge commands", () => {
  test("values go on standard input and never in the arguments", async () => {
    const calls: { args: string[]; stdin?: string }[] = [];
    const run: Runner = async (args, stdin) => {
      calls.push({ args, stdin });
      return { code: 0, out: JSON.stringify({ ok: true }) };
    };
    const result = await hostBridgeApi(run).save("telegram", { token: "123:secret" }, true);
    expect(result.ok).toBe(true);
    expect(calls[0]?.args.join(" ")).not.toContain("secret");
    expect(calls[0]?.args).toEqual(["set", "telegram", "--stdin", "--json", "--enable"]);
    expect(JSON.parse(calls[0]?.stdin ?? "{}")).toEqual({ values: { token: "123:secret" } });
  });

  test("a refusal carries the host's reason, and an old host is told to update", async () => {
    const refused: Runner = async () => ({ code: 1, out: JSON.stringify({ ok: false, error: "Telegram does not know this token" }) });
    expect((await hostBridgeApi(refused).test("telegram", {})).error).toBe("Telegram does not know this token");
    const old: Runner = async () => ({ code: 2, out: "" });
    expect((await hostBridgeApi(old).save("telegram", {})).error).toContain("Update plural");
    await expect(hostBridgeApi(old).list()).rejects.toThrow("Update plural");
  });

  test("the list is what the host reports", async () => {
    const run: Runner = async () => ({ code: 0, out: `${JSON.stringify({ ok: true, providers: [telegram()] })}\n` });
    const apps = await hostBridgeApi(run).list();
    expect(apps.map((app) => app.id)).toEqual(["telegram"]);
  });
});
