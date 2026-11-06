---
name: memos-docker-build
description: >-
  Build & ship the Memos fork Docker image.
---

# Memos fork Docker build & deploy (GH Actions → GHCR → Dockge)

Project: `/opt/data/memos-fork` (github.com/DevHamid/memos), branch
`feat/chris-ux-integration`. Deploys via Dockge to host port **5231:5230**
(existing stock instance stays on 5230).

## Standing rules
- Never claim a CI/build fix works without evidence: run `go build -o /tmp/memos-test ./cmd/memos` (full path `/opt/data/go/bin/go`, ~2-3 min) and validate `web/package.json` JSON locally before pushing. User explicitly rejects confident claims without output.
- No Docker daemon and no direct GitHub push from this container. Shipping code to GitHub goes through a **bundle relay** (below).
- User wants production-ready day one — no incremental stubs.

## Procedure
1. Local gate: `go build ./cmd/memos` + `python3 -c "import json;json.load(open('web/package.json'))"` (and pnpm-lock.yaml sanity).
2. Commit on `feat/chris-ux-integration`.
3. Bundle: `git bundle create /opt/data/<name>.bundle feat/chris-ux-integration` (~45M).
4. Hand the user the host commands (run on devhamid host, repo `~/memos`):
   ```
   docker cp hermes-agent:/opt/data/<name>.bundle ~/memos-<name>.bundle
   cd ~/memos
   git fetch ~/memos-<name>.bundle feat/chris-ux-integration:tmp
   git reset --hard tmp && git branch -D tmp
   git push origin feat/chris-ux-integration
   ```
   Do not invent your own run on the host — deliver the block and wait.
5. Green Actions run ⇒ user Pulls in Dockge (verify image digest actually changed), Start.
6. Smoke test new image: `docker run --rm ghcr.io/devhamid/memos:latest memos version` must print CalVer — a shell-parse error here means the image is not what the build produced.

## Dockerfile (scripts/Dockerfile)
Three stages, mirrors upstream canary + in-image frontend build:
1. `node:24-alpine` → `npm install -g pnpm@11.0.1` (corepack prepare is unreliable), `pnpm install --frozen-lockfile`, then `pnpm release` (outputs to `../server/frontend/dist` — the path `go:embed` expects; `pnpm build` would output to `web/dist` instead). See `templates/Dockerfile.memos`.
2. `golang:1.27-alpine` → `go mod download`, copy source + frontend dist, `CGO_ENABLED=0 go build -trimpath -ldflags="-s -w -X .../version.Version=${VERSION} -X .../version.Commit=${COMMIT}" -tags netgo,osusergo -o memos ./cmd/memos`. Go 1.26+ required by go.mod.
3. `alpine:3.20` runtime: `ca-certificates tzdata su-exec sqlite`, non-root user uid/gid 10001, binary → `/usr/local/bin/memos`, entrypoint `scripts/entrypoint.sh`, `CMD ["memos", "--data", "/var/opt/memos", "--port", "5230"]`.

## Pitfalls (cost real time here)
- **`.dockerignore` excludes `/web/`, `/docs/`, `*.md`** — upstream never builds the frontend inside the image (separate `build-frontend` job uploads `server/frontend/dist` artifact). Adding an in-image frontend stage fails with `"/web": not found` until `/web/` is un-excluded.
- **GHCR tags must be lowercase.** `github.repository` / `github.repository_owner` keep original case (`DevHamid` → buildx: `invalid tag ... repository name must be lowercase`). Add a step: `echo "owner_lc=$(echo '${{ github.repository_owner }}' | tr '[:upper:]' '[:lower:]')" >> "$GITHUB_OUTPUT"` and use it in tags/attestation.
- **CalVer gate**: `internal/version.Validate()` rejects `VERSION=dev` (`expected YY.MM[.N]`). Pass `bash scripts/release_version.sh development-version` as VERSION build-arg, or patch Validate() to `return nil` — but when you do, remove the now-unused `regexp`/`errors` imports or `go build` fails with `imported and not used`.
- **After any cherry-pick / conflict resolution (`git checkout --theirs`), scan `web/package.json` + lockfile for `<<<<<<<` markers.** pnpm dies in Docker with bare `exit code: 1` and no visible cause; the only local repro is `pnpm install` on the host checkout. Run the JSON gate in step 1.
- **`/usr/local/memos/memos: line 1: syntax error: unexpected ")"` in crash loop = wrong/stale image**, not a code bug: that binary path never existed in the current Dockerfile. Check the pulled digest against the green run before reading code.
- buildx/BuildKit unavailable on the SBC host (no `--mount`, `--platform` parse errors, OOM) — that's why builds live in GH Actions; don't retry local `docker buildx`.
- No-cache churn: build-args like `BUILD_DATE=run_id` + `no-cache: true` in the workflow force fresh layers; upstream cache (`type=gha`) otherwise hides stale layers.

## Dockge compose (known-good shape)
```
services:
  memos:
    image: ghcr.io/devhamid/memos:latest
    container_name: memos-custom
    restart: unless-stopped
    ports: ["5231:5230"]
    volumes: ["./memos-data:/var/opt/memos"]
    environment:
      - MEMOS_DRIVER=sqlite
      - MEMOS_DSN=/var/opt/memos/memos.db?_journal=WAL&_busy_timeout=5000&_sync=NORMAL
```
Env vars are UPPERCASE `MEMOS_*` (a `Memos_Driver` lowercase-prefix variant is ignored).

## Status at last write
Local `go build ./cmd/memos` verified clean; frontend stage + conflict-marker fix pushed to GitHub but **CI run not yet confirmed green** — do not assume the image in GHCR is current.
