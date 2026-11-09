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
  plan: "trial" | "paid" | null;
  plan_ends_at: string | null;
  trial_started: boolean;
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

export async function revokeMachine(id: string): Promise<void> {
  await call(`/machines/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function activeMachines(account: Account): Machine[] {
  return account.machines.filter((machine) => !machine.revoked);
}

export function planLine(account: Account, now: number = Date.now()): string {
  if (account.plan === null) {
    return account.trial_started ? "Trial ended" : "Free trial starts with your first computer";
  }
  if (account.plan === "paid") {
    return "Plan active";
  }
  const days = Math.max(0, Math.ceil((Date.parse(account.plan_ends_at ?? "") - now) / 86_400_000));
  return days === 1 ? "Trial, 1 day left" : `Trial, ${days} days left`;
}
