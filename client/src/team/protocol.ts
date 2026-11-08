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
