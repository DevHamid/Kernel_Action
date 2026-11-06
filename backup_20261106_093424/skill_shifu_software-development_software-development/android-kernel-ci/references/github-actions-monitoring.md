# GitHub Actions: carrying workflows + monitoring runs

## Un-ignoring `.github/` when the repo has a blanket `.*` ignore rule

Many kernel repos' `.gitignore` starts with `.*` (ignores every dotfile/dir).
That silently excludes `.github/`, so a workflow cannot be committed. Add
negation rules AFTER the blanket line — and un-ignore each PARENT directory,
not just the file (a path inside an ignored dir stays ignored unless the dir
itself is re-included):

    !.github/
    !.github/workflows/
    !.github/workflows/*.yml

Confirm with `git check-ignore -v .github/workflows/*.yml` and a dry-run
`git add -n .github/workflows/*.yml` before committing. Spot-check for a
duplicate negation line (appending the same rule twice is harmless but sloppy —
clear it before landing).

## Auto-trigger + manual dispatch

Trigger on push to the feature branch, not all branches:
`on.push.branches: [<branch>]`. Also expose `workflow_dispatch` inputs so a run
can be fired on demand (full kernel build vs single target).

## Monitoring runs and reading logs

Check for a `gh` CLI AND a stored OAuth token BEFORE declaring CI logs
inaccessible. On this host `gh` lives at `/opt/data/.local/bin/gh` and
`~/.config/gh/hosts.yml` holds a token (scopes gist/read:org/repo) — so
`gh run view <run-id> --repo <owner>/<repo> --log-failed` returns the EXACT
failing compiler lines, which the unauth'd job-log endpoint (HTTP 403) never
gives you. Only fall back to the `curl` API
(`/repos/.../actions/runs?per_page=N`) when no gh auth exists. On hosts where
`gh` dies with `write tcp ... connection reset by peer` (an IPv6 route issue to
api.github.com), force IPv4 with `curl -4 -sS -H "Authorization: Bearer $(gh
auth token)" ...` — this is the working path; it is NOT a credential problem.
Piping through `python3 -c "import sys,json; ..."` keeps the JSON parseable
when the curl output would otherwise collapse.

## Triggering a build (workflow_dispatch) with input overrides

Kit repos (e.g. Kernel_Action) are thin dispatcher repos whose workflow reads
the actual kernel source from a `KERNEL_SOURCE` repo at a configurable source
branch — by default the user's kitchen-sink branch. When the work to build
lives on a DIFFERENT branch (e.g. `mglru-v5`), dispatch explicitly and pass the
source-branch input; never assume the default builds what you want:

```sh
curl -4 -sS -X POST -H "Authorization: Bearer $(gh auth token)" \
  -H "Accept: application/vnd.github+json" -H "Content-Type: application/json" \
  "https://api.github.com/repos/<owner>/<kit-repo>/actions/workflows/<wf>.yml/dispatches" \
  -d '{"ref":"<kit-branch>","inputs":{"KERNEL_SOURCE_BRANCH":"<source-branch>"}}'
```

HTTP 204 means accepted (no body). Read the triggering workflow file first via
the contents API to learn which inputs exist (and their defaults) before
dispatching. Confirm the run with `.../actions/runs?per_page=3` and watch it
with a background loop that polls `status` until `completed` then prints
`conclusion`.

### Write the watcher's parser in Python, not in nested shell quoting

A background watcher that embeds a Python `-c` snippet inside a shell heredoc
breaks on backslash-escaped quotes: `print(f"{a[\"name\"]}")` is a SyntaxError
inside a single-quoted heredoc, the watcher exits 0 with empty output, and the
notification reads as "completed, nothing to report" when the real result was
never printed. Write the polling loop so the JSON parsing happens in ONE
Python process fed a file or stdin, and keep the shell layer to `curl` plus a
redirect. Test the parser against a saved API response before arming the
watcher — a watcher that cannot fail loudly is worse than no watcher.

### Files over 1 MB do not come back from the contents API

The contents endpoint refuses to inline a blob above ~1 MB and returns an entry
with no `content` key (a `KeyError: 'content'` in the consumer). For a kernel
image or any large artifact, download it by raw URL instead:

```sh
curl -sL --retry 4 -o out.bin \
  "https://raw.githubusercontent.com/<owner>/<repo>/<branch>/<path>"
```

The contents API is still right for listing a branch and for small files
(configs, logs, scripts) — check `size` in the listing before assuming the
content will be inline.

`gh` in this installed version rejects the JSON field name `headCommit` — the
valid field is `headSha` (list available fields with a dummy
`--json <field> --jq` probe that prints the accepted field names, then retry).
This fails the whole command with `Unknown JSON field`, NOT a partial result, so
it can look like a network/auth error — check field names first when a `gh`
query dies.

Concurrency semantics: if the workflow sets `concurrency.group` +
`cancel-in-progress: true`, a new push CANCELS the still-running run for the same
ref. A status of `cancelled` on a superseded run is EXPECTED, not a failure —
judge only the newest run. A run may sit `pending` behind an earlier
`in_progress` on the same group.

## Attribute a failure to the right commit before diagnosing it

A kit repo's `head_sha` is the KIT repo's SHA, not the kernel source's. A push to
the kit's own branch fires a run whose failure has nothing to do with the kernel
branch you are working on — and two runs can sit in the list at once, one from
your `workflow_dispatch` and one from a kit push.

Before reading any log, resolve what the run actually built:

```sh
curl -4 -sS -H "Authorization: Bearer $TOKEN" \
  ".../actions/runs/<id>" | python3 -c "import sys,json;r=json.load(sys.stdin);print(r['event'], r['head_sha'], r['head_repository']['full_name'], r['head_branch'])"
```

If `head_sha` does not resolve on the source repo
(`gh api repos/<owner>/<source-repo>/commits/<sha>` → HTTP 422), the failure
belongs to a different tree. Diagnosing it burns the session and can ship a fix
for a bug that was never in your build. Note the event too: `push` runs on a kit
repo are kit changes, `workflow_dispatch` runs are yours.

## An interactive Kconfig prompt is a CI failure mode, not a build error

A build that dies with no compiler error and a log ending mid-prompt
(`* Restart config...` then `Symbol [Y/n/?] (NEW)`) is `make` waiting on stdin.
The tell is a `(NEW)` marker: the symbol exists in the tree's Kconfig but is
absent from the defconfig, so `syncconfig` re-evaluates and asks. The workflow's
`make defconfig && make olddefconfig` sequence is supposed to be non-interactive,
so when it is not, the defconfig and the Kconfig have drifted apart.

Check the symbol is genuinely committed in the defconfig
(`git show HEAD:<defconfig> | grep <SYM>`) before treating the prompt as the
cause — a symbol present in the working tree but absent from the committed blob
is the usual reason. The fix is on the config side (add the symbol, or seed
`.config` before `olddefconfig`), not in the source the prompt names.

## Downloading build artifacts

Two distinct paths, chosen by whether you need the raw zip or the contents:

- **Raw artifact zip** (e.g. the flashable AnyKernel3 zip, to re-host):
  `gh api repos/{owner}/{repo}/actions/artifacts/{id}/zip` — the endpoint is
  `actions/artifacts/{id}/zip`, NOT `actions/runs/{run}/artifacts/{id}/zip`
  (that nested path 404s). Capture stdout bytes (`subprocess.run(capture_output=True)`)
  and write them to a file; `gh api -o` is unsupported in this gh version.
  This returns the real zip — verify with `zipfile.testzip()` before re-hosting.
- **Expanded artifact contents** (e.g. `resolved-config` to check a built
  `.config`): `gh run download <run> -R <owner>/<repo> -n <artifact-name>
  -D <dir>` expands the artifact into a directory tree. Grep the resulting
  `.config` for the symbols the workflow was supposed to set — a green run
  proves the workflow ran, not that the config symbol actually resolved.
  Use this to verify `CONFIG_*` values in the BUILT config before handing the
  flash zip over.

If a `zip` binary is not installed, prefer the raw-artifact API path over
hand-zipping an expanded directory.
