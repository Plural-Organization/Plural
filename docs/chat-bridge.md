# Sessions in a chat app

A bot can bring your sessions into Telegram: mention it in a group and the agent of the session that group follows answers there, with its steps, its streaming reply and buttons for the things it asks you to allow. Slack and others will use the same bridge.

The bridge runs on the computer where your sessions run, next to them. It needs no server of yours and no open port: it polls Telegram and joins the sessions the way the terminal does.

## Set it up

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy its token.
2. Start the bridge on the host's computer and leave it running:

   ```bash
   PLURAL_TELEGRAM_TOKEN=<token> plural bridge telegram
   ```

   The first time, it prints a code. Send `/pair <code>` to your bot in a private chat: that makes you its owner. `plural bridge telegram --pair` prints a new code to add another owner.
3. Start `plural` in a project folder as usual.
4. Add the bot to a group, or stay in the private chat, and send `/link`. Pick the session from the buttons.

From then on, start a message with its name (`plural, how does auth work?`), mention it (`@your_bot …`), reply to one of its messages or use `/ask <text>`. The names are `plural`, `плюрал`, `плурал` and the bot's own first name; `--name` replaces them. In a private chat every message goes to the agent.

## One bot, many chats and sessions

- One bridge runs one bot, and the bot serves every chat it is in.
- A chat follows one session at a time. In a group with topics, each topic is a chat of its own, so one group can follow several sessions, a topic each.
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

- **A reply** is a rich message. While the agent works, a private chat shows Telegram's own *Thinking…* draft with a stop button; a group shows the message growing, edited every couple of seconds, with a **Stop** button for owners.
- **Steps** the agent took fold into a block at the top of the reply that opens on a tap.
- **A request to allow** something is a message of its own with **Allow**, **Always** and **Reject**, or **Read** and **Read and write** for a folder outside the project. Once answered, it says who answered and how.
- The bot only reads messages meant for it. With Telegram's privacy mode on (the default) a bot in a group receives commands and replies to it; if mentions don't reach it, turn privacy mode off in @BotFather or use `/ask`.

## Commands

| | |
|---|---|
| `/link` | pick a running session for this chat |
| `/unlink` | stop following it here |
| `/status` | which session this chat follows, and whether it is running |
| `/stop` | stop the agent's current run |
| `/ask <text>` | send a prompt without a mention |
| `/pair <code>` | become an owner (private chat only) |

## What to know

- The token is a secret: anyone with it can read what the bot reads. The bridge never logs it. Keep it in an environment variable or a secret manager, not in a shell history you share.
- What the agent writes goes through Telegram's servers, like any message in the chat. Don't link a chat to a session whose code must not leave your company.
- The bridge keeps its owners and links in `~/.plural/bridge/telegram.json`, readable by you only. Each running host leaves a file with its host link in `~/.plural/running/` while it runs, so the bridge can offer it in `/link`; it is as private as the host key next to it.
- One bot, one bridge: Telegram hands a bot's updates to one reader, so a second bridge with the same token stops with an error.
