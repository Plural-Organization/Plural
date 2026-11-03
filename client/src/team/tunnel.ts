// Hosts of tunnels that open for one session. Their address changes at every start and a team made on one
// ends with it. A tunnel of your own, on a domain of yours, is not on this list. The host command keeps
// the same list (src/plural/host/team.py), and team-vectors.json checks both.
const TUNNEL_SUFFIXES = [".trycloudflare.com", ".ngrok-free.app", ".ngrok-free.dev", ".ngrok.app", ".ngrok.dev", ".ngrok.io", ".loca.lt"];
// What a tunnel provider answers for an address nothing listens on any more.
export const TUNNEL_GONE: ReadonlySet<number> = new Set([404, 502, 503, 504, 530]);

export function isTunnelHost(host: string): boolean {
  const name = host.toLowerCase().split(":")[0] ?? "";
  return TUNNEL_SUFFIXES.some((suffix) => name.endsWith(suffix));
}

export function closedTunnel(host: string): string {
  return `the tunnel ${host} is closed, and the team on it ended with it. Ask the team owner to start it again and send a new invite`;
}
