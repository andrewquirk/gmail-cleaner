# gmail-cleaner

A Claude-powered agent that tidies your Gmail inbox: archives newsletters and promotions, trashes obvious junk, and tells you who to unsubscribe from.

**Safe by default**

- **Dry-run unless you pass `--apply`.** The agent proposes; nothing changes.
- **Never permanently deletes.** Actions are archive, label, or move to Trash (recoverable for 30 days). The OAuth scope (`gmail.modify`) can't delete permanently or send mail.
- **Safety rules live in code, not the prompt.** Starred mail and protected senders are always skipped, the agent can only act on message IDs it actually saw in a search, and `max_actions` caps each run.
- **Metadata only.** The agent sees sender, subject, date, and snippet, never message bodies, and is told to treat those as untrusted (prompt-injection defense).
- **Audit log.** Every action is appended to `actions.jsonl`.

## Setup

1. **Create a Google OAuth client**
   - In the [Google Cloud Console](https://console.cloud.google.com/), create a project and enable the **Gmail API**.
   - Configure the OAuth consent screen (External, add yourself as a test user).
   - Create credentials → **OAuth client ID** → **Desktop app**. Download the JSON as `credentials.json` into the directory you'll run from.
2. **Get an Anthropic API key** and export it: `export ANTHROPIC_API_KEY=...`
3. **Install**
   ```bash
   uv sync            # or: pip install -e ".[dev]"
   ```

## Usage

### Delete everything from specific senders (no LLM)

```bash
uv run gmail-cleaner delete news@shop.com @spammy-domain.com           # preview
uv run gmail-cleaner delete --from-file senders.txt --apply            # move to Trash
```

Finds *all* mail from each sender (addresses or whole domains) and moves it to Trash. Starred mail is skipped. `--limit N` caps messages per sender. Nothing needs an Anthropic key.

### Let Claude decide (agent mode)

```bash
cp examples/config.example.yaml config.yaml   # edit protected senders + preferences

uv run gmail-cleaner run --config config.yaml            # dry run
uv run gmail-cleaner run --config config.yaml --apply    # for real
```

The first run opens a browser for Google consent and stores `token.json` (mode 600). Both `credentials.json` and `token.json` are gitignored. **Never commit them.**

## How it works

```
cli.py → agent.py (Claude + tool runner) → tools.py → session.py (safety rules) → gmail.py → Gmail API
```

Claude gets four tools: `search_messages`, `archive_messages`, `trash_messages`, `label_messages`. It surveys the inbox, groups mail by sender or category, and acts in batches. Every mutation passes through `Session.act()`, which enforces the rules above.

## Development

```bash
uv run pytest
uv run ruff check .
```

Tests use a fake Gmail client, so no credentials are needed.

## Disclaimer

This tool modifies your mailbox. Start with a dry run, review `actions.jsonl`, and use `--max-actions` for your first real run. Provided as-is under the MIT license.
