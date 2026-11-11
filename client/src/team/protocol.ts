// What a team request and a team join sign. The Python host and relay make the same strings
// (src/plural/security/identity.py), and client/test/fixtures/team-vectors.json holds the values
// every implementation has to reproduce.

export function httpBase(relay: string): string {
  const url = new URL(relay.trim());
  const scheme = ({ "ws:": "http:", "wss:": "https:", "http:": "http:", "https:": "https:" } as Record<string, string>)[url.protocol];
  if (scheme === undefined) {
    throw new Error(`${relay} is not a relay address`);
  }
  return `${scheme}//${url.host}`;
}

export function requestMessage(method: string, path: string, bodyHash: string, timestamp: number, nonce: string): string {
  return `${method.toUpperCase()}\n${path}\n${timestamp}\n${nonce}\n${bodyHash}`;
}

export function joinMessage(url: string, room: string, timestamp: number, nonce: string): string {
  return `plural-team-join\n${url}\n${room}\n${timestamp}\n${nonce}`;
}

export function authorizationHeader(certificate: string, timestamp: number, nonce: string, signature: string): string {
  return `Plural cert=${certificate} ts=${timestamp} nonce=${nonce} sig=${signature}`;
}

export function freshNonce(): string {
  return [...globalThis.crypto.getRandomValues(new Uint8Array(8))].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

// An invite code as the relay compares it: lowercase letters and digits, without the "tm" prefix
// (relay/directory.py `normalize_code`).
export function normalizeTeamCode(code: string): string {
  const plain = [...code.toLowerCase()].filter((character) => /[a-z0-9]/.test(character)).join("");
  return plain.startsWith("tm") ? plain.slice(2) : plain;
}

// What a device's key signs to show a key-only member is its own, so an account can take it over
// (protocol/team.py `key_proof_message`, ADR 0016).
export function keyProofMessage(code: string): string {
  return `plural-team-key:${normalizeTeamCode(code)}`;
}

// What a computer's certificate key signs to prove its account to a team directory
// (protocol/team.py `account_proof_message`).
export function accountProofMessage(timestamp: number, nonce: string): string {
  return `plural-teams:${timestamp}:${nonce}`;
}
