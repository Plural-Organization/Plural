# ADR 0017: the hosted relay requires an account to host

Status: accepted.

## Context

ADR 0013 gave every host a certificate from the accounts service and left the relay logging what it
found, with refusal "a separate decision, taken after the log shows who would be turned away". Plural
has not been released to people yet, so there is no one to turn away: the log would show nobody.

The product is a hosted relay that is easy to start on, with free use up to a limit and payment
beyond it, next to a relay anyone can run for themselves. Both need a hosted relay that knows who
opens a room.

## Decision

- **A relay run with `--require-account` refuses a host without a valid certificate.** It needs
  `--accounts-url`, and the relay exits at start without it. A relay without the option behaves as
  before, so every self-hosted relay keeps accepting everyone.
- **Only hosts and team creation are asked.** Opening `/host/{room}` closes with 4402 (no
  certificate), 4403 (expired, forged, malformed, or a certificate for another host key) or 4503 (the
  accounts key is not known yet), each with a reason that says what to do (`plural login`). `POST
  /teams` without an account proof is a 401. Guests are never asked, joining a team with an
  invite is not creating one, and the invite stays the gate.
- **4503 refuses and says to retry.** The alternative, letting a host in while the key is unknown, would
  make the rule skippable by catching a relay at start. The key is read in the background and kept, so
  an accounts outage after that never stops a room (ADR 0013).
- **`/healthz` says so.** A relay that requires accounts answers `{"ok": true, "accounts":
  "required"}`, so a client can tell a person to sign in before it opens a room. Any other relay answers
  `{"ok": true}` as before.
- **No plan, no quota.** Whether a certificate is valid is the only thing judged. Free hours, plans and
  payment are a later decision that adds a claim to the certificate (ADR 0013, "Plans … do not exist").

## Consequences

- A host that is refused reconnects with a growing delay and says nothing until the host side reads
  the close code; teaching hosts and clients to ask `/healthz` first and to show the reason is the
  next change.
- A certificate lasts 7 days and renews itself, so a computer that was offline for longer has to sign
  in again before it can host on a relay that requires accounts.
- The relay still never calls the accounts service while a host is opening a room.
