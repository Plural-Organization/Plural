import { createHash, randomBytes } from "node:crypto";
import { spawn } from "node:child_process";
import { chmodSync, mkdirSync, readFileSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { copyToClipboard } from "./lib/clipboard";

const CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e";
const REDIRECT_URI = "https://platform.claude.com/oauth/code/callback";
const TOKEN_URL = "https://platform.claude.com/v1/oauth/token";
const SCOPES = "org:create_api_key user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload";

export interface OAuthCredentials {
  access: string;
  refresh: string;
  expires: number;
}

export interface OAuthAttempt {
  verifier: string;
  url: string;
}

export function oauthPath(environment: Record<string, string | undefined> = process.env): string {
  return join(environment["PLURAL_DATA_DIR"] ?? join(homedir(), ".plural"), "anthropic-oauth.json");
}

export function beginOAuth(): OAuthAttempt {
  const verifier = randomBytes(32).toString("base64url");
  const challenge = createHash("sha256").update(verifier).digest("base64url");
  const params = new URLSearchParams({
    code: "true",
    client_id: CLIENT_ID,
    response_type: "code",
    redirect_uri: REDIRECT_URI,
    scope: SCOPES,
    code_challenge: challenge,
    code_challenge_method: "S256",
    state: verifier,
  });
  return { verifier, url: `https://claude.ai/oauth/authorize?${params}` };
}

export function parseAuthorizationCode(input: string, verifier: string): string {
  const value = input.trim();
  let code = value;
  let state: string | null = null;
  if (value.startsWith("http://") || value.startsWith("https://")) {
    const url = new URL(value);
    code = url.searchParams.get("code") ?? "";
    state = url.searchParams.get("state");
  } else if (value.includes("#")) {
    [code, state] = value.split("#", 2) as [string, string];
  } else if (value.startsWith("code=")) {
    const params = new URLSearchParams(value);
    code = params.get("code") ?? "";
    state = params.get("state");
  }
  if (state !== null && state !== verifier) {
    throw new Error("OAuth state mismatch; start sign in again");
  }
  if (!code) {
    throw new Error("Paste the code shown by Claude after sign in");
  }
  return code;
}

export async function exchangeCode(input: string, verifier: string): Promise<OAuthCredentials> {
  const code = parseAuthorizationCode(input, verifier);
  const response = await fetch(TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      grant_type: "authorization_code",
      client_id: CLIENT_ID,
      code,
      state: verifier,
      redirect_uri: REDIRECT_URI,
      code_verifier: verifier,
    }),
    signal: AbortSignal.timeout(30_000),
  });
  if (!response.ok) {
    throw new Error(`Claude sign in failed (${response.status}); start again`);
  }
  const payload = (await response.json()) as Record<string, unknown>;
  if (typeof payload["access_token"] !== "string" || typeof payload["refresh_token"] !== "string" ||
      typeof payload["expires_in"] !== "number" || payload["expires_in"] <= 0) {
    throw new Error("Claude returned an invalid login response");
  }
  return {
    access: payload["access_token"],
    refresh: payload["refresh_token"],
    expires: Date.now() / 1000 + payload["expires_in"],
  };
}

export function hasOAuth(path: string = oauthPath()): boolean {
  try {
    const value = JSON.parse(readFileSync(path, "utf8")) as Record<string, unknown>;
    return typeof value["access"] === "string" && typeof value["refresh"] === "string" &&
      typeof value["expires"] === "number";
  } catch {
    return false;
  }
}

export function saveOAuth(credentials: OAuthCredentials, path: string = oauthPath()): void {
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  const temporary = `${path}.${randomBytes(6).toString("hex")}.tmp`;
  try {
    writeFileSync(temporary, `${JSON.stringify(credentials)}\n`, { encoding: "utf8", mode: 0o600 });
    chmodSync(temporary, 0o600);
    renameSync(temporary, path);
  } catch (error) {
    try { unlinkSync(temporary); } catch { /* no temporary file */ }
    throw error;
  }
}

export function clearOAuth(path: string = oauthPath()): void {
  try {
    unlinkSync(path);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
}

export async function openOAuth(attempt: OAuthAttempt): Promise<void> {
  await copyToClipboard(attempt.url, (value) => process.stdout.write(`\u001b]52;c;${Buffer.from(value).toString("base64")}\u0007`));
  const command = process.platform === "darwin" ? ["open", attempt.url] :
    process.platform === "win32" ? ["cmd", "/c", "start", "", attempt.url] : ["xdg-open", attempt.url];
  try {
    const child = spawn(command[0]!, command.slice(1), { stdio: "ignore", detached: true });
    child.on("error", () => undefined);
    child.unref();
  } catch { /* The copied URL can be opened manually. */ }
}
