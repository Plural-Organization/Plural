import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { mkdtempSync, writeFileSync, chmodSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { listSessions } from "../src/sessions";
import pkg from "../package.json" with { type: "json" };

const SCRIPT = resolve(import.meta.dir, "../../install.sh");

let server: ReturnType<typeof Bun.serve>;
beforeAll(() => {
  server = Bun.serve({
    port: 0,
    fetch(request) {
      const path = new URL(request.url).pathname;
      if (path === "/releases/latest") {
        return Response.redirect(`http://127.0.0.1:${server.port}/releases/tag/v9.8.7`, 302);
      }
      if (path === "/other/latest") {
        return Response.redirect(`http://127.0.0.1:${server.port}/other/somewhere`, 302);
      }
      return new Response("ok");
    },
  });
});
afterAll(() => server.stop(true));

async function latestFrom(base: string): Promise<{ out: string; code: number }> {
  const child = Bun.spawn(["sh", "-c", `PLURAL_INSTALL_SOURCE_ONLY=1 . "${SCRIPT}"; latest_version`], {
    env: { ...(process.env as Record<string, string>), PLURAL_RELEASE_URL: base },
    stdout: "pipe",
    stderr: "pipe",
  });
  const out = (await new Response(child.stdout).text()).trim();
  return { out, code: await child.exited };
}

describe("the installer pins both parts to one release", () => {
  test("the latest version is read from where the releases page sends you", async () => {
    expect(await latestFrom(`http://127.0.0.1:${server.port}/releases`)).toEqual({ out: "9.8.7", code: 0 });
  });

  test("a redirect that is not a release, or no network, gives no version instead of a guess", async () => {
    expect((await latestFrom(`http://127.0.0.1:${server.port}/other`)).code).not.toBe(0);
    expect((await latestFrom("http://127.0.0.1:9/releases")).code).not.toBe(0);
  });

  test("sourcing it for a test installs nothing", async () => {
    const child = Bun.spawn(["sh", "-c", `PLURAL_INSTALL_SOURCE_ONLY=1 . "${SCRIPT}"; echo sourced`], { stdout: "pipe", stderr: "pipe" });
    expect((await new Response(child.stdout).text()).trim()).toBe("sourced");
  });

  test("the host is refreshed from the index so a stale cache cannot keep an old one", async () => {
    const text = await Bun.file(SCRIPT).text();
    expect(text).toContain('uv tool install --force --refresh-package plural-agent "$package"');
  });

  test("the host runs on any Python the machine has, so uv does not fetch one it does not need", async () => {
    const text = await Bun.file(SCRIPT).text();
    expect(text).not.toContain("--python 3.12");
  });
});

describe("a host that does not know the command", () => {
  test("is named with how to update it", async () => {
    const directory = mkdtempSync(join(tmpdir(), "plural-oldhost-"));
    const fake = join(directory, "plural-host");
    writeFileSync(fake, "#!/bin/sh\necho \"No such command 'sessions'.\" >&2\nexit 2\n");
    chmodSync(fake, 0o755);
    const saved = process.env["PLURAL_HOST_CMD"];
    process.env["PLURAL_HOST_CMD"] = fake;
    try {
      await expect(listSessions()).rejects.toThrow(`older than this plural ${pkg.version}`);
      await expect(listSessions()).rejects.toThrow(/plural update/);
    } finally {
      if (saved === undefined) delete process.env["PLURAL_HOST_CMD"];
      else process.env["PLURAL_HOST_CMD"] = saved;
    }
  });
});

async function extrasFor(env: Record<string, string>, tools: string): Promise<string> {
  const child = Bun.spawn(["sh", "-c", `PLURAL_INSTALL_SOURCE_ONLY=1 . "${SCRIPT}"; host_extras`], {
    env: { ...(process.env as Record<string, string>), PLURAL_PROVIDER: "", PLURAL_EXTRAS: "", PATH: `${tools}:${process.env["PATH"]}`, ...env },
    stdout: "pipe",
    stderr: "pipe",
  });
  const out = (await new Response(child.stdout).text()).trim();
  await child.exited;
  return out;
}

describe("the optional model SDKs", () => {
  const tools = mkdtempSync(join(tmpdir(), "plural-uv-"));
  // A uv that points at a host environment whose python imports only what the file `sdks` lists.
  const environment = join(tools, "env", "plural-agent", "bin");
  Bun.spawnSync(["mkdir", "-p", environment]);
  writeFileSync(join(tools, "sdks"), "");
  writeFileSync(join(environment, "python"), `#!/bin/sh\ngrep -qx "\${2#import }" "${join(tools, "sdks")}"\n`);
  chmodSync(join(environment, "python"), 0o755);
  writeFileSync(join(tools, "uv"), `#!/bin/sh\necho "${join(tools, "env")}"\n`);
  chmodSync(join(tools, "uv"), 0o755);

  test("a plain install takes none, so it stays small", async () => {
    expect(await extrasFor({}, tools)).toBe("");
  });

  test("the provider the user named, or PLURAL_EXTRAS, picks the SDKs", async () => {
    expect(await extrasFor({ PLURAL_PROVIDER: "anthropic" }, tools)).toBe("anthropic");
    expect(await extrasFor({ PLURAL_PROVIDER: "anthropic_oauth" }, tools)).toBe("anthropic");
    expect(await extrasFor({ PLURAL_PROVIDER: "openai" }, tools)).toBe("openai");
    expect(await extrasFor({ PLURAL_PROVIDER: "claude_code" }, tools)).toBe("");
    expect(await extrasFor({ PLURAL_EXTRAS: "anthropic,openai" }, tools)).toBe("anthropic,openai");
  });

  test("an update keeps the SDKs the installed host already has", async () => {
    writeFileSync(join(tools, "sdks"), "openai\n");
    expect(await extrasFor({}, tools)).toBe("openai");
    expect(await extrasFor({ PLURAL_PROVIDER: "anthropic" }, tools)).toBe("anthropic,openai");
    writeFileSync(join(tools, "sdks"), "");
  });
});

async function currentWith(version: string, installed: string, sdks: string, env: Record<string, string> = {}): Promise<number> {
  const tools = mkdtempSync(join(tmpdir(), "plural-current-"));
  const bin = join(tools, "env", "plural-agent", "bin");
  Bun.spawnSync(["mkdir", "-p", bin]);
  writeFileSync(join(tools, "sdks"), sdks);
  writeFileSync(join(bin, "python"), `#!/bin/sh\ngrep -qx "\${2#import }" "${join(tools, "sdks")}"\n`);
  chmodSync(join(bin, "python"), 0o755);
  const listing = installed ? `plural-agent v${installed}\n- plural-host` : "";
  writeFileSync(join(tools, "uv"), `#!/bin/sh\nif [ "$2" = dir ]; then echo "${join(tools, "env")}"; else printf '${listing}\\n'; fi\n`);
  chmodSync(join(tools, "uv"), 0o755);
  const child = Bun.spawn(["sh", "-c", `PLURAL_INSTALL_SOURCE_ONLY=1 . "${SCRIPT}"; VERSION=${version}; host_is_current`], {
    env: { ...(process.env as Record<string, string>), PLURAL_PROVIDER: "", PLURAL_EXTRAS: "", PATH: `${tools}:${process.env["PATH"]}`, ...env },
    stdout: "pipe",
    stderr: "pipe",
  });
  return child.exited;
}

describe("a host that is already current is not downloaded again", () => {
  test("the same release with nothing new asked for is skipped", async () => {
    expect(await currentWith("0.2.11", "0.2.11", "")).toBe(0);
    expect(await currentWith("v0.2.11", "0.2.11", "")).toBe(0);
  });

  test("another release, no host, or a version that could not be resolved still installs", async () => {
    expect(await currentWith("0.2.12", "0.2.11", "")).not.toBe(0);
    expect(await currentWith("0.2.11", "", "")).not.toBe(0);
    expect(await currentWith("latest", "0.2.11", "")).not.toBe(0);
  });

  test("an SDK that is asked for but missing installs, one that is kept does not", async () => {
    expect(await currentWith("0.2.11", "0.2.11", "", { PLURAL_PROVIDER: "anthropic" })).not.toBe(0);
    expect(await currentWith("0.2.11", "0.2.11", "anthropic\n", { PLURAL_PROVIDER: "anthropic" })).toBe(0);
    expect(await currentWith("0.2.11", "0.2.11", "openai\n")).toBe(0);
  });

  test("a host package given by hand always installs", async () => {
    expect(await currentWith("0.2.11", "0.2.11", "", { PLURAL_HOST_PACKAGE: "./dist/plural_agent.whl" })).not.toBe(0);
  });
});
