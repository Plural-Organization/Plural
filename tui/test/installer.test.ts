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
    expect(text).toContain('uv tool install --force --refresh --python 3.12 "$package"');
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
