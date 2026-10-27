import { describe, expect, test } from "bun:test";
import { mkdtempSync, readFileSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { beginOAuth, clearOAuth, exchangeCode, hasOAuth, oauthPath, parseAuthorizationCode, saveOAuth } from "../src/anthropicOAuth";

describe("Claude OAuth", () => {
  test("authorization uses PKCE and checks the returned state", () => {
    const attempt = beginOAuth();
    const url = new URL(attempt.url);
    expect(url.hostname).toBe("claude.ai");
    expect(url.searchParams.get("code_challenge_method")).toBe("S256");
    expect(url.searchParams.get("code_challenge")).not.toBe(attempt.verifier);
    expect(url.searchParams.get("state")).toBe(attempt.verifier);
    expect(parseAuthorizationCode(`abc#${attempt.verifier}`, attempt.verifier)).toBe("abc");
    expect(() => parseAuthorizationCode("abc#wrong", attempt.verifier)).toThrow("state mismatch");
    expect(() => parseAuthorizationCode("", attempt.verifier)).toThrow("Paste the code");
  });

  test("credentials are private and can be removed", () => {
    const directory = mkdtempSync(join(tmpdir(), "plural-oauth-"));
    const path = join(directory, "data", "anthropic-oauth.json");
    expect(oauthPath({ PLURAL_DATA_DIR: join(directory, "data") })).toBe(path);
    expect(hasOAuth(path)).toBe(false);
    saveOAuth({ access: "access", refresh: "refresh", expires: 12345 }, path);
    expect(hasOAuth(path)).toBe(true);
    expect(statSync(path).mode & 0o777).toBe(0o600);
    expect(JSON.parse(readFileSync(path, "utf8"))).toEqual({ access: "access", refresh: "refresh", expires: 12345 });
    clearOAuth(path);
    expect(hasOAuth(path)).toBe(false);
  });

  test("the code exchange uses the matching PKCE verifier", async () => {
    const original = globalThis.fetch;
    const attempt = beginOAuth();
    let sent: Record<string, string> | null = null;
    globalThis.fetch = (async (_url, init) => {
      sent = JSON.parse(init?.body as string) as Record<string, string>;
      return Response.json({ access_token: "access", refresh_token: "refresh", expires_in: 3600 });
    }) as typeof fetch;
    try {
      const credentials = await exchangeCode(`code#${attempt.verifier}`, attempt.verifier);
      expect(sent).toMatchObject({
        grant_type: "authorization_code",
        code: "code",
        state: attempt.verifier,
        code_verifier: attempt.verifier,
      });
      expect(credentials.access).toBe("access");
      expect(credentials.refresh).toBe("refresh");
      expect(credentials.expires).toBeGreaterThan(Date.now() / 1000 + 3500);
    } finally {
      globalThis.fetch = original;
    }
  });
});
