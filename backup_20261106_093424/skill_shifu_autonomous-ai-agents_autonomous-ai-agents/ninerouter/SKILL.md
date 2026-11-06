---
name: 9router
description: Entry point for 9Router — local/remote AI gateway with OpenAI-compatible REST for chat, image, TTS, embeddings, web search, web fetch. Use when the user mentions 9Router, NINEROUTER_URL, or wants AI without writing provider boilerplate. This skill covers setup + indexes capability skills; fetch the relevant capability SKILL.md from the URLs below when needed.
---

# 9Router

Local/remote AI gateway exposing OpenAI-compatible REST. One key, many providers, auto-fallback.

## Setup

```bash
export NINEROUTER_URL="http://localhost:20128"      # or VPS / tunnel URL
export NINEROUTER_KEY="sk-..."                      # from Dashboard → Keys (only if requireApiKey=true)
```

All requests: `${NINEROUTER_URL}/v1/...` with header `Authorization: Bearer ${NINEROUTER_KEY}` (omit if auth disabled).

Verify: `curl $NINEROUTER_URL/api/health` → `{"ok":true}`

## Discover models

```bash
curl $NINEROUTER_URL/v1/models                  # chat/LLM (default)
curl $NINEROUTER_URL/v1/models/image            # image-gen
curl $NINEROUTER_URL/v1/models/tts              # text-to-speech
curl $NINEROUTER_URL/v1/models/embedding        # embeddings
curl $NINEROUTER_URL/v1/models/web              # web search + fetch (entries have `kind` field)
curl $NINEROUTER_URL/v1/models/stt              # speech-to-text
curl $NINEROUTER_URL/v1/models/image-to-text    # vision
```

Use `data[].id` as `model` field in requests. Combos appear with `owned_by:"combo"`.

Response shape:
```json
{ "object": "list", "data": [
  { "id": "openai/gpt-5", "object": "model", "owned_by": "openai", "created": 1735000000 },
  { "id": "tavily/search", "object": "model", "kind": "webSearch", "owned_by": "tavily", "created": 1735000000 }
]}
```

## Capability skills

When the user needs a specific capability, fetch that skill's `SKILL.md` from its raw URL:

| Capability | Raw URL |
|---|---|
| Chat / code-gen | https://raw.githubusercontent.com/decolua/9router/refs/heads/master/skills/9router-chat/SKILL.md |
| Image generation | https://raw.githubusercontent.com/decolua/9router/refs/heads/master/skills/9router-image/SKILL.md |
| Text-to-speech | https://raw.githubusercontent.com/decolua/9router/refs/heads/master/skills/9router-tts/SKILL.md |
| Speech-to-text | https://raw.githubusercontent.com/decolua/9router/refs/heads/master/skills/9router-stt/SKILL.md |
| Embeddings | https://raw.githubusercontent.com/decolua/9router/refs/heads/master/skills/9router-embeddings/SKILL.md |
| Web search | https://raw.githubusercontent.com/decolua/9router/refs/heads/master/skills/9router-web-search/SKILL.md |
| Web fetch (URL → markdown) | https://raw.githubusercontent.com/decolua/9router/refs/heads/master/skills/9router-web-fetch/SKILL.md |

## Combos & routing strategy

A combo is a named model that fans out to member models. Strategy is per-combo, stored in settings → `comboStrategies.<comboName>` (`fallbackStrategy`, `judgeModel`, `fusionTuning`), falling back to the global `settings.comboStrategy`.

| Strategy | Behaviour | Use for |
|---|---|---|
| `fallback` (default) | try in order, next on 429/5xx/timeout | default combo for agent/chat traffic; keeps streaming + tools |
| `round-robin` | rotate members, sticky per `comboStickyLimit` | a POOL of the same model across accounts (quota spread) |
| `fusion` | all members in parallel, `judgeModel` synthesizes one answer | hard reasoning, one-shot, high stakes |

Hard constraint: **fusion strips `tools` and forces `stream:false`** (tool history flattened to prose). Never point an agent/delegation profile at a fusion combo — it breaks silently, no error. Fusion also needs a client timeout above `panelHardTimeoutMs` (default 90000).

Round-robin across *different* model tiers is random quality per turn with no signal. Rotate only homogeneous pools; put cross-tier chains on `fallback`.

Set `judgeModel` explicitly, from a different family than the panel — it defaults to `panel[0]`, which rubber-stamps that model's own bias at 4x cost.

Verification commands, settings shape and the layering config: `references/combo-strategies.md`.

## Errors

- 401 → set/refresh `NINEROUTER_KEY` (Dashboard → Keys)
- 400 `Invalid model format` → check `model` exists in `/v1/models/<kind>`
- 503 `All accounts unavailable` → wait `retry-after` or add another provider account

## Diagnosing a 'model not working' report

Probe order — a failing model is usually a routing problem, not your config:

1. Check auth/transport first: `curl -s $NINEROUTER_URL/v1/models` with the bearer key. If this errors, the model is irrelevant — fix auth/transport first.
2. Then replicate the *exact failing call shape*. A plain `{model, messages}` probe returning 200 does NOT prove the alias healthy: combo member selection is request-parametric. `reasoning_effort`, `tools`, and `stream` each change which member the router picks, so a param you add can route to a different (possibly dead) backend. Reproduce the failing request's full param set (esp. `reasoning_effort`) in the repro curl, not just the model id.
3. A combo that returns 410 (`ModelDeprecated` /  `Gone`) or 400 `INVALID_MODEL_ID` is pointing at an upstream member that reached EOL or was removed. The alias itself exists; its member table is stale. Check the deprecation date in the error body.
4. Error geography: `410` = an upstream member died; `400` code `11128` `request illegal / channel verification` = the origin vendor rejecting calls that don't come from an official client. Both are alias/upstream health, not your gateway config.

Once isolated, the fix lives on the router (repoint/refresh the combo's members), not in the Hermes config — unless the config forces a param (e.g. global `agent.reasoning_effort: high`) that pins every call onto the dead member.
