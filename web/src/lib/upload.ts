import type { Command, Projection } from "@plural/client";
import { base64 } from "../hooks/useAttachments";
import { sha256 } from "./sha256";

const WAIT_MS = 15_000;

// Sends a file to the host and resolves with its attachment id, or null when it never arrives.
export async function upload(file: Blob, name: string, projection: Projection, send: (command: Command) => void): Promise<string | null> {
  const data = new Uint8Array(await file.arrayBuffer());
  const hash = await sha256(data);
  send({ type: "file.attach", name, content_b64: base64(data), sha256: hash });
  const deadline = Date.now() + WAIT_MS;
  while (Date.now() < deadline) {
    const found = Object.values(projection.state.attachments).find((meta) => meta.sha256 === hash && meta.owner_id === projection.meId);
    if (found) {
      return found.id;
    }
    await new Promise((resolve) => setTimeout(resolve, 60));
  }
  return null;
}
