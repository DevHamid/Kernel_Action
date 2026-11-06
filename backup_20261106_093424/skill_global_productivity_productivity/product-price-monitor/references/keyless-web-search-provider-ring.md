# Keyless web search provider ring — connection reset failover

## Trigger
A price-watch tick reports web search failing entirely (no results, no error text, or "[Errno 104] Connection reset by peer") while other sources appear reachable. The job has a `web_provider_ring` configured as a list such as `exa, parallel, firecrawl, keenable`.

## Mechanism
The keyless provider ring walks providers in order. A provider that returns a structured refusal (HTTP 401/402/403/5xx, or an explicit refusal object) triggers failover to the next provider. A raw connection reset is not a structured refusal — the failover handler treats it as a non-refusal error and stops walking the ring before reaching fallback providers such as `keenable`. The result is a total search failure even though later providers would have worked.

## Fix
Mark the connection-reset provider's tier `paid` so it is excluded from the keyless ring:

```
hermes config set web.provider_tier.<provider> paid
```

Examples seen in the field:
- `hermes config set web.provider_tier.firecrawl paid`

This does not change paid-provider behavior; it only removes the provider from the keyless ring so the walk proceeds to `parallel` → `keenable`. Firecrawl itself remains usable under its paid tier if credentials exist elsewhere.

## Diagnosis steps
1. Read the failed tick output in `/opt/data/cron/output/<job-id>/` and confirm web search returned nothing while the provider ring included a connection-resetting provider.
2. Run `grep provider_tier /opt/data/config.yaml` to confirm the provider tier is unset or `keyless`.
3. Apply the tier override above.
4. Re-run the job: `hermes cron run <job-id>` in background with `notify=true`.
5. Confirm the tick output shows results from the next provider in the ring (e.g. Exa or Parallel) and no connection-reset errors.

## Verification
- [ ] Failed tick output confirmed web search failure with connection reset in the provider ring.
- [ ] Tier set via `hermes config set`, not hand-edited config.yaml.
- [ ] Re-run succeeded with results from a fallback provider.
- [ ] No new output file means the job is still processing — poll `kill -0 <pid>` until it finishes.