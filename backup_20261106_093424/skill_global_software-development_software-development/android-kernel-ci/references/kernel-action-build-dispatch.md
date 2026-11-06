# External kernel CI build dispatch (Kernel_Action pattern)

When the user points at a separate "build kernels" kit repo (e.g. `DevHamid/Kernel_Action`, workflow `build-kernel.yml`) that builds a kernel from a source repo, the flow is:

## 1. Discover the kit and its default branches
- List the kit repo, read its workflow YAML via the contents API, and read its `config.env` at the kit's default branch. Key fields: `KERNEL_SOURCE` (source repo), `KERNEL_SOURCE_BRANCH` (DEFAULT source branch — often a stale branch, NOT the finished feature branch), defconfig, image target, toolchain pins.
- The workflow's default source branch is a trap. Always dispatch with an explicit `KERNEL_SOURCE_BRANCH` input set to the actual finished tree. Verify the source repo/` has the branch by listing branches before dispatching.

## 1b. Verify the source branch is BUILDABLE before dispatching (pre-dispatch gate)
- **The source branch must exist on the REMOTE**, not just in a local clone. GH Actions clones the source repo from the remote; a local-only branch cannot be dispatched. Check `git ls-remote --heads origin | grep <source-branch>` — if absent, push it first (or have the user push it). Do NOT promise or trigger a build until the branch is on origin.
- **After pushing the new source branch, the local `origin/<branch>` tracking ref is stale** — it predates the push, so `git show origin/<branch>:<path>` reads the OLD ref and returns empty/garbage even though the remote branch is correct and complete. Verify the push landed with `git ls-remote origin <branch>` (truth from origin) and inspect content by the PUSHED SHA from that output (`git show <sha>:<path>`), or `git fetch origin <branch>` first to refresh the local ref. Never conclude a push failed or dropped content from a zero-count `git show origin/<branch>` immediately after the push.
- **Check the working tree for uncommitted changes from ANOTHER task.** A git status showing an unrelated dirty defconfig (e.g. a different card's `CONFIG_DEFAULT_TCP_CONG`) means committing now would mix that task's work into this build, breaking the one-by-one isolation. Verify `git status -sb` is clean (or that every diff belongs to the branch being built) before committing/pushing the feature branch.

## 2. Dispatch
- `POST /repos/<kit>/actions/workflows/<workflow>.yml/dispatches` with `{"ref":"<kit-default-branch>","inputs":{"KERNEL_SOURCE_BRANCH":"<source-branch>"}}`. HTTP 204 = accepted.
- The kit's `ref` is the kit branch; the `inputs` branch selects the source tree. Do not confuse the two.

## 3. Watch the run
- `GET /repos/<kit>/actions/runs?event=workflow_dispatch` (or by run id) → poll `status`/`conclusion`. A full kernel build takes ~30–60 min; poll with a small sleep, not a tight loop.
- Use `curl -4` (IPv6 connections to api.github.com RST), not `gh`/graphql.
- **Extract an API token cleanly — one token per line.** A token pulled from a config file with `grep oauth_token ... | awk '{print $2}' | tr -d '"'` will concatenate EVERY matching line with a newline if the file holds duplicates (e.g. a token written under two host keys). The resulting Authorization header `Bearer gho_...\ngho_...` is malformed: GitHub rejects it with HTTP 400 over HTTP/1.1 and a silent connection drop (HTTP 000) over HTTP/2 — never a clean 401, so it reads as a network flake. Fix: `head -1` to keep a single token, and verify its length/characters (`echo -n "$TOKEN" | od -c`) before using it. Diagnose a 000/400 with a deliberately FAKE bearer token: if the fake gets 401, the API is reachable and your real token is the problem — not egress.
- Judge progress from JOB-LEVEL STEP timestamps, not the run's `updated_at`. The run-level `updated_at` advances only on step *transitions*, so inside a long step it stays frozen and a healthy run looks hung. Get the job: `GET /repos/<kit>/actions/jobs/<job_id>` → each step carries `started_at`/`completed_at`. A step is progressing if its `started_at` is recent and the NEXT step's `started_at` hasn't arrived.
- A legitimate long step is NOT a hang: "Download Clang-aosp" pulls a ~2GB toolchain tarball and runs many minutes. Never cancel on wall-clock or stale `updated_at`. Only cancel when a step shows no movement over a long window AND the next step never starts (e.g. a setup/apt step stuck 30+ min — that is a real transient runner stall; cancel and re-dispatch).
- **A build that fails in the toolchain-download step ("Download Gcc-aosp"/"Download Clang-aosp") with HTTP 5xx — e.g. `503 Service Unavailable` from `android.googlesource.com` — is a transient infra failure, NOT a kernel-code problem.** Before touching any kernel code, verify the exact download URL returns 200 from your own host (`curl -s -o /dev/null -w "%{http_code}" ...`); if it does, re-dispatch the SAME commit/branch — the run will likely pass on retry. Do not bump versions, edit the tree, or change the workflow for a 503.
- GitHub publishes job logs at `GET /repos/<kit>/actions/jobs/<job_id>/logs` — the response may be either a ZIP or raw text. Sniff with `file <out>` before assuming zip; do not burn calls trying to `unzip` a text body.

## 4. Verify what actually built
- Download the `resolved-config` artifact (the workflow must upload it) and grep it for the features the chain claims. The resolved config is ground truth for what the build's config actually enabled.
- Confirm the SOURCE branch was used by checking a symbol that lives ONLY in that branch (e.g. a POC selector). If that unique symbol is present, the right tree was built; if absent, the workflow used its stale default source branch.
- Grep the resolved config for each claimed feature symbol — a card's claim ("CONFIG_X=y") is only satisfied if the symbol appears in the RESOLVED config, not the fragment.
- `unzip` is often absent on the host — extract zips with python3 `zipfile` instead.

## Kernel-boot artifact verification
After a successful build, before declaring victory, verify the artifact content (see SKILL.md step 9): download the boot image, byte-walk the ANDROID! header + cpio ramdisk, and for kernel-side patches count the patch marker in the gzip-decompressed Image.gz-dtb payload.

When the fix is a DTS/DT property (e.g. growing the reserved ramoops region), verify at the DTB LEVEL, not just the resolved config — a `.config` symbol does not prove the property values landed. Parse the BUILT DTB out of `Image.gz-dtb` (gzip kernel + trailing DTB: decompress, find DTB magic `\xd0\x0d\xfe\xed`, read `totalsize`, then token-walk the struct block: BEGIN_NODE/END_NODE/PROP/END) and assert the `reg`/`console-size`/`record-size` cells equal the intended hex. The DTB is the ship-of-truth for DT changes.

**Artifact zip pitfall:** a member inside the artifact zip can share the downloaded zip's own filename (e.g. artifact `Image.gz-dtb` contains a member `Image.gz-dtb`). Extracting in-place over the downloaded zip truncates it to 0 bytes (the zip is the extraction target). Always extract to a FRESH directory; if the member name collides with the zip path, re-download to a distinct name first. If `gh api` returns a 0-byte artifact (flaky egress), retry with `curl -4sS -H "Authorization: token $(gh auth token)"` against the artifact zip URL.
