# 9router combo strategies

## Verify what a build supports — read the source, not the dashboard

Strategy support is a build detail. It lives in `open-sse/services/combo.js`. The dashboard is a Next.js App Router page: its HTML is a short RSC stream with no listable `_next/static` chunks, so grepping the served JS is a dead end. Authoritative files on `master`:

```bash
base=https://raw.githubusercontent.com/decolua/9router/master
curl -s $base/open-sse/services/combo.js   > combo.js   # strategy dispatch, fusion, judge
curl -s $base/src/sse/handlers/chat.js     > chat.js    # where strategy is read from settings

grep -nE 'strategy|judgeModel|fusion|round-robin|quorum|FUSION' combo.js
grep -nE 'comboStrateg|judgeModel|fusion' chat.js
```

To see exactly what a release added, read the commit message body — it enumerates touched files and the design rationale:

```bash
curl -s https://api.github.com/repos/decolua/9router/commits/<sha> \
  | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["commit"]["message"]);print([f["filename"] for f in d["files"]])'
```

Confirm the deployed instance separately: `/api/health` and `/v1/models` answer with the API bearer key; combo CRUD under `/api/combos` does not — it wants the dashboard session, so read combos from the dashboard or the source rather than the API.

## Settings shape

```js
settings.comboStrategy            // global default: "fallback" | "round-robin" | "fusion"
settings.comboStickyLimit         // round-robin stickiness
settings.comboStrategies[comboName] = {
  fallbackStrategy: "fallback" | "round-robin" | "fusion",
  judgeModel: "provider/model",            // fusion only; default panel[0]
  fusionTuning: { minPanel, stragglerGraceMs, panelHardTimeoutMs }
}
settings.providerStrategies       // per-provider rotation, separate from combos — correct home for round-robin
```

Fusion defaults: `minPanel: 2`, `stragglerGraceMs: 8000`, `panelHardTimeoutMs: 90000`. Quorum-grace means the first `minPanel` answers unblock the judge, so one slow member costs at most the grace window.

Fusion runs panel calls non-streaming with tools stripped and tool history flattened to prose; the judge call reuses the client's original body plus a judge directive. Sources are anonymized to `Source N` so the judge weighs substance, not brand.

## Layering pattern

Two combos and one YAML line beat an automatic prompt classifier.

```
agent/chat/delegation traffic  -> combo "agent-base"   fallback, 3 same-tier different-family models
hard one-shot reasoning        -> combo "deep-fusion"  fusion, 3 different families + cross-family judge
round-robin                    -> providerStrategies, homogeneous pools only (same model, N accounts)
```

Hermes side:

```yaml
model:
  default: agent-base
  provider: custom
  base_url: http://<host>:20128/v1
fallback_providers:
  - { provider: custom, model: <single-model combo>, base_url: http://<host>:20128/v1 }
```

That gives two independent fallback layers: combo-internal ordering, then Hermes-level provider fallback if the whole combo 5xxs.

Reach fusion out-of-band instead of via `model.default`:

```bash
curl -s $NINEROUTER_URL/v1/chat/completions \
  -H "Authorization: Bearer $NINEROUTER_KEY" -H 'Content-Type: application/json' \
  -d '{"model":"deep-fusion","stream":false,"messages":[{"role":"user","content":"..."}]}'
```

## Pitfalls

- Fusion as the agent model = dead agent. Tools stripped, streaming off, and the failure is silent rather than an error.
- Fusion is non-streaming: one blob, no token stream. Fine for analysis, wrong for conversation.
- Panel of one short-circuits to a direct answer; panel members from one family add cost without signal. Diversity beats strength.
- Judge defaults to `panel[0]`. Set `judgeModel` to another family or the fusion is decoration.
- Panel *hard* timeout above the client timeout stalls the whole request. Raise the client timeout for fusion calls only.
- Round-robin on a combo whose members differ in tier makes every reply's quality random — reads as the model getting dumber, invisible to diagnose.
- A combo alias is only as alive as its members. `owned_by:"combo"` aliases fan out to member models that can reach EOL independently; a plain probe returning 200 proves nothing about the path taken when `reasoning_effort` is added (member selection is request-parametric). Re-run the failing request verbatim and read the 410 `ModelDeprecated` body for which member died.
