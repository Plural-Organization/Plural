# Running Plural on a server

A room has two parts that can live anywhere:

- the **relay** routes frames between the host and the people in the room. It never decides permissions and never stores content. Run one per team, or share one.
- the **host** runs the agent with your key and keeps the log. On a server it connects out to the relay, so it needs no public address and no open port.

People join with an invite from the terminal (`plural join "wss://…"`) or from the web client. A web client served over https can only reach a relay over `wss://`, which is why the relay sits behind TLS.

## The relay

### Railway

Create a service from this repository and set the variable `RAILWAY_DOCKERFILE_PATH=deploy/relay.Dockerfile`, or point the service's config file at [`deploy/railway/relay.json`](../deploy/railway/relay.json). Generate a domain for it. Railway terminates TLS, so the relay is at `wss://<name>.up.railway.app`. The relay listens on the `PORT` Railway gives it and answers `/healthz`.

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

When it starts, the host prints the room, a one-time guest link and the host link to its log. Open the host link in the web client or with `plural join` to approve actions and create more invites. Anyone who can read the log can become the host, so keep the logs private.

- **Railway:** a service with `RAILWAY_DOCKERFILE_PATH=deploy/host.Dockerfile` (or [`deploy/railway/host.json`](../deploy/railway/host.json)) and a volume at `/data`.
- **Render:** the `plural-host` worker in [`render.yaml`](../render.yaml).
- **Any VM:** [`deploy/cloud-init.yaml`](../deploy/cloud-init.yaml) installs Docker, builds the image and runs it. Fill in the three values at the top.

The image has git, ssh, curl and ripgrep. A project that needs another toolchain, such as Node or Go, builds its own image `FROM` this one.

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
- **macOS:** copy [`deploy/launchd/dev.plural.host.plist`](../deploy/launchd/dev.plural.host.plist) to `~/Library/LaunchAgents/`, then `launchctl load ~/Library/LaunchAgents/dev.plural.host.plist`. The links are in `/tmp/plural-host.log`.

The room id stays the same across restarts, so the log and the session continue where they were.
