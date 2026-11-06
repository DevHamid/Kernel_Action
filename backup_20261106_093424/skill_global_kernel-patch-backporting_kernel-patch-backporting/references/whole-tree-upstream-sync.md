# Whole-Tree Upstream Sync (absorbing a stable/CIP branch)

For "upstream our kernel to <branch>" tasks where the delta is thousands of files rather than one feature. Every single-patch path fails at this scale:

- a cross-repo `git fetch` of a GB-scale branch times out (and re-times-out on retry);
- a full-delta `git apply --3way` aborts **atomically** because the target repo lacks the upstream blobs — the tree stays untouched while the log reads like a partial success;
- `git diff > patch` then `git apply` in the target tree dies on Android's symlinked `Documentation/devicetree` paths before the first hunk lands (if a patch is still wanted for review, strip those hunks with a `(?m)^(?=diff --git )` split).

Run the merge **inside a clone of the upstream repo** — it already has every blob, so there is no fetch and no `--3way` blob hunt.

## Procedure

1. **Verify both refs at use time, inside the upstream clone.**

   ```bash
   base=$(git rev-parse <vanilla-tag>^{commit}); tip=$(git rev-parse <branch>^{commit})
   echo "$base $tip"
   ```

   A base SHA remembered from an earlier probe is not evidence. A wrong base misdirects every diff, apply and conflict judgement that follows, silently.

2. **Scratch worktree of the upstream clone**, emptied except `.git`:

   ```bash
   git worktree add <wt> --detach <tip>
   cd <wt> && find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
   ```

   Copy the target tree in with a tar pipe — handles GB-scale trees, needs no `rsync`:

   ```bash
   tar -C <target-tree> --exclude=.git -cf - . | tar -C <wt> -xf -   # background for large trees
   ```

   Verify markers after the copy, before grafting: vendor dirs present, feature sources present, tree size within a few percent of the source. A copy that dies mid-way leaves a plausible-looking 900 MB tree with the feature files missing — check for the markers, not the size alone.

3. **Commit the target state and graft it onto the base.**

   ```bash
   git add -A && git commit -m 'ours'
   new=$(git commit-tree $(git write-tree) -p "$base" -m 'graft') && git reset --hard "$new"
   ```

   The parent MUST be `$base`. Grafted on `$tip` (or anything containing theirs), the following merge prints **"Already up to date." with zero conflicts** — a no-op that reads exactly like a clean sync and yields a summary full of false success. This is the highest-cost trap in the procedure.

4. `git merge --no-ff "$tip"`, then `git diff --name-only --diff-filter=U > conflicts.txt` as the work list.

5. **Classify by porcelain code before reading any content:**

   | Code | Meaning | Action |
   |---|---|---|
   | `UU`, `AA` | both modified / both added | real conflict — triage per file |
   | `DD` | deleted both sides | `git rm`, safe |
   | `DU`/`UD` | modify-delete | usually one tree moved the file — confirm the real owner first |
   | `AU` | added by us | vendor copy of upstream content — `git checkout --ours -- <f> && git add <f>` |

   Before `git rm`-ing the upstream path of a `DU`/`UD`, confirm the path is genuinely absent from your tree: vendor trees relocate files, and removing a path your build still compiles deletes a file you need.

6. **Triage by what the CI defconfig compiles, not by file count.** Grep the defconfig for each conflicted subsystem's config keys — dead filesystems, other-architecture code, unused sound/USB/media drivers, off-SoC subsystems.

   - Conflicts wholly inside never-compiled subsystems: `git checkout --theirs -- <f> && git add <f>`. Zero build risk, upstream's post-EOL security fixes come for free, and this is usually the large majority of the list.
   - Hand-merge only files where both trees genuinely modified compiled code.

   Take the build defconfig from the CI workflow's `env:` block (`KERNEL_CONFIG=vendor/<device>-oss-perf_defconfig`), not from the device name — the `-oss-` variant is common and editing the wrong file hides every config decision.

7. **Per-hunk decisions need the consumers in hand.** If your side carries a fork convention consumed elsewhere in your tree (macro style, toolchain/compiler-flag wiring your own CI depends on), keep ours inside the conflicting region and take upstream's changes elsewhere in the file. A wholesale `--theirs` compiles your consumers against upstream's shape and breaks files that never conflicted. Grep the consumers before choosing a side.

8. **Finish:** `git diff --name-only --diff-filter=U` must be empty. Then express the result as a diff against your real branch and commit it there — the merge only ever existed in the scratch clone, and one tree should not carry two histories for the same content.

## Scale sanity checks

- `git diff --name-only --diff-filter=U | wc -l` after the merge: one-sided divergence auto-merges, so a ~16k-file divergence should yield conflicts in the low hundreds. Conflicts ≈ divergence means the base is wrong — back to step 1.
- `git diff --shortstat <vanilla> <your-tree>` is the honest size of what you are absorbing, and belongs in the summary.
- A log full of "Applied patch to ... cleanly" while the tree is unchanged means the operation aborted — verify the tree, never the log.

## Reporting

Give the user: base and tip SHAs, conflict count, the auto-resolved vs hand-merged split, and which features ride along in the same pass. Report only what is verified — never present a merge as more than "conflicts resolved" when no build has run.
