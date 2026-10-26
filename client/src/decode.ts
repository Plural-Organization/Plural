import type { Envelope, Event, EventRecord } from "./protocol";

export class ProtocolError extends Error {}

export function decodeEnvelope(raw: string): Envelope | null {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null) {
    return null;
  }
  const envelope = value as Partial<Envelope>;
  if (typeof envelope.id !== "string" || typeof envelope.kind !== "string") {
    return null;
  }
  return envelope as Envelope;
}

export function decodeEvent(envelope: Envelope): Event {
  if (envelope.kind !== "evt" || typeof envelope.type !== "string") {
    throw new ProtocolError("not an event");
  }
  return { ...envelope.payload, type: envelope.type } as unknown as Event;
}

export function decodeRecord(envelope: Envelope): EventRecord | null {
  if (envelope.seq === null || envelope.seq === undefined) {
    return null;
  }
  return {
    seq: envelope.seq,
    id: envelope.id,
    ts: envelope.ts,
    actor_id: envelope.actor,
    event: decodeEvent(envelope),
  };
}
