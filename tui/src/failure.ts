import { CommandRejected } from "@plural/client";

export function explain(error: unknown): string {
  if (error instanceof CommandRejected) {
    const message = error.error.message;
    switch (error.error.code) {
      case "unauthorized":
        if (/invite/i.test(message)) {
          return "this invite link was already used or has expired. Ask the host for a new one, they get it with /invite";
        }
        if (/revoked/i.test(message)) {
          return "the host removed you from this session. Ask for a new invite";
        }
        return `your access to this session is not valid any more (${message}). Ask the host for a new invite`;
      case "forbidden":
        return `the host does not allow this: ${message}`;
      case "version_mismatch":
        return "this plural and the host speak different protocol versions. Update both with plural update";
      default:
        return `${error.error.code}: ${message}`;
    }
  }
  return error instanceof Error ? error.message : String(error);
}
