# Sharing a session

A room is only useful if the people you invite can reach your host. There are three ways, and you choose one in the client: `F2` → Session → *Who can join*. The choice is saved and applies the next time you start `plural`. A fourth, a tunnel, is one command.

| Way | Who can join | What you need |
|---|---|---|
| **This machine** (default) | only you | nothing |
| **Same network** | people on your Wi-Fi, office network or VPN | nothing. The invite link carries your network address, and the host listens on every interface |
| **Over the internet** | anyone with the link | the address of a relay |

With *Over the internet* the host connects out to the relay and so does every guest. Nobody opens a port, which is what makes it work from a home network. The relay only routes frames, it never decides permissions and never stores content. The invite link carries the relay address, so a guest needs no setup.

## Through a tunnel

A tunnel gives your host a public address without a server of your own. One command starts the tunnel, waits for its address and starts the host with it:

```bash
plural --tunnel cloudflared
plural --tunnel ngrok
```

The first lines of the conversation show an invite whose link carries the tunnel address (`wss://…`), so a guest joins with `plural join` or from the browser. When you quit, the tunnel stops with the host.

| | needs | the address |
|---|---|---|
| `cloudflared` | the [`cloudflared`](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) program, no account | new at every start, so old links stop working |
| `ngrok` | the [`ngrok`](https://ngrok.com/download) program and a free account, `ngrok config add-authtoken <token>` once | random on a free plan |

Plural does not install these programs. If one is missing, the command says how to get it.

Two things to know. The tunnel provider terminates TLS, so it can read the traffic: trust it like you would a relay. And your host port is reachable from the internet while the tunnel is up. Only someone who holds the room link, an invite or a token can even ask to come in, and with the default setting nobody sees anything of the room until you let them in. Still, share the link only with the people you mean, and end it with `/invite revoke` if it leaks.

A tunnel suits one person showing a session to a few teammates. For a team that needs a stable link, run a [relay](#the-relay).

## Which way fits

| You want | Run |
|---|---|
| to try it alone | `plural` |
| to show a session to someone on your network | `F2` → Session → Same network, then `plural` |
| to show a session to someone anywhere, now | `plural --tunnel cloudflared` |
| a link that stays the same for your team | a [relay](#the-relay) on Railway, Render or your own server, then `plural --relay wss://…` |
| an agent that keeps running when your laptop is closed | [the host in the cloud](#the-host-in-the-cloud) |
| a host on a home server or a Mac mini | [self-hosting on your own machine](#self-hosting-on-your-own-machine) |

The same choices exist as options for scripts and servers: `--relay <url>` for the internet, `--bind 0.0.0.0 --public-url ws://<your address>:<port>` for the network. Every option can also be an environment variable (`PLURAL_RELAY_URL`, `PLURAL_BIND_HOST`, `PLURAL_PUBLIC_URL`, `PLURAL_PORT`), and a flag wins over a variable. An address given as a flag also wins over the saved choice in the client.

If the relay restarts or the network drops, nothing needs to be done. The host reconnects on its own within a few seconds and takes its room back. Guests see *connection lost, reconnecting…*, keep their seat and carry on. If a tunnel stops, the host shows a warning in the conversation, because the links through it no longer work.

Use a relay you run yourself or one you trust: it sees who connects and when, and the size of every message. Guests use the room link and wait for you to let them in, see [Usage](usage.md#let-people-in).

# Running Plural on a server

A room has two parts that can live anywhere:

- the **relay** routes frames between the host and the people in the room. It never decides permissions and never stores content. Run one per team, or share one.
- the **host** runs the agent with your key and keeps the log. On a server it connects out to the relay, so it needs no public address and no open port.

People join with an invite from the terminal (`plural join "wss://…"`) or from the web client. A web client served over https can only reach a relay over `wss://`, which is why the relay sits behind TLS.

## The relay

### Limits and clean-up

A relay that anyone can reach needs limits, so it has them:

- A room is forgotten 15 minutes after its host left and no one is in it. The host can come back within that time and the room is still its own. After it the room id is free.
- One address can host 3 rooms and bring 30 guests at once, and can open at most 20 connections in a burst and 2 per second after that. A host or a guest over a limit is refused with the close code 4429.
- The relay holds at most 50 rooms.

Behind a proxy every client looks like the proxy. Tell the relay how many proxies are in front of it with `PLURAL_RELAY_PROXY_HOPS` (the images set it to 1, which is right for Caddy, Railway and Render) and it takes the client address from the `X-Forwarded-For` header. Use 0 when the relay is reached directly. If the relay log shows the same `peer=` for different people, raise the number of hops, or raise the limits with `PLURAL_RELAY_MAX_ROOMS`, `PLURAL_RELAY_ROOMS_PER_PEER` and `PLURAL_RELAY_GUESTS_PER_PEER`.

### Teams

A relay can also keep a team directory: who is in which team and the invite codes. Start it with a file for the data:

```bash
plural-host relay --teams /data/teams.db      # or PLURAL_RELAY_TEAMS=/data/teams.db
```

Without it the relay serves no teams. The file holds each team's signing key, so keep it private (plural creates it readable by its owner only) and back it up; losing it means the teams have to be created again. Prompts, replies and files never go to the directory. Anyone who can reach the relay can create a team, at most 3 per address per 10 minutes and 500 in all, so put the relay behind a network rule if it should serve only you. In a container, mount a volume for the file.

For a team that lives only as long as your laptop, `plural team create <name> --tunnel ngrok` starts this relay and a tunnel to it for you, see [usage](usage.md#a-team-on-your-own-machine-behind-a-tunnel).

### Railway

Create a service from this repository and set the variable `RAILWAY_DOCKERFILE_PATH=deploy/relay.Dockerfile`, or point the service's config file at [`deploy/railway/relay.json`](../deploy/railway/relay.json). Generate a domain for it. Railway terminates TLS, so the relay is at `wss://<name>.up.railway.app`. The relay listens on the `PORT` Railway gives it and answers `/healthz`. Set `PLURAL_RELAY_BIND` to change the address it binds, the images set it to `0.0.0.0`.

### Your own server

On a machine with Docker and a domain pointing to it:

```bash
cd deploy
RELAY_DOMAIN=relay.example.com docker compose up -d
```

Caddy gets a certificate from Let's Encrypt and renews it, and the relay is at `wss://relay.example.com`.

### Render

[`render.yaml`](../render.yaml) is a blueprint with the relay as a web service and a host as a worker with a disk.

## The host in the cloud

The image [`deploy/host.Dockerfile`](../deploy/host.Dockerfile) runs a host as a service. Give it a volume at `/data`, which keeps the log, the room, the host key and the workspace across restarts, and these variables:

| variable | |
|---|---|
| `PLURAL_RELAY_URL` | required, for example `wss://relay.example.com` |
| `ANTHROPIC_API_KEY` | or another provider, see [configuration](configuration.md) |
| `GIT_URL` | the repository the agent works on, cloned into the workspace the first time. A token in the URL is removed from the clone's remote |
| `GIT_BRANCH` | optional |
| `PLURAL_ROOM` | optional, a fixed room id. Without it the host picks one and keeps it in `/data/room` |
| `PLURAL_HOST_NAME` | optional, the name the room sees |

When it starts, the host prints the room, the room link and the host link to its log. Start it with `PLURAL_ADMISSION=open` if nobody is there to let people in, and keep the link private then. Open the host link in the web client or with `plural join` to approve actions and create more invites. Anyone who can read the log can become the host, so keep the logs private.

- **Railway:** a service with `RAILWAY_DOCKERFILE_PATH=deploy/host.Dockerfile` (or [`deploy/railway/host.json`](../deploy/railway/host.json)) and a volume at `/data`.
- **Render:** the `plural-host` worker in [`render.yaml`](../render.yaml).
- **Any VM:** [`deploy/cloud-init.yaml`](../deploy/cloud-init.yaml) installs Docker, builds the image and runs it. Fill in the three values at the top.

The image runs as an unprivileged user and has git, ssh, curl and ripgrep. A project that needs another toolchain, such as Node or Go, builds its own image `FROM` this one.

## Self-hosting on your own machine

A Mac mini, a home server or any box you can shell into. Install Plural with `install.sh`, then keep the host running as a service with a fixed room:

```bash
mkdir -p ~/.config/plural
cat > ~/.config/plural/host.env <<'ENV'
PLURAL_RELAY_URL=wss://relay.example.com
PLURAL_ROOM=r_team
PLURAL_WORKSPACE=/home/you/project
ANTHROPIC_API_KEY=sk-ant-...
ENV
chmod 600 ~/.config/plural/host.env
```

- **Linux:** copy [`deploy/systemd/plural-host.service`](../deploy/systemd/plural-host.service) to `~/.config/systemd/user/`, then `systemctl --user enable --now plural-host`. The links are in `journalctl --user -u plural-host`.
- **macOS:** copy [`deploy/launchd/dev.plural.host.plist`](../deploy/launchd/dev.plural.host.plist) to `~/Library/LaunchAgents/`, then `launchctl load ~/Library/LaunchAgents/dev.plural.host.plist`. The links are in `~/Library/Logs/plural-host.log`, readable only by you.

The room id stays the same across restarts, so the log and the session continue where they were.
