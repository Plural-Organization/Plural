import { inboxRequests, participantName, type InboxRequest, type PluginAsked } from "@plural/client";

// What waits for the host lives in @plural/client, for this client and the terminal one; the web adds a plugin's question.
export type InboxItem = InboxRequest | { kind: "plugin"; id: string; ask: PluginAsked };

export { inboxRequests as inboxItems, participantName as nameOf };

export function askItems(asks: PluginAsked[]): InboxItem[] {
  return asks.map((ask): InboxItem => ({ kind: "plugin", id: ask.ask_id, ask }));
}
