import { useEffect, useRef, useState } from "react";
import type { Command, Projection } from "@plural/client";
import { sha256 } from "../lib/sha256";

// The host's limits: images up to 2.5 MB reach the model as pictures, other files up to 1 MB as text.
export const IMAGE_LIMIT = 2_500_000;
export const FILE_LIMIT = 1_048_576;
const WAIT_MS = 15_000;
const IMAGE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"];

export interface Attachment {
  key: string;
  name: string;
  size: number;
  sha256: string;
  preview: string | null;
}

function base64(data: Uint8Array): string {
  let text = "";
  for (let index = 0; index < data.length; index += 0x8000) {
    text += String.fromCharCode(...data.subarray(index, index + 0x8000));
  }
  return btoa(text);
}

// A file is sent as text only if it reads as text: no NUL bytes near the start.
function looksLikeText(data: Uint8Array): boolean {
  return !data.subarray(0, 8192).includes(0);
}

export function useAttachments(projection: Projection, send: (command: Command) => void, notify: (text: string) => void) {
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const counter = useRef(0);

  useEffect(() => () => attachments.forEach((item) => item.preview && URL.revokeObjectURL(item.preview)), []);

  const add = async (file: Blob, name: string): Promise<void> => {
    const data = new Uint8Array(await file.arrayBuffer());
    const image = IMAGE_TYPES.includes(file.type);
    if (!image && !looksLikeText(data)) {
      notify(`${name} is not an image or a text file, so the agent could not read it`);
      return;
    }
    const limit = image ? IMAGE_LIMIT : FILE_LIMIT;
    if (data.length > limit) {
      notify(`${name} is ${(data.length / 1e6).toFixed(1)} MB, more than ${(limit / 1e6).toFixed(1)} MB`);
      return;
    }
    const hash = await sha256(data);
    counter.current += 1;
    const item = { key: `a${counter.current}`, name, size: data.length, sha256: hash, preview: image ? URL.createObjectURL(file) : null };
    setAttachments((current) => [...current, item]);
    send({ type: "file.attach", name, content_b64: base64(data), sha256: hash });
  };

  const remove = (key: string) =>
    setAttachments((current) => {
      current.filter((item) => item.key === key).forEach((item) => item.preview && URL.revokeObjectURL(item.preview));
      return current.filter((item) => item.key !== key);
    });

  // An upload is done once its attachment.added event names the id a prompt refers to.
  const ids = async (pending: Attachment[]): Promise<string[] | null> => {
    const deadline = Date.now() + WAIT_MS;
    while (Date.now() < deadline) {
      const added = Object.values(projection.state.attachments);
      const found = pending.map((item) => added.find((meta) => meta.sha256 === item.sha256 && meta.owner_id === projection.meId)?.id);
      if (found.every((id) => id !== undefined)) {
        return found as string[];
      }
      await new Promise((resolve) => setTimeout(resolve, 60));
    }
    return null;
  };

  const take = (): Attachment[] => {
    const pending = attachments;
    setAttachments([]);
    return pending;
  };

  return { attachments, add, remove, ids, take, restore: setAttachments };
}
