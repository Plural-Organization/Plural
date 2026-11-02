import { readFile, stat } from "node:fs/promises";
import { homedir } from "node:os";

const IMAGE_EXTENSION = /\.(png|jpe?g|gif|webp)$/i;

/**
 * The image file a paste names, when it names one: a file dragged into the terminal or copied in Finder
 * arrives as its path, quoted, with escaped spaces or as a file:// URL depending on the terminal.
 */
export function imagePath(text: string): string | null {
  let path = text.trim();
  if (path === "" || path.includes("\n")) {
    return null;
  }
  const quoted = path.length > 1 && (path[0] === "'" || path[0] === '"') && path.at(-1) === path[0];
  path = quoted ? path.slice(1, -1) : path.replace(/\\(.)/g, "$1");
  if (path.startsWith("file://")) {
    try {
      path = decodeURIComponent(new URL(path).pathname);
    } catch {
      return null;
    }
  }
  if (path.startsWith("~/")) {
    path = homedir() + path.slice(1);
  }
  return path.startsWith("/") && IMAGE_EXTENSION.test(path) ? path : null;
}

/** The kind of image the bytes hold, the same check the host makes. */
export function imageKind(data: Uint8Array): "png" | "jpg" | "gif" | "webp" | null {
  const head = Buffer.from(data.subarray(0, 12));
  if (head.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) {
    return "png";
  }
  if (head[0] === 0xff && head[1] === 0xd8 && head[2] === 0xff) {
    return "jpg";
  }
  const ascii = head.toString("latin1");
  if (ascii.startsWith("GIF87a") || ascii.startsWith("GIF89a")) {
    return "gif";
  }
  return ascii.startsWith("RIFF") && ascii.slice(8, 12) === "WEBP" ? "webp" : null;
}

/** The bytes of an image file, or null when it is missing, not a file or not an image. */
export async function readImageFile(path: string): Promise<Buffer | null> {
  try {
    if (!(await stat(path)).isFile()) {
      return null;
    }
    const data = await readFile(path);
    return imageKind(data) === null ? null : data;
  } catch {
    return null;
  }
}
