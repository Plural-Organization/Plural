export interface Machine {
  id: string;
  created_at: string;
  last_seen_at: string | null;
  revoked: boolean;
}

export interface Account {
  id: string;
  email: string;
  name: string;
  machines: Machine[];
}

export interface Claim {
  code: string;
  expires_at: string;
}

export class AccountError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

// Set when the build is for a Plural that has accounts; without it the page has no sign-in at all.
export const ACCOUNTS_URL: string = ((import.meta.env.VITE_ACCOUNTS_URL as string | undefined) ?? "").replace(/\/+$/, "");
export const accountsEnabled = ACCOUNTS_URL !== "";

export function signInUrl(returnTo: string, base: string = ACCOUNTS_URL): string {
  return `${base}/auth/google/start?return=${encodeURIComponent(returnTo)}`;
}

const LOGIN_ERRORS: Record<string, string> = {
  denied: "Google sign-in was cancelled.",
  failed: "Google sign-in could not be verified. Try again.",
};

export function loginErrorMessage(code: string | null): string | null {
  return code === null ? null : (LOGIN_ERRORS[code] ?? "Sign-in did not finish. Try again.");
}

async function call(path: string, init: RequestInit = {}, base: string = ACCOUNTS_URL): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, { ...init, credentials: "include" });
  } catch {
    throw new AccountError(0, "unreachable", "Accounts cannot be reached right now.");
  }
  if (response.ok) {
    return response;
  }
  let code = "failed";
  let message = "Something went wrong.";
  try {
    const body = (await response.json()) as { error?: { code?: string; message?: string } };
    code = body.error?.code ?? code;
    message = body.error?.message ?? message;
  } catch {
    // The answer was not ours; the defaults stand.
  }
  throw new AccountError(response.status, code, message);
}

export async function fetchAccount(base: string = ACCOUNTS_URL): Promise<Account | null> {
  try {
    return (await (await call("/me", {}, base)).json()) as Account;
  } catch (error) {
    if (error instanceof AccountError && error.status === 401) {
      return null;
    }
    throw error;
  }
}

export async function signOut(): Promise<void> {
  await call("/auth/logout", { method: "POST" });
}

export async function createClaim(): Promise<Claim> {
  return (await (await call("/claims", { method: "POST" })).json()) as Claim;
}

export interface Ticket {
  ticket: string;
  expires_at: string;
}

// A minute-long proof for the Plural program on this computer that this page is signed in.
export async function createTicket(): Promise<Ticket> {
  return (await (await call("/tickets", { method: "POST" })).json()) as Ticket;
}

export async function revokeMachine(id: string): Promise<void> {
  await call(`/machines/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export interface DeviceRequest {
  name: string;
  machine: string;
  expires_at: string;
  decided: boolean;
}

export async function fetchDevice(code: string): Promise<DeviceRequest> {
  return (await (await call(`/device/${encodeURIComponent(code)}`)).json()) as DeviceRequest;
}

export async function decideDevice(code: string, approve: boolean): Promise<void> {
  await call(`/device/${encodeURIComponent(code)}/${approve ? "approve" : "deny"}`, { method: "POST" });
}

export function activeMachines(account: Account): Machine[] {
  return account.machines.filter((machine) => !machine.revoked);
}
