# Out-of-tree mm backports: what fits which kernel base

Decision helper for which memory-management patch applies to a given kernel/LRU architecture. Goal: pick the patch that actually fits the tree before touching code.

## Taxonomy (three distinct features, two overlap)
- **le9uo** (firelzrd/le9uo, `0001-linux6.15.y-le9uo-1.15.patch`) — working-set PROTECTION. Reserves a floor of RAM for anonymous pages + clean file cache so reclaim never evicts in-use pages under pressure. Anti-thrash / anti-near-OOM-freeze. Works on BOTH classic LRU and MGLRU. Tuned via sysctls: `vm.workingset_protection` (enable, default OFF), `anon_min_ratio` (15%), `clean_min_ratio` (15%), `clean_low_ratio` (0%). Author's own test: ~38× faster file access under pressure.
- **"vm.workingset_protection: On by default"** (Masahito S — the le9uo author) — NOT a separate feature. One-line flip of that sysctl default 0→1. Only useful to make le9uo active with zero sysctl. The le9uo patch is a backport/adaptation of this commit.
- **re-swappiness** (firelzrd/re-swappiness, `0001-linux7.1-rc1-Re-swappiness-v1.3.patch`) — a DIFFERENT bug: under MGLRU `vm.swappiness` is effectively ignored (setting 0 doesn't stop swapping). Splits anon/file aging so swappiness works as a real global ratio. Companion to le9uo (same author), designed to run together, but does not stop freezes.
- **CAST / lru_cast** (firelzrd/lru_cast) — replaces the LRU lists entirely with an LRFU access-ranks policy. NOT "using MGLRU": a third option runtime-swappable alongside classic LRU and MGLRU. Requires 64-bit + SPARSEMEM + MMU.

## Which patch fits which kernel
- **le9uo + re-swappiness**: target MGLRU-enabled kernels, backportable to OLD bases — written originally for classic LRU, extended for MGLRU. This is the realistic set for a 4.19 MGLRU tree (e.g. DevHamid LKGeek_sdm660 `mglru-v5`).
- **CAST**: supports kernels ~6.12 → 7.3 ONLY. Hooks into modern mm internals (`memdesc_flags_t`, `vmap_pages_range_noflush`, memcg reparenting, `workingset_age_nonresident` private headers) that do not exist pre-6.12. Porting to 4.19 is a rewrite of the mm subsystem — non-starter. Future option only if the tree moves to a 6.12+ base.

## Pitfalls
- Don't compare le9uo vs on-by-default as rivals — same feature, one is a sysctl flip. The real comparison is le9uo vs CAST vs (re-swappiness as add-on).
- XanMod shipped workingset_protection on-by-default then REVERTED it (Apr 2024) after user-reported problems/freezes, later re-added in 7.1. So "on by default" has a history of boot trouble on some hardware. Recommendation: enable le9uo via sysctl with tuned ratios rather than the on-by-default patch (avoids forcing 15% floors on everyone).
- re-swappiness is invasive: rewrites MGLRU's core aging (splits `max_seq`, drops the PID controller). Upstream MGLRU maintainers explicitly rejected that approach in favor of a minimal fix — so it diverges further from upstream and costs more maintenance. Add it only when actually fighting `vm.swappiness` behavior under MGLRU.
- Hard protective floors can cause EARLY OOM if `anon_min_ratio`/`clean_min_ratio` are set too high.
