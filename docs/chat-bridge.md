# Sessions in a chat app

A bot can bring your sessions into Telegram or Discord: mention it in a group and the agent of the session that chat follows answers there, with its steps, its streaming reply and buttons for the things it asks you to allow. Other services use the same bridge: a service is one module and one entry in the list of providers.

The bridge runs on the computer where your sessions run, next to them. It needs no server of yours and no open port: it polls Telegram, holds a gateway connection to Discord, and joins the sessions the way the terminal does.

## Set it up

Chat apps are set up on the host's computer, in any of three places. They all write the same settings, so use whichever you have open.

- **Web client:** Room settings → *Chat apps* (needs `plural daemon` running).
- **Terminal client:** settings (`F2`) → *Chat apps*.
- **Command line:** `plural bridge list`, `plural bridge set telegram`, `plural bridge test telegram`, `plural bridge remove telegram`.

Each service shows what to do in it first (Telegram: [@BotFather](https://t.me/BotFather) → `/newbot`; Discord: Developer Portal → application → Bot, with *Message Content Intent* turned on), then asks for the bot's token. **Test** connects once and tells you the bot's name without saving anything; **Save and connect** keeps the token on your computer and connects at once.

1. Add a service and save. The status shows *Connected* with the bot's name.
2. The settings show a pairing code. Send `/pair <code>` to the bot in a **private** chat: that makes you its owner. *Add another owner* shows a new code.
3. Start `plural` in a project folder as usual.
4. Add the bot to a group or server, or stay in the private chat, and send `/link`. Pick the session from the buttons.

Something has to run the bridges: `plural daemon` does it for as long as it runs, and `plural bridge run` does it without the daemon. If neither runs, the settings say *Waiting to start*. Only one process on a computer runs them (the other only edits the settings), so a token is never read twice. A change made in any place reaches the running bridge within a couple of seconds.

To try a bot once without saving anything: `plural bridge telegram --token <token>` or `plural bridge discord --token <token>`.

From then on, start a message with its name (`plural, how does auth work?`), mention it (`@your_bot …`), reply to one of its messages or use `/ask <text>`. The names are `plural`, `плюрал`, `плурал` and the bot's own name; the *Names that call the bot* setting replaces them. In a private chat every message goes to the agent.

## One bot, many chats and sessions

- Each service runs one bot, and the bot serves every chat it is in. Telegram and Discord can run side by side, and a session can be followed from both.
- A chat follows one session at a time. In a Telegram group with topics, each topic is a chat of its own, so one group can follow several sessions, a topic each. On Discord a channel (or a thread, which is a channel of its own) is a chat.
- Several chats can follow the same session, and the terminal and the web client keep working alongside them. What happens in the session shows up in every chat that follows it, whoever asked.
- A link survives restarts: when the session's host stops, the chat says so, and when `plural -c` brings the session back, the chat follows it again on its own.

## Who can do what

| | an owner | anyone else in the chat |
|---|---|---|
| ask the agent | yes, as the host | yes, as a guest under their own name |
| answer what the agent asks to allow | yes, with the buttons | no |
| `/link`, `/unlink`, `/stop` | yes | no |

A guest's prompt is treated like any guest's: the commands and writes it leads to wait for an owner's answer, whatever the permission mode. So anyone in the group can ask questions, and nothing changes on your computer unless an owner presses **Allow**.

## In the chat

- **A reply** is a rich message. While the agent works, a Telegram private chat shows Telegram's own *Thinking…* draft with a stop button; a group, and every Discord channel, shows the message growing, edited every couple of seconds, with a **Stop** button for owners. A Discord reply over 2000 characters continues in a second message.
- **Steps** the agent took fold into a block at the top of the reply that opens on a tap (Telegram), or sit in a short list of the last few (Discord).
- **A request to allow** something is a message of its own with **Allow**, **Always** and **Reject**, or **Read** and **Read and write** for a folder outside the project. Once answered, it says who answered and how.
- **The rest of the group's talk** goes to the session's chat, under each person's name. The agent does not answer it, but reads it before its next answer, so "what did we decide about the deploy?" works. It needs the bot to see every message: make it an admin of the group or turn privacy mode off in @BotFather (`/setprivacy` → Disable). With privacy mode on it sees only commands and replies to it. Like a guest's prompt, a guest's message makes the next run a guest turn, so writes and commands in it wait for an owner.

## Commands

| | |
|---|---|
| `/link` | pick a running session for this chat |
| `/unlink` | stop following it here |
| `/status` | which session this chat follows, and whether it is running |
| `/stop` | stop the agent's current run |
| `/ask <text>` | send a prompt without a mention |
| `/pair <code>` | become an owner (private chat only) |

On Discord they are slash commands, which the bot registers when it connects. Nothing the agent writes can ping anyone: the bot sends every message with mentions turned off.

## What to know

- The token is a secret: anyone with it can read what the bot reads. It lives in `~/.plural/bridge/config.json`, readable by you only, and is never logged. The settings screens and the daemon never send it back: they say only that one is saved. Terminal and command-line changes pass it on standard input, never in the arguments.
- What the agent writes goes through the chat service's servers, like any message in the chat. Don't link a chat to a session whose code must not leave your company.
- Owners and links are in `~/.plural/bridge/<service>.json`, also readable by you only. Each running host leaves a file with its host link in `~/.plural/running/` while it runs, so the bridge can offer it in `/link`; it is as private as the host key next to it.
- One bot, one reader: Telegram hands a bot's updates to one reader, so a second program with the same token stops with an error. Discord's bot needs *Message Content Intent*; without it the bridge says so instead of hearing nothing.
- A bridge that loses the network tries again with a growing pause. One that the service refuses (a revoked token) stops and shows why, so it does not keep knocking.

## Adding a service

A service is two things, and no screen changes:

1. A module in `plural/bridge/` with a class that implements `ChatPlatform` (`platform.py`): it turns the service's updates into `Said` and `Pressed`, and turns `Answer` and `Notice` into the service's messages. `live.py` gives a message that is edited as the agent works, with the service's rate limits.
2. A `Provider` in `providers.py`: its name, what to do in the service, the fields it needs (marked secret or not) and how to build the platform from them. The web client, the terminal and the command line draw their forms from this description.
