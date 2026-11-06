# Pushing kernel changes when git-over-SSH hangs

Use when git fetch/push to the repo's SSH remote hangs (exit 124, NAT64 IPv6 resets). Fall back to GitHub REST Git Data API via curl.

## Token
- Valid: first line of /opt/data/github_token via `head -1` (cat/grep adds a duplicate newline → HTTP 400/000).
- /opt/data/.gh_token is stale (401) — never use.

## Procedure
1. GET /repos/<o>/<r>/git/refs/heads/<branch> → object.sha (full commit SHA).
2. GET .../git/trees/<branch_sha>?recursive=1 → blob SHAs at the paths to change.
3. Edit locally; create one blob per changed file: POST .../git/blobs with {content, encoding:"utf-8"}. Capture the full 40-char SHA — never truncate.
4. POST .../git/trees with {base_tree:<branch_sha>, tree:[{path, mode:"100644", type:"blob", sha:<full_blob_sha>}]} listing ONLY changed entries. Do NOT pass the whole recursive tree — it fails and returns a null tree SHA. base_tree derives all unchanged entries.
5. POST .../git/commits {message, tree:<new_tree_sha>, parents:[<branch_sha>]}.
6. PATCH .../git/refs/heads/<branch> {sha:<commit_sha>, force:false}.
7. Optional tag: POST .../git/refs {ref:"refs/tags/<tag>", sha:<commit_sha>}.
8. Verify pushed state, not just head SHA: GET branch ref and assert head==new commit; GET commit's tree recursively, fetch changed blobs, diff byte-for-byte against intended files. A commit referencing the wrong blob passes SHA checks but ships a stale file.

## Technique
- Pipe JSON via curl --data-binary @- with body as stdin (subprocess.run input=json.dumps(payload)) — avoids shell-quoting and arg-size limits.
- Recreate blobs in the same session as the tree build so full SHAs are in hand.
