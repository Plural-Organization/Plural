# ADR 0013: computers belong to accounts

Status: accepted for the certificate and the logging relay; enforcement is a later decision.

## Context

Plural has had no notion of who runs a host. A relay can limit by address and, with `--clients-only`,
by User-Agent, but both are easy to fake, and neither lets a hosted relay say "this room belongs to a
person". We want sign-in with Google, `plural login` from the terminal, and hosting started from the web,
without turning the relay into a service that holds accounts, and without asking guests to sign in.

## Decision

- **A separate accounts service** (a private repository) owns accounts, Google sign-in and the
  device approval page. The open-source host, relay and web client only speak its small HTTP API.
- **A computer is linked to an account by a certificate**: `base64url(claims).base64url(signature)`,
  Ed25519, the same shape as a team certificate. The claims are `v`, `account`, `key`, `iat`, `exp`,
  where `key` is the host key the room is opened with (`relay.open.public_key`). The host proves it
  holds `key` by signing a challenge when it asks, so a certificate cannot be moved to another computer.
  Certificates last 7 days and the host renews them on its own when less than a day is left.
- **A relay judges a certificate offline** with the service's public key from
  `/.well-known/entitlement-key`, read in the background at start and again every hour or when a
  certificate looks forged (a rotated key). It never calls the service on the path of a host opening a
  room, so the accounts service being down cannot stop a room.
- **Sign-in is optional for now.** A host that sends no certificate, an expired one, or one for another
  key is counted and logged (`relay.entitlement`, and `entitlements` in `/metrics`), and still gets its
  room. Guests never carry a certificate and are not looked at.
- **Plans, trials and billing do not exist.** Claims carry no plan, so adding one later is a new claim,
  not a change to the meaning of this one.

## Later

Refusing hosts without a valid certificate is a separate decision, taken after the log shows who would
be turned away. It needs a way for a self-hosted or private relay to keep accepting everyone (no
`--accounts-url`, which is the default) and a clear message in the client for a host that is refused.

## Consequences

- A relay run without `--accounts-url` behaves exactly as before.
- The certificate says which account a key belonged to when it was issued; it does not make the key
  secret or the person present. A stolen host key and its certificate work until the certificate
  expires, so the lifetime is the revocation window.
- Account ids are opaque (`a_<hex>`), and the relay logs the id only for a certificate that checked out.
