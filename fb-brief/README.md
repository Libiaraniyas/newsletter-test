# F&B Daily Brief — Proof of Concept

A GitHub Action that collects F&B news, uses Claude to keep **only**
strategically important stories, and sends them to a WhatsApp group via Green API.

## How it works

```
GitHub Actions (manual "Run workflow" button)
   → collect candidates from RSS feeds (sources.json, incl. Hebrew)
   → drop URLs already sent (sent.json)
   → ONE Claude call → clean JSON of selected articles
   → if none qualify: send nothing (a quiet day is fine)
   → send selected articles to WhatsApp (Green API)
   → remember what was sent (sent.json) so a story never repeats
```

## The two rules (in `brief.py` → `RULES`)

1. **Strict quality.** Only major moves: a company entering a new category,
   large M&A, meaningful market-share shifts, significant Israeli-player moves.
   Mediocre articles are rejected. One great article is a full brief. Zero is valid.
2. **No repeats, by story (not URL).** The same story is never sent twice — not
   from another source, not reworded. The only exception is a *major new development*.

## One-time setup

Add these under **Repo → Settings → Secrets and variables → Actions → Secrets**:

| Secret name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | your Anthropic API key (`sk-ant-...`) |
| `GREEN_API_INSTANCE` | your Green API instance id (e.g. `710722706469`) |
| `GREEN_API_TOKEN` | your Green API token (`apiTokenInstance`) |
| `GREEN_API_CHAT_ID` | the WhatsApp group id (e.g. `1203634...@g.us`) |

Optional: under **Variables**, set `CLAUDE_MODEL` to change the model
(default `claude-sonnet-5`).

## Running the POC

1. Open the **Actions** tab → **F&B Daily Brief** → **Run workflow**.
2. Leave "test_mode" on for the first run — you'll get a WhatsApp message even
   if nothing qualifies, confirming the pipeline works end-to-end.
3. Check the run logs to see which feeds returned candidates and what Claude picked.

> The "Run workflow" button only appears once this workflow is on the
> repository's **default branch**.

## Going to production (after the POC)

- Add a `schedule:` trigger (e.g. 07:00 / 12:00 / 17:00 / 22:00 Israel time).
- Add more sources to `sources.json` (Hebrew RSS: Globes, Calcalist, TheMarker).
- Turn off `test_mode` so quiet days stay silent.
