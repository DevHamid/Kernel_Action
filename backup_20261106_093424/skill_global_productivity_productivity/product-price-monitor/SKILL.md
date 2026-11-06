---
name: product-price-monitor
description: "Watch product, flight, or listing prices; alert on target."
version: 0.1.0
author: Ben Barclay (benbarclay), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Prices, Availability, Shopping, Travel, Alerts]
    related_skills: [maps]
---

# Product Price Monitor

Monitor a concrete purchasable item and alert on a normalized all-in price or availability condition. Handle variants, taxes, fees, currencies, stock, cancellation terms, and duplicate alerts explicitly. Setup runs once in the foreground; the recurring check runs as a `cronjob` tick (the `price-watch` automation blueprint scaffolds this).

## When to Use

- "Alert me when this laptop drops below $1,000."
- "Watch these flights for a fare under $500."
- "Tell me when this hotel has a refundable room."
- "Track ticket/listing availability."
- A cron tick fires for an existing price watch (steps 4-6).

Don't use for: one-off "what does this cost right now" lookups (use `web_search`/`web_extract` directly).

## Procedure — Setup (foreground, once)

### 1. Define the exact item

Record source URL/provider, product/listing ID where available, variant, quantity, location, dates, travelers/guests, membership/login assumptions, condition, seller, and acceptable substitutes. Done when two variants cannot be confused.

### 2. Define the alert condition

Specify currency, all-in vs pre-tax price, maximum price, availability/stock rule, shipping, refundability, cabin/room/ticket class, cooldown, and notification destination. Done when synthetic examples have deterministic alert decisions.

### 3. Establish a live baseline, then schedule

Fetch a bounded live result with `web_extract` or `browser_navigate` and record retrieval time, source price, fees/taxes, availability, and terms. Do not schedule until one foreground fetch works. Write the watch contract (item, condition, baseline observation) to a state file under `~/.hermes/price-watches/<watch-slug>.json`, then create the job:

```
cronjob(action="create",
        schedule="every 6h",
        prompt="Load the product-price-monitor skill and run the tick for the watch contract at ~/.hermes/price-watches/<watch-slug>.json.",
        deliver=<user's destination>)
```

Pick a cadence that respects rate limits and site terms. Pin the job to the known-good model of a working sibling watch (same provider + base_url) so it survives main-agent model switches — see the model-routing pitfall below. Done when the baseline matches the exact item contract and the job exists.

## Procedure — Tick (each scheduled run)

### 4. Fetch and normalize

Re-fetch the source. Convert currency only with a timestamped rate and retain the source currency. Separate base price, mandatory fees, shipping/taxes, total, and availability. Exclude volatile page metadata. A failed fetch means unknown state: report or skip, but never overwrite the last good observation with an error page. Done when the observation is comparable to the baseline or explicitly marked failed.

### 5. Compare and suppress duplicates

Alert on threshold entry, qualifying availability, material lower price, or recovery as requested. Store the last good observation and last alert fingerprint in the state file. Replaying the same offer must send no second alert; respect the cooldown. Done when the alert decision is deterministic against stored state.

### 6. Deliver or stay silent

When a condition is met, the alert includes: exact item/variant, observed all-in price and source currency, availability/terms, threshold, retrieval timestamp, source link, and important uncertainty. Never claim inventory is reserved. When nothing qualifies, stay silent — no "still watching" noise unless a periodic all-clear was requested. Done when the state file reflects this run.

### 7. Retire a dead listing (store closed / delisted / sold)

When the user confirms a reported listing is gone (sold, store closed, delisted), it must be suppressed in TWO places — a state-file entry alone does not stop re-alerts because each tick runs autonomously with only its prompt and the duplicate-suppression fingerprint keys on url+price:

1. Add the exact URL to the state file's `dead_listings` array (`~/.hermes/price-watches/<watch-slug>.json`). Patch the JSON in place.
2. Update the cron job's prompt via `cronjob_manage` (action=update, job_id from the last `cronjob_manage list`) with a line: DEAD LISTING: <url> (<title>, <price>, <seller>) is <sold/AWAY> — treat it as a dead listing, never report or re-alert on it.

Done when both the state file and the job prompt carry the URL. Confirm by firing `cronjob_manage` (action=run) once and checking the run does not re-report it.

## Pitfalls

- Comparing a base fare with an all-in threshold.
- Alerting on the wrong size, seller, cabin, dates, or room terms.
- Overwriting a last-known-good value with an error page.
- Polling aggressively enough to trigger blocking or violate site terms.
- Scheduling before a single foreground fetch has succeeded.
- Creating the tick job without a state file while the prompt references one — the tick burns its run returning 'no baseline/contract'; either write the contract file first (step 3) or embed the baseline observation inline in the tick prompt so the run is self-sufficient.
- For used-phone marketplace watches (Tokopedia/Shopee/OLX/Carousell Indonesia), leaving out exclusion filters — bypass, wifi-only, icloud-lock, simlock, Mi-account-locked, and parts-only listings flood alerts with unusable units; pin ONLY physical/functional minus in the alert condition.
- A keyless web search provider connection reset stops provider-ring failover before fallback providers are tried — the watch search fails entirely. When a tick fails web search, mark the connection-reset provider tier `paid` (e.g. `hermes config set web.provider_tier.firecrawl paid`) so it is excluded from the keyless ring and the walk proceeds to the next provider. Do not hand-edit config.yaml — use `hermes config set KEY VAL`.
- When a listing is confirmed dead (store closed, delisted, sold), do BOTH steps in §Retire a dead listing: record the URL in the state file's `dead_listings` array AND pin it as dead in the cron job's prompt. The state-file entry alone does not suppress re-alerts: the duplicate-suppression fingerprint keys on url+price, and each tick runs autonomously with only its prompt.
- A watch job that dies with `interrupted` (or `RuntimeError: HTTP 400 ... INVALID_MODEL_ID`) and an empty or one-line output file is a model-routing failure, NOT a listing result — the run never reached the search step. Two causes: the pinned model name went stale on the provider (renamed/removed), or the job carries no pin at all (`model`/`provider`/`base_url` null in `/opt/data/cron/jobs.json`) and therefore inherits the main agent's current model, which breaks every time the user switches models. Diagnose by reading the stored job's `model`/`provider`/`base_url` and comparing against a working sibling watch job (siblings share provider + base_url; a working sibling's values are the known-good set). Fix with `hermes cron edit <id> --model <sibling-model> --provider <sibling-provider>` (`--pin` locks the current main-agent model instead), restore a null `base_url` in the jobs JSON, then verify with `hermes cron run <id>` → `hermes cron runs <id>` (last run `completed`, `failure_streak` back to 0). On this host the watch set runs `mercury-3/mercury-3` via `custom:9router` at `http://192.168.1.1:20128/v1`.
- A direct `hermes cron run` can fail once with `GatewayClientError: Gateway connection failed; no local fallback` while the gateway is actually healthy — the attempt is recorded `failed` with an empty output file even though nothing is wrong with the job. Before concluding a job is broken, check `hermes gateway status` and the gateway heartbeat file; if the gateway is up, re-run the job as a tracked background process (a full watch tick takes ~5 minutes) and judge health by the next `hermes cron runs <id>` row, never by the first failed attempt. On hosts where the CLI is not on PATH, `export PATH=$PATH:/opt/hermes/bin` before any `hermes cron ...` command.
- Marketplace page extraction is per-site, not global: one marketplace (e.g. Shopee) can be blocked by the web-extract SSRF guard ("Blocked: URL targets a private or internal network address") while others on the same run extract fine. Use `web_search` first for every site — snippets carry live prices and work even where page extract is blocked; then `web_extract` only the sites that extract cleanly. Never fail the whole watch run because one site's page extract is blocked — degrade to its search snippets instead. Test each site's extract once in the foreground before relying on it.
- BigGo is the Shopee fallback source: BigGo's own page extract is also SSRF-blocked, but its search-result snippets (via `web_search` with `site:biggo.id` + brand/variant/model terms) surface Shopee minus listings with price, variant (RAM/storage), and the Shopee product/page IDs embedded in the snippet links. Use those snippets when the direct Shopee page and the BigGo page both refuse extraction; treat their availability as unverified until the listing is confirmed live.
- When the user wants watch alerts out of their own DM ("keep my private message clean"), route the job's delivery to a group thread with the `platform:chat_id:thread_id` grammar: `deliver="telegram:-1003628710660:10669"` (group id, not the DM chat id). Update ALL sibling watch jobs that should move together in one parallel batch (`cronjob_manage` action=update per job_id) and confirm each returned job shows the new `deliver`; a job left on origin keeps posting to the DM.
- Marketplace source viability is source-specific: Facebook Marketplace is NOT a usable watch source — login-walled, JS-rendered, not indexed by aggregators like BigGo, and has no headless snippet/extract path for a cron tick. Do not promise a daily listing source with no verification path; if the user asks, state the blocker and offer a separate browser-based job instead of treating it as a drop-in addition to the snippet-based watch set.
- Thresholds are strict inequalities: a user's "under RpX" / "below RpX" means price < X, and a listing sitting exactly at the cap does NOT qualify. Record the comparison as strict in the alert condition and say so in the baseline so a future tick does not misreport an at-threshold listing as a hit.

## Verification

- [ ] The watch contract pins the item so two variants cannot be confused.
- [ ] One foreground fetch succeeded before any job was created.
- [ ] The job carries an explicit model/provider/base_url pin matching a working sibling watch.
- [ ] Alert decisions replay deterministically from the state file; duplicates suppressed.
- [ ] Failed fetches never replaced last-known-good state.
- [ ] Alerts carry all-in price, source currency, timestamp, and source link.
