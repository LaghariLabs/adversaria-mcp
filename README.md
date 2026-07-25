# Adversaria MCP server

**Sovereign-first, read-only access to your local meeting notes + to-dos over the
[Model Context Protocol](https://modelcontextprotocol.io).**

It runs **on your machine**, reads the same on-device `meetings.db` the desktop app
writes (opened **read-only**), and makes **no network calls of its own**. Your data
only ever leaves your device if *you* connect it to a cloud model — that choice is
yours. Connect it to **Claude Desktop, Claude Code, an OpenAI-compatible client, a
local LLM**, or anything else that speaks MCP.

## Tools

| Tool | What it returns |
|---|---|
| `list_recent_meetings(limit=20)` | Recent meetings (id, title, date, duration, attendees, tags, snippet) |
| `search_meetings(query, limit=20)` | Meetings matching title/summary/transcript |
| `get_meeting(meeting_id)` | Full notes: summary (markdown), transcript, personal notes, attendees |
| `get_action_items(status="open", limit=100)` | Your to-dos across meetings. `status`: `open` · `done` · `overdue` · `today` · `all` |

The generic dual-capture speaker labels (`Me`/`Them`) are stripped from titles,
attendees, and transcripts — real names are kept.

## Run it

Requires [`uv`](https://docs.astral.sh/uv/) (or any way to run a Python package).

```sh
# From this directory — starts the stdio server (it waits for an MCP client):
uv run adversaria-mcp
```

By default it reads the desktop app's database:
- macOS: `~/Library/Application Support/meeting-note-taker/meetings.db`
- Windows: `%APPDATA%\meeting-note-taker\meetings.db`

Override with the `ADVERSARIA_DB` environment variable if your DB is elsewhere.

> **If you turned on encryption at rest** in Adversaria's settings, the database is
> SQLCipher-encrypted and this server cannot open it — it uses plain SQLite, so
> you'll get a "file is not a database" error. Encryption is off by default;
> support for the encrypted path isn't implemented yet.

## Connect a client

**Claude Desktop** — add to `claude_desktop_config.json`
(`~/Library/Application Support/Claude/` on macOS):

```json
{
  "mcpServers": {
    "adversaria": {
      "command": "uv",
      "args": ["run", "--directory", "/ABSOLUTE/PATH/TO/mcp-server", "adversaria-mcp"]
    }
  }
}
```

Restart Claude Desktop; you'll see the Adversaria tools available. Then ask things
like *"What are my open to-dos?"* or *"Summarize my meetings with Hamza this week."*

**Claude Code**

```sh
claude mcp add adversaria -- uv run --directory /ABSOLUTE/PATH/TO/mcp-server adversaria-mcp
```

**Other clients (OpenAI, local LLMs, etc.)** — point any MCP-capable client at the
same `command`/`args` (stdio transport). MCP client support across local-LLM tools
varies and is evolving, so check your client's MCP docs.

## Privacy

The server is local and read-only. It never writes to your data and never phones
home. When you query through a **cloud** model (e.g. Claude Desktop), the meeting
content the tools return is sent to that provider as part of your request — same as
pasting it into a chat. For a fully on-device loop, use a local-LLM MCP client.
