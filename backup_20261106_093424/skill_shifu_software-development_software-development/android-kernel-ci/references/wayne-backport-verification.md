# Feature verification map — wayne (sdm660) kernel backports

Work on `origin/<branch>` (dev `origin/mglru-v5`, freshly branched `project-hail-mary`). For each task, the verification command and expected evidence:

## A-tasks (Dev): A1–A7
- **A1 MGLRU v5**: `git show origin/<branch>:mm/vmscan.c | grep -c lru_gen` → ~163 refs. Freeze fix present iff `lru_gen_init_lruvec` appears. Kconfig alone (`CONFIG_LRU_GEN=y`) is NOT proof — a dangling config with zero code is the known fail state.
- **A2 pstore/ramoops**: `git ls-tree -r --name-only origin/<branch> -- arch/arm64/boot/dts/ | grep -i ramoops` (dtsi) + `CONFIG_PSTORE*`/`CONFIG_RAMOOPS*` in the vendor defconfig (`arch/arm64/configs/vendor/wayne-oss-perf_defconfig`).
- **A3 BakaSU (ReSukiSU→BakaSU)**: grep tree for `bakasu`/`resuki` (`git grep -iE 'bakasu|resuki' origin/<branch>`). Verified state was still `ReSukiSU` v4.2.0-rc1 — rename not done.
- **A4 SUSFS**: grep for `susfs`/`jack` — the hits are sound-card docs (`emu10k1-jack.rst`), NOT SUSFS. Any `jack` grep must be name-scoped.
- **A5 Rekernel**: `git ls-tree -r --name-only origin/<branch> | grep -i rekernel` → `drivers/net/rekernel/`.
- **A6 NoMount**: `git ls-tree -r --name-only origin/<branch> -- fs/nomount` → 4 files (verify-only, already in base).
- **A7 MGLRU v5**: fresh backport of CachyOS `0001-MGLRU-v5.patch` onto project-hail-mary. Verify with `git show origin/<branch>:mm/vmscan.c | grep -c lru_gen`. (User-corrected: A7 is MGLRU, NOT POC/REFLEX.)
- **A8 POC**: Dev backports the cpufreq 'Paw Of Change' selector from `firelzrd/poc-selector`. Path-free check: `git ls-tree -r --name-only origin/<branch> | grep -i poc`, then grep the symbol in tree.

## B-tasks (Shifu): B1–B8
- **B1 BBRv3**: `git show origin/<branch>:net/ipv4/tcp_bbr.c | grep -n 'define BBR_VERSION'` → `3`. The `bbr_ack_aggregation*` / `bbr_max_bw` machinery distinguishes v3 from stock 4.9 BBR. (Path is `net/ipv4/`, NOT `drivers/net/`.)
- **B2 LZ4**: `git ls-tree -r --name-only origin/<branch> -- lib/lz4` → 8 files (verify-only).
- **B3 NTSYNC**: `git ls-tree -r --name-only origin/<branch> | grep -i ntsync` → `drivers/misc/ntsync.c` + uapi.
- **B4 Droidspaces-OSS**: the non-GKI patch infra yields ~96 `droidspaces` hits — those are NOT the OSS backport. The real driver backport was absent on `mglru-v5`. Verify the actual driver source, not the patch-infra grep.
- **B5 LMK PSI**: `CONFIG_PSI=y` alone is NOT LMK-PSI. Check `drivers/staging/android` for `lmkd`/`lowmemorykiller` PSI hooks — the config-only state was the incomplete one.
- **B6 BORE+ADIOS**: `git show origin/<branch>:kernel/sched/fair.c | grep -icE 'bore|adios'` → 0 = absent (single file, not `kernel/sched/bore.c`).
- **B7 Cambyses**: `git show origin/<branch>:kernel/sched/fair.c | grep -c cambyses` → 2 (folded into fair.c), AND `git show origin/<branch>:kernel/sched/features.h | grep LB_STRICT_BUDGET` → `1` (the actual runtime gate). Cambyses has NO Kconfig option — it compiles unconditionally into fair.c and runs iff `sched_feat(LB_STRICT_BUDGET)` is 1. Beware: the sched_feat flag list lives in `kernel/sched/features.h`, NOT `sched_features.h` (grep that path returns 404 / no hits). A "compiles unconditionally, no config gate" feature still has a runtime switch — check the sched_feat default before declaring it dead or alive.
- **B8 REFLEX**: Shifu backports the cpufreq 'Powerhouse' governor from `firelzrd/reflex`. Path-free check then symbol grep, same pattern as A8.

## Rules
- Path-free check first: `git ls-tree -r --name-only origin/<branch> | grep -i <feature>` before guessing a path.
- Version-sensitive features: grep a real code marker, not file existence.
- The Kanban board is stale (all 14 marked done) if 5 are actually missing — verify before trusting it.
