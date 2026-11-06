# External kernel CI build dispatch (Kernel_Action pattern)

When the user points at a separate "build kernels" kit repo (e.g. `DevHamid/Kernel_Action`, workflow `build-kernel.yml`) that builds a kernel from a source repo, the flow is:

## 1. Discover the kit and its default branches
- List the kit repo, read its workflow YAML via the contents API, and read its `config.env` at the kit's default branch. Key fields: `KERNEL_SOURCE` (source repo), `KERNEL_SOURCE_BRANCH` (DEFAULT source branch — often a stale branch, NOT the finished feature branch), defconfig, image target, toolchain pins.
- The workflow's default source branch is a trap. Always dispatch with an explicit `KERNEL_SOURCE_BRANCH` input set to the actual finished tree. Verify the source repo/` has the branch by listing branches before dispatching.

## 1b. Verify the source branch is BUILDABLE before dispatching (pre-dispatch gate)
- **The source branch must exist on the REMOTE**, not just in a local clone. GH Actions clones the source repo from the remote; a local-only branch cannot be dispatched. Check `git ls-remote --heads origin | grep <source-branch>` — if absent, push it first (or have the user push it). Do NOT promise or trigger a build until the branch is on origin.
- **After pushing the new source branch, the local `origin/<branch>` tracking ref is stale** — it predates the push, so `git show origin/<branch>:<path>` reads the OLD ref and returns empty/garbage even though the remote branch is correct and complete. Verify the push landed with `git ls-remote origin <branch>` (truth from origin) and inspect content by the PUSHED SHA from that output (`git show <sha>:<path>`), or `git fetch origin <branch>` first to refresh the local ref. Never conclude a push failed or dropped content from a zero-count `git show origin/<branch>` immediately after the push.
- **Check the working tree for uncommitted changes from ANOTHER task.** A git status showing an unrelated dirty defconfig (e.g. a different card's `CONFIG_DEFAULT_TCP_CONG`) means committing now would mix that task's work into this build, breaking the one-by-one isolation. Verify `git status -sb` is clean (or that every diff belongs to the branch being built) before committing/pushing the feature branch.

- `git ls-remote` over HTTPS hits the same IPv6/NAT64 reset as `api.github.com`
  (`kex_exchange_identification: read: Connection reset by peer`). Retry in a
  short shell loop (3 attempts, `sleep 3`) before concluding a branch is
  missing — one failed attempt reads as "branch absent" and can trigger a
  needless re-push or a dispatch against the wrong tree.

## 1c. Checking out a named branch in a shallow clone

When the user says "continue on branch X", that branch may not exist as a
remote-tracking ref locally. In a `--depth=1` clone, `git fetch origin X`
downloads the branch but does NOT create `refs/remotes/origin/X`, so
`git rev-parse origin/X` fails with `ambiguous argument` and `git checkout X`
finds nothing — the branch looks absent when it is present on the remote.

Read the SHA out of `.git/FETCH_HEAD` and branch from that:

```bash
git fetch origin <branch>                 # populates FETCH_HEAD only
git rev-parse FETCH_HEAD                  # the real tip SHA
git checkout -b <branch> FETCH_HEAD       # creates the local branch
```

Before switching, stash or commit any in-flight work from a DIFFERENT task —
`git checkout -b` carries a dirty working tree across the switch and mixes the
two tasks into one commit. `git stash push -m <label> <paths>` scoped to the
touched files keeps the other task's edits recoverable without polluting the
new branch.

Confirm the landed SHA matches what the user named before building on it
(`git log -1 --format=%H` against the SHA from the artifact/CI run), so the
fix is applied to the tree that actually produced the failing image.

## 2. Dispatch

- Read the workflow YAML's `on.workflow_dispatch.inputs` block FIRST to enumerate ALL inputs — kits often gate extra switches beyond the source branch (e.g. `CONFIG_KSU`, `CONFIG_KSU_SUSFS`, `CONFIG_KSU_SUSFS_SUS_MOUNT`). Pass each explicitly so you don't silently inherit a default you didn't intend.
- These KSU/SUSFS inputs are INVERTED OVERRIDES, not plain booleans: the workflow's inject step only writes `<SYM>=n` into the defconfig when the input string equals `n`, otherwise it leaves the defconfig's own setting (usually `CONFIG_KSU=y` / `CONFIG_KSU_SUSFS=y` / `CONFIG_KSU_SUSFS_SUS_MOUNT=y`) untouched. Two consequences: (a) the input's DEFAULT is `'n'`, so OMITTING the input also disables KSU — you cannot 'leave it alone' by not passing it; (b) to keep the defconfig's default you must EXPLICITLY pass a non-`n` value (`on`). Ground-truth the defconfig on the source branch (`raw.githubusercontent.com/<repo>/<branch>/<configs-path>`) before dispatching to see what the tree actually defaults to.
- This user runs KSU+SUSFS INSTEAD of Magisk — removing Magisk was specifically to hand root to KSU. A rebuild release should carry KSU/SUSFS enabled unless the test explicitly isolates them; do NOT disable them as a 'cleaner' default for a scheduler-isolation build without confirming with the user. If a run was dispatched with KSU off by mistake, cancel it (`POST /repos/<kit>/actions/runs/<id>/cancel` → HTTP 202; confirm via run `conclusion: cancelled`) and re-dispatch with the three KSU inputs set to `on`.
- `POST /repos/<kit>/actions/workflows/<workflow>.yml/dispatches` with `{"ref":"<kit-default-branch>","inputs":{"KERNEL_SOURCE_BRANCH":"<source-branch>", ...all inputs}}`. HTTP 204 = accepted.
- **A dispatch snapshots the source branch at the moment of dispatch** — it does NOT track the branch head. If the branch moves after you dispatch (you push more commits, or a retry fires while an earlier run is queued), the run compiles the SHA it captured, not the current head. Before dispatching, grab the source branch's current tip SHA (`GET /repos/<src>/branches/<branch>` → `commit.sha`) and record it; if a later run's `head_sha` differs from that, it is building a stale tree. Never call a run "the build of <branch>" without checking its `head_sha` equals the head you intended.
- **Never blindly retry a failed/422 dispatch — first list existing runs for the same event and target.** The retry loop in this project re-sent the same dispatch multiple times after an error, creating 4+ duplicate runs, and because the branch had moved between retries they landed targeting a stale SHA. Before (re-)dispatching: `GET /repos/<kit>/actions/runs?event=workflow_dispatch&per_page=20`, compare each run's `head_sha` against the intended tip, cancel the stale/duplicate ones (`POST .../cancel` → 202, confirm `conclusion: cancelled`), and keep exactly one clean run on the intended SHA. A single dispatch, verified by `head_sha`, is the target state.
- The kit's `ref` is the kit branch; the `inputs` branch selects the source tree. Do not confuse the two.
- Before dispatching, confirm `config.env`'s `KERNEL_SOURCE` names the repo the source branch was actually pushed to — the kit builds that repo, so a branch pushed to a different remote is invisible to the run.

## 3. Watch the run
- `GET /repos/<kit>/actions/runs?event=workflow_dispatch` (or by run id) → poll `status`/`conclusion`. A full kernel build takes ~30–60 min; poll with a small sleep, not a tight loop.
- Use `curl -4` (IPv6 connections to api.github.com RST), not `gh`/graphql.
- Poll long builds with a terminal BACKGROUND loop, not `execute_code`: the
  `execute_code` wall-clock cap is ~300s regardless of its `timeout_s`
  parameter, so a 10–15 min kernel build poll times out mid-run with no output.
  Use a background `curl` loop (poll every 30s, break on `completed`, notify on
  exit) and check it via a process poll.
- **Extract an API token cleanly — one token per line.** A token pulled from a config file with `grep oauth_token ... | awk '{print $2}' | tr -d '"'` will concatenate EVERY matching line with a newline if the file holds duplicates (e.g. a token written under two host keys). The resulting Authorization header `Bearer gho_...\ngho_...` is malformed: GitHub rejects it with HTTP 400 over HTTP/1.1 and a silent connection drop (HTTP 000) over HTTP/2 — never a clean 401, so it reads as a network flake. Fix: `head -1` to keep a single token, and verify its length/characters (`echo -n "$TOKEN" | od -c`) before using it. Diagnose a 000/400 with a deliberately FAKE bearer token: if the fake gets 401, the API is reachable and your real token is the problem — not egress.
- Judge progress from JOB-LEVEL STEP timestamps, not the run's `updated_at`. The run-level `updated_at` advances only on step *transitions*, so inside a long step it stays frozen and a healthy run looks hung. Get the job: `GET /repos/<kit>/actions/jobs/<job_id>` → each step carries `started_at`/`completed_at`. A step is progressing if its `started_at` is recent and the NEXT step's `started_at` hasn't arrived.
- A legitimate long step is NOT a hang: "Download Clang-aosp" pulls a ~2GB toolchain tarball and runs many minutes. Never cancel on wall-clock or stale `updated_at`. Only cancel when a step shows no movement over a long window AND the next step never starts (e.g. a setup/apt step stuck 30+ min — that is a real transient runner stall; cancel and re-dispatch).
- **A build that fails in the toolchain-download step ("Download Gcc-aosp"/"Download Clang-aosp") with HTTP 5xx — e.g. `503 Service Unavailable` from `android.googlesource.com` — is a transient infra failure, NOT a kernel-code problem.** Before touching any kernel code, verify the exact download URL returns 200 from your own host (`curl -s -o /dev/null -w "%{http_code}" ...`); if it does, re-dispatch the SAME commit/branch — the run will likely pass on retry. Do not bump versions, edit the tree, or change the workflow for a 503.
- GitHub publishes job logs at `GET /repos/<kit>/actions/jobs/<job_id>/logs` — the response may be either a ZIP or raw text. Sniff with `file <out>` before assuming zip; do not burn calls trying to `unzip` a text body.

## 3b. Identify what an IN-PROGRESS run is building
- A `workflow_dispatch` run's metadata (`head_branch`, `display_title`) shows only the KIT branch (e.g. `Kernel_Action`), NOT the `KERNEL_SOURCE_BRANCH` input that selects the kernel tree. Do not attribute the build to a kernel branch from the run's own fields.
- To know which kernel tree a running build compiles: read `config.env` from the kit repo — `KERNEL_SOURCE` names the source repo (e.g. `DevHamid/LKGeek_sdm660`). Then list that source repo's branches; the branch being built is the one whose HEAD SHA contains the target feature commit. Verify presence by ANCESTRY, not by matching the feature SHA to a branch tip (the feature commit is an ancestor of the tip, rarely the tip itself): fetch branch tips (`GET /repos/<src>/branches`) and locally run `git merge-base --is-ancestor <feature> <branch-tip>`.
- Multiple concurrent runs on the same kit repo all share the kit's default branch; run-level fields cannot tell them apart. Distinguish by creation time against the board's running tasks, and confirm each against the source repo's branch set.
- If a run ID returns 404 on the repo you expect, the run belongs to a DIFFERENT repo — run IDs are per-repo. Sweep the owner's repos (`GET /users/<owner>/repos`) and re-query each until the run resolves.

## 4. Verify what actually built
- Download the `resolved-config` artifact (the workflow must upload it) and grep it for the features the chain claims. The resolved config is ground truth for what the build's config actually enabled.
- Confirm the SOURCE branch was used by checking a symbol that lives ONLY in that branch (e.g. a POC selector). If that unique symbol is present, the right tree was built; if absent, the workflow used its stale default source branch.
- Grep the resolved config for each claimed feature symbol — a card's claim ("CONFIG_X=y") is only satisfied if the symbol appears in the RESOLVED config, not the fragment.
- `unzip` is often absent on the host — extract zips with python3 `zipfile` instead.

## 4b. Verify run → branch attribution BEFORE handing out a download link

Concurrent dispatch runs on the same kit are indistinguishable by their own fields (`head_branch`/`display_title` show only the kit branch; creation times can be seconds apart). Dispatch order or an earlier guess is NOT ground truth for which source branch a completed run built. The ONLY proof is the run's own `resolved-config` artifact: download it and grep it for the feature symbols the branch was supposed to flip (`grep -E "SCHED_POC_SELECTOR|CPU_FREQ_GOV_REFLEX"`). Confirm the signature matches the intended test (e.g. POC off + REFLEX on for "test1") BEFORE publishing the flash link — a swapped build would hand the user the freeze-causing config and break the single-variable read.

- **The artifact branch mixes commits: images and flashable zips land in
  SEPARATE commits, so a file's presence does not attribute it to the latest
  run.** `GET /repos/<kit>/contents/?ref=kbuilds` gives names/sizes/blob SHAs
  only; to attribute a file to a run, read the branch's commit list
  (`GET /repos/<kit>/commits?sha=kbuilds`) and match the commit that ADDED it
  (`GET /repos/<kit>/commits/<sha>` → `.files[]`). Two zips from the same run
  differing only by a defconfig flip differ in size by a few KB, so size alone
  cannot tell them apart.
- **When the kit publishes `config.txt` beside the images on the artifact
  branch, that file IS the resolved config of the shipped build.** Download it
  (`raw.githubusercontent.com/<kit>/kbuilds/config.txt`) and grep the
  discriminating feature symbols before handing out a flash link — same ground
  truth as the run's `resolved-config` artifact, without needing the run id.

## Release-based artifact delivery (clickable link)

GitHub artifact API URLs are auth-gated (HTTP 401 anonymously) and `Attach the file itself as media` only works when the agent can attach. When a stable clickable link is required, publish the flashable zip through a release instead: `POST /repos/<kit>/releases` with `{"tag_name":"<branch>-1","name":"<display>","draft":true}`, upload the asset to the returned `upload_url` (`curl --data-binary @<zip> -H "Content-Type: application/zip"`), then `PATCH` the release with `{"draft":false}`. Without the publish PATCH the download URL is an unstable `untagged-<hash>` link; after publishing, `browser_download_url` is stable.

## Kernel-boot artifact verification
After a successful build, before declaring victory, verify the artifact content (see SKILL.md step 9): download the boot image, byte-walk the ANDROID! header + cpio ramdisk, and for kernel-side patches count the patch marker in the gzip-decompressed Image.gz-dtb payload.

**A rebuilt boot.img does NOT hash-match the clean base — do not assert it does.** When the workflow injects the new kernel (`Image.gz-dtb`) into the base image's ramdisk at packaging time, the resulting `boot` artifact differs from the clean base by design, so a sha256 comparison against the base is expected to FAIL and proves nothing. The right clean-base proof is the RAMDISK, not the hash ( parse the ANDROID! header (kernel_size at 8, ramdisk_size at 16, page_size at 36; `rd_start = page_size + align(kernel_size)`), gunzip the ramdisk, walk the newc cpio, and assert ZERO hits for `magisk`/`magiskinit`/`overlay.d`/`.backup` — plus that the stock entries (init, fstab, build.prop) are all present. That confirms the Magisk-stripped base carried through while the kernel was swapped. Do not report the built image as 'byte-identical to the clean base' without actually running the hash, and if you run it and it differs, that is expected — check the ramdisk content instead.

When the fix is a DTS/DT property (e.g. growing the reserved ramoops region), verify at the DTB LEVEL, not just the resolved config — a `.config` symbol does not prove the property values landed. Parse the BUILT DTB out of `Image.gz-dtb` (gzip kernel + trailing DTB: decompress, find DTB magic `\xd0\x0d\xfe\xed`, read `totalsize`, then token-walk the struct block: BEGIN_NODE/END_NODE/PROP/END) and assert the `reg`/`console-size`/`record-size` cells equal the intended hex. The DTB is the ship-of-truth for DT changes.

**Artifact zip pitfall:** a member inside the artifact zip can share the downloaded zip's own filename (e.g. artifact `Image.gz-dtb` contains a member `Image.gz-dtb`). Extracting in-place over the downloaded zip truncates it to 0 bytes (the zip is the extraction target). Always extract to a FRESH directory; if the member name collides with the zip path, re-download to a distinct name first. If `gh api` returns a 0-byte artifact (flaky egress), retry with `curl -4sS -H "Authorization: token $(gh auth token)"` against the artifact zip URL.

**When `gh run download` fails with `connection reset by peer`, stop retrying it and fetch the zip with `curl -4`.** The failure is on the blob-storage redirect (`productionresultssa9.blob.core.windows.net`) over the host's IPv6/NAT64 path, not a bad run or expired link — retrying `gh run download` reproduces it. The artifact redirect honours IPv4:

```bash
url=$(gh api repos/<owner>/<repo>/actions/runs/<id>/artifacts \
  -q '.artifacts[]|select(.name|startswith("AnyKernel3"))|.archive_download_url')
curl -4 -sSL -H "Authorization: token $(gh auth token)" -o ak.zip "$url" \
  -w 'http=%{http_code} size=%{size_download}\n'
```

Expect `http=200` and a size matching the artifact's `size_in_bytes`. Verify integrity with python3 before handing out the file — `zipfile.ZipFile(p).testzip()` must be `None` and the kernel member (`Image.gz-dtb`) must be present. Do the download and the config verification from the SAME run so the artifact and the `.config` describe one build.

## Manually republishing a flashable artifact to the branch (git-data API)

- The kit workflow's publish step auto-pushes ONLY the kernel image files (`Image.gz-dtb`, `boot.img`) to the artifact branch (`kbuilds`). The flashable AnyKernel3 zip is only a run artifact and is NOT pushed. If you point the user at a `raw.githubusercontent.com` link for the zip, you must republish it yourself after the run completes.
- Force-pushing the artifact branch (the kit's `git init; cp ...; git push -f` step) replaces branch contents with only what was copied — so after each build a previously-published zip can vanish from the branch even while the images remain. Re-check branch contents (`GET /repos/<kit>/contents/?ref=kbuilds`) before promising a stable zip URL.
- Republish recipe via git-data API (no local git required):
  1. `GET /repos/<kit>/commits/<branch>` — take `sha` (head) and `commit.tree.sha` (base_tree).
  2. `POST /repos/<kit>/git/blobs` with `{"content": <base64>, "encoding":"base64"}` → blob sha. Must include `-H "Content-Type: application/json"` — without it the API returns an empty/non-JSON body and the blob create silently fails.
  3. `POST /repos/<kit>/git/trees` with `{"base_tree": <base_tree>, "tree":[{"path":"<name>.zip","mode":"100644","type":"blob","sha":<blob sha>}]}` → tree sha.
  4. `POST /repos/<kit>/git/commits` with `{"message":..., "tree":<tree sha>, "parents":[<head sha>]}` → commit sha.
  5. `PATCH /repos/<kit>/git/refs/heads/<branch>` with `{"sha": <commit sha>, "force":true}`.
- Pitfall: when filling the commit's `parents` array, do NOT shell-interpolate a sha captured through `echo`/console output — a trailing newline or whitespace corrupts the parent hash and GitHub rejects the commit (or creates a bogus parent). Parse the sha with the same python `json.load(stdin)` builder (or `strip()` it) before embedding it in the payload.
- Pitfall: inline `-d '<json>'` payloads fail for large files. A multi-MB boot/zip blob base64-encoded into a curl argument exceeds ARG_MAX and fails with `Argument list too long`. Write the JSON payload to a temp file (`json.dump(payload, open('/tmp/p.json','w'))`) and send it with `curl --data-binary @/tmp/p.json` — avoids both shell-quoting and the arg-size limit. Same rule applies to the blob-create POST for any artifact over a few hundred KB.
- Verify before handing out the link: download the republished file from `raw.githubusercontent.com`, run `ZipFile.testzip()`, confirm the kernel member (`Image.gz-dtb`) is non-zero, AND compare its sha256 against the original run artifact — a byte-identical hash proves the republish copied the right file, not a stale/wrong zip.
