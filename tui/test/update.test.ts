import { describe, expect, test } from "bun:test";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { parseArgs, UsageError } from "../src/options";
import { compareVersions, isInstalledBinary, latestVersion, runInstaller, runUpdate, skewNote, Updater, type Installer, type UpdateState } from "../src/update";

class Capture {
  text = "";
  write(text: string): void {
    this.text += text;
  }
}

const release = (tag: unknown, status = 200): typeof fetch =>
  (async () => new Response(JSON.stringify({ tag_name: tag }), { status })) as unknown as typeof fetch;

describe("versions", () => {
  test("are compared as numbers, not as text", () => {
    expect(compareVersions("0.10.0", "0.9.5")).toBe(1);
    expect(compareVersions("0.2.1", "v0.2.1")).toBe(0);
    expect(compareVersions("0.2.9", "0.3.0")).toBe(-1);
    expect(compareVersions("1.0.0", "0.99.99")).toBe(1);
    expect(() => compareVersions("latest", "0.2.1")).toThrow();
  });

  test("the latest release is read from its tag", async () => {
    expect(await latestVersion(release("v0.3.0"))).toBe("0.3.0");
    await expect(latestVersion(release("v0.3.0", 403))).rejects.toThrow(/403/);
    await expect(latestVersion(release("nightly"))).rejects.toThrow(/no version/);
    await expect(latestVersion(release(undefined))).rejects.toThrow(/no version/);
  });

  test("only the installed program can replace itself", () => {
    expect(isInstalledBinary("/home/me/.local/bin/plural")).toBe(true);
    expect(isInstalledBinary("/usr/local/bin/plural")).toBe(true);
    expect(isInstalledBinary("/home/me/.bun/bin/bun")).toBe(false);
    expect(isInstalledBinary("/usr/bin/node")).toBe(false);
  });
});

describe("plural update", () => {
  function setup(latest: unknown, execPath = "/home/me/.local/bin/plural", code = 0) {
    const out = new Capture();
    const err = new Capture();
    const runs: Record<string, string>[] = [];
    const install: Installer = async (environment) => {
      runs.push(environment);
      return code;
    };
    const deps = { current: "0.2.1", execPath, fetcher: release(latest), install, out, err };
    return { deps, out, err, runs };
  }

  test("says so when nothing newer exists and installs nothing", async () => {
    const { deps, out, runs } = setup("v0.2.1");
    expect(await runUpdate({ check: false }, deps)).toBe(0);
    expect(out.text).toBe("plural 0.2.1 is up to date\n");
    expect(runs).toEqual([]);
  });

  test("a version older than mine is not an update", async () => {
    const { deps, runs } = setup("v0.2.0");
    expect(await runUpdate({ check: false }, deps)).toBe(0);
    expect(runs).toEqual([]);
  });

  test("--check only reports", async () => {
    const { deps, out, runs } = setup("v0.3.0");
    expect(await runUpdate({ check: true }, deps)).toBe(0);
    expect(out.text).toContain("plural 0.3.0 is available, you have 0.2.1");
    expect(runs).toEqual([]);
  });

  test("installs that exact version next to the running program", async () => {
    const { deps, out, err, runs } = setup("v0.3.0");
    expect(await runUpdate({ check: false }, deps)).toBe(0);
    expect(runs).toEqual([{ PLURAL_VERSION: "0.3.0", PLURAL_INSTALL_DIR: "/home/me/.local/bin" }]);
    expect(out.text).toContain("updating plural 0.2.1 → 0.3.0");
    expect(out.text).toContain("plural 0.3.0 is installed");
    expect(err.text).toBe("");
  });

  test("a copy that runs from source is told how it can be updated", async () => {
    const { deps, err, runs } = setup("v0.3.0", "/home/me/.bun/bin/bun");
    expect(await runUpdate({ check: false }, deps)).toBe(1);
    expect(err.text).toContain("cannot replace itself");
    expect(runs).toEqual([]);
  });

  test("a failed install is reported with how to go on", async () => {
    const { deps, err } = setup("v0.3.0", "/home/me/.local/bin/plural", 3);
    expect(await runUpdate({ check: false }, deps)).toBe(1);
    expect(err.text).toContain("did not finish (exit 3)");
  });

  test("no network is reported, not thrown", async () => {
    const out = new Capture();
    const err = new Capture();
    const failing = (async () => {
      throw new Error("getaddrinfo ENOTFOUND api.github.com");
    }) as unknown as typeof fetch;
    expect(await runUpdate({ check: false }, { current: "0.2.1", execPath: "/x/plural", fetcher: failing, out, err })).toBe(1);
    expect(err.text).toContain("could not look up the latest version");
    expect(err.text).toContain("ENOTFOUND");
  });
});

describe("the installer is the project's own script", () => {
  test("it runs with the version and the folder as environment", async () => {
    const directory = mkdtempSync(join(tmpdir(), "plural-update-"));
    const script = join(directory, "install.sh");
    const record = join(directory, "record.txt");
    writeFileSync(script, `printf '%s|%s' "$PLURAL_VERSION" "$PLURAL_INSTALL_DIR" > "${record}"\n`);
    const code = await runInstaller(`file://${script}`)({ PLURAL_VERSION: "0.3.0", PLURAL_INSTALL_DIR: "/opt/bin" });
    expect(code).toBe(0);
    expect(readFileSync(record, "utf8")).toBe("0.3.0|/opt/bin");
  });

  test("a script that cannot be fetched fails the update", async () => {
    expect(await runInstaller("file:///nowhere/install.sh")({})).not.toBe(0);
  });

  test("a script that fails passes its code on", async () => {
    const directory = mkdtempSync(join(tmpdir(), "plural-update-"));
    const script = join(directory, "install.sh");
    writeFileSync(script, "exit 7\n");
    expect(await runInstaller(`file://${script}`)({})).toBe(7);
  });
});

describe("a host older than the client", () => {
  test("is named with how to fix it", () => {
    const note = skewNote("0.2.2", "0.2.1");
    expect(note).toContain("plural-host 0.2.1");
    expect(note).toContain("plural update");
    expect(note).toContain("plural-agent==0.2.2");
  });

  test("an equal or newer host, or a version that cannot be read, says nothing", () => {
    expect(skewNote("0.2.2", "0.2.2")).toBeNull();
    expect(skewNote("0.2.2", "0.3.0")).toBeNull();
    expect(skewNote("0.2.2", "dev")).toBeNull();
    expect(skewNote("dev", "0.2.1")).toBeNull();
  });
});

describe("the command line", () => {
  test("update and update --check", () => {
    expect(parseArgs(["update"])).toEqual({ kind: "update", check: false });
    expect(parseArgs(["update", "--check"])).toEqual({ kind: "update", check: true });
    expect(() => parseArgs(["update", "--now"])).toThrow(UsageError);
  });
});

describe("the update offer", () => {
  const binary = "/home/me/.local/bin/plural";

  function watch(updater: Updater): UpdateState[] {
    const seen: UpdateState[] = [];
    updater.subscribe((state) => state && seen.push(state));
    return seen;
  }

  test("a newer release is offered and an equal or older one is not", async () => {
    const newer = new Updater({ current: "0.2.4", execPath: binary, fetcher: release("v0.2.5") });
    await newer.check();
    expect(newer.state).toEqual({ phase: "ready", version: "0.2.5" });
    const same = new Updater({ current: "0.2.5", execPath: binary, fetcher: release("v0.2.5") });
    await same.check();
    expect(same.state).toBeNull();
  });

  test("a failed look-up offers nothing", async () => {
    const offline = new Updater({ current: "0.2.4", execPath: binary, fetcher: release("v0.2.5", 500) });
    await offline.check();
    expect(offline.state).toBeNull();
  });

  test("a copy that runs from source is not offered an update it cannot install", async () => {
    const source = new Updater({ current: "0.2.4", execPath: "/usr/bin/node", fetcher: release("v0.3.0") });
    await source.check();
    expect(source.state).toBeNull();
  });

  test("installing pins the version and the folder of the running program", async () => {
    const calls: Record<string, string>[] = [];
    const install: Installer = async (environment) => {
      calls.push(environment);
      return 0;
    };
    const updater = new Updater({ current: "0.2.4", execPath: binary, fetcher: release("v0.2.5"), install });
    await updater.check();
    const seen = watch(updater);
    await updater.install();
    expect(calls).toEqual([{ PLURAL_VERSION: "0.2.5", PLURAL_INSTALL_DIR: "/home/me/.local/bin" }]);
    expect(seen.map((state) => state.phase)).toEqual(["installing", "installed"]);
  });

  test("a failed install can be tried again and nothing runs twice at once", async () => {
    let code = 3;
    let runs = 0;
    const install: Installer = async () => {
      runs += 1;
      return code;
    };
    const updater = new Updater({ current: "0.2.4", execPath: binary, fetcher: release("v0.2.5"), install });
    await updater.check();
    await updater.install();
    expect(updater.state).toEqual({ phase: "failed", version: "0.2.5", code: 3 });
    code = 0;
    await updater.install();
    expect(updater.state?.phase).toBe("installed");
    await updater.install();
    expect(runs).toBe(2);
  });
});
