import { useCallback, useEffect, useState } from "react";
import { type Account, accountsEnabled, fetchAccount, loginErrorMessage, signOut as endSession } from "../lib/accounts";

export interface AccountState {
  enabled: boolean;
  // `off` when this build has no accounts, `loading` while the first answer is awaited.
  status: "off" | "loading" | "out" | "in" | "error";
  account: Account | null;
  // Why the last sign-in did not finish, read from the address Google sent the person back to.
  loginError: string | null;
  refresh: () => Promise<Account | null>;
  signOut: () => Promise<void>;
}

function takeLoginError(): string | null {
  const url = new URL(window.location.href);
  const code = url.searchParams.get("login_error");
  if (code === null) {
    return null;
  }
  url.searchParams.delete("login_error");
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  return loginErrorMessage(code);
}

export function useAccount(): AccountState {
  const [status, setStatus] = useState<AccountState["status"]>(accountsEnabled ? "loading" : "off");
  const [account, setAccount] = useState<Account | null>(null);
  const [loginError] = useState(() => (accountsEnabled ? takeLoginError() : null));

  const refresh = useCallback(async () => {
    if (!accountsEnabled) {
      return null;
    }
    try {
      const next = await fetchAccount();
      setAccount(next);
      setStatus(next === null ? "out" : "in");
      return next;
    } catch {
      setStatus((current) => (current === "loading" ? "error" : current));
      return null;
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const signOut = useCallback(async () => {
    await endSession();
    setAccount(null);
    setStatus("out");
  }, []);

  return { enabled: accountsEnabled, status, account, loginError, refresh, signOut };
}
