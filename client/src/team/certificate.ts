// A certificate lasts 30 days; past this much of it left, a client asks for a fresh one.
const RENEW_BEFORE_MS = 7 * 24 * 3600 * 1000;

function fromBase64url(text: string): Uint8Array {
  const plain = atob(text.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (text.length % 4)) % 4));
  return Uint8Array.from(plain, (char) => char.charCodeAt(0));
}

// When the certificate was made and runs out, read from its signed claims.
export function certificateWindow(certificate: string): { issued: number; expiry: number } | null {
  try {
    const claims = JSON.parse(new TextDecoder().decode(fromBase64url(certificate.split(".")[0]!))) as { iat?: string; exp?: string };
    const issued = claims.iat ? Date.parse(claims.iat) : NaN;
    const expiry = claims.exp ? Date.parse(claims.exp) : NaN;
    return Number.isNaN(issued) || Number.isNaN(expiry) ? null : { issued, expiry };
  } catch {
    return null;
  }
}

// Due once less than a week, or less than half its life, is left; a fresh certificate is never due.
export function renewalDue(certificate: string, now: number): boolean {
  const window = certificateWindow(certificate);
  return window !== null && window.expiry - now <= Math.min(RENEW_BEFORE_MS, (window.expiry - window.issued) / 2);
}
