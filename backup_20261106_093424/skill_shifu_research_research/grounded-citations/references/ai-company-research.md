# AI-company product research (LLM vendor launch, pricing, data policy)

When researching an AI/LLM vendor's product — context windows, free tiers,
pricing, data policy — these patterns recur.

## Sparse launch blogs

Launch blog posts are frequently JS-rendered; `web_extract` collapses them to
a skeleton (hundreds of chars). Don't stop there:

- Pull the site's subpages: `/pricing`, `/docs/terms-of-use`,
  `/docs/privacy-policy`, FAQ/doc pages. These carry the legal and commercial
  facts.
- Pull third-party tech-press coverage (MarkTechPost, TechCrunch, the-decoder,
  VentureBeat): it usually republishes the full spec table (context window,
  price per 1M tokens, benchmarks, parameter count). Cross-check numbers
  against the vendor's own page — the press carries the numbers, the vendor
  carries the defaults and legal language.
- Distinguish vendor self-reported benchmarks from independent evaluation;
  label them accordingly (Inception's table is self-reported).

## Free-token offers: three different things

Users conflate these; separate them precisely:

1. **One-time trial credit** — e.g. "100M free tokens" on account creation. A
   single tank that drains; it does NOT refill. The answer to "does it reset?"
   is *no*.
2. **Free-tier rate limits** — per-minute request / input / output token caps.
   These are throttles, not credits, and reset per minute, not monthly.
3. **Recurring allowance** — monthly/weekly included quota (rare on free
   tiers). Confirm before claiming any reset exists.

## Training-data / API privacy

The default is almost always opt-IN (they train on your inputs):

- Read the Terms of Use for a license grant to use "User Submissions"
  (prompts, uploads, outputs) to train models.
- Read the Privacy Policy for whether prompt/input personal data is listed as
  collected and used for training.
- Look for a self-serve opt-out toggle in account settings (e.g. "Improve the
  model for everyone"). Flip it off if the user cares.
- If no toggle is published, the only off-ramp is a contractual/enterprise
  arrangement — say so instead of inventing one.
