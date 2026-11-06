Transcription bot @oogwayisrobot (id 8970387782, admin), token /opt/data/.env TRANSCRIPTION_BOT_TOKEN. Worker transcription_worker.py (cron 72b0feeab47d) fail-closed if = Dev token. Never getUpdates on live gateway token.
§
gh oauth_token grep → dup newline → HTTP 400; use head -1.
§
wayne build: CI DevHamid/Kernel_Action @Kernel_Action. config.env @04b902493c: source DevHamid/LKGeek_sdm660 @devhamid-remastered, config vendor/wayne-oss-perf_defconfig, Image.gz-dtb, ENABLE_KERNELSU=false. AK3 = LKDenchin/KernelSU_Action prebuilt_ak3. Only submodules auto-pull: BakaSU (KernelSU→Baka-SU/BakaSU, drivers/kernelsu→../KernelSU/kernel).
§
MGLRU sdm660 ref mglru-backport-safe: lru_gen_init_lruvec() from lruvec_init() fixes freeze-on-enable (present mm/mmzone.c:105); lru_gen_use_mm guard must not call lru_gen_enabled(). That ref reverted DEBUG_FS ('bootloops this tree') but devhamid-remastered has DEBUG_FS=y — check.
§
9router AI gateway http://192.168.1.1:20128/v1; key env HERMES_CUSTOM_192_168_1_1_20128_API_KEY in profiles/shifu/.env (absent from shell env).
§
GitHub push: /opt/data/github_token valid (93ch, admin+push); /opt/data/.gh_token expired 401. gh CLI not installed.
§
Gateway lock dir /opt/data/.local/state/hermes/gateway-locks is stale uid-1000 (stage2-hook.sh chowns a fixed subdir list only; no root in-container) — repair: HERMES_GATEWAY_LOCK_DIR=/opt/data/.gateway-locks in /opt/data/.env + profiles/shifu/.env, restart gateway-default.
§
wayne-openwrt = CURRENT project: Mi6X→OpenWrt/ImmortalWrt modem+Docker bring-up. Kernel = LKGeek_sdm660@fix-ksu-sugrant (live, MGLRU OFF); build.yml pin fixed @fix-ksu-sugrant. Both branches' sharedmem drivers bind rmtfs reg=0 dynamically, patch NOT needed. modem/ files @ main 61cc738 (mba.mbn wiring, pil-msa MBA chain, no DTS patch); originals in /Desktop/vendor-work/openwrt-modem; /srv/ssd remounted EMPTY (fw payload 91.58MB gone — re-extract from phone). QMI/QRTR not MBIM; uqmi unusable.