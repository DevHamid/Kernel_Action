# Verifying a patch/delta apply actually landed

Goal: prove, per file a delta patch touched, which version the final tree carries:
target-intended, original/vendor baseline, or a mangled merge.

## Why trust is a problem

`git apply` on a tree assembled from raw file downloads lacks the pre-image blobs it
needs for the 3-way merge. It then silently falls back to *direct application*, and a
context mismatch emits `patch does not apply` — the whole file's hunks are DROPPED with
no conflict marker and no warning. So "applied N files cleanly" and "N failed" are
both silent: a failed file simply keeps the old version, and nothing flags it.

## Drill

1. Extract the rejected-file list from the apply log:
   `grep -E "patch does not apply" <apply.log> | sed 's/error: //; s/: patch does not apply//' | sort -u`
2. Per file, three boundary checks:
   - `git cat-file -e HEAD:<path>` — exists in the final tree?
   - `git show HEAD:<path> | cmp -s - <src>/<path>` — equals the intended source (e.g. CIP tree)?
   - `git show <baseline>:<path> | cmp -s - <(git show HEAD:<path>)` — equals the earliest visible baseline commit?
3. Classify:
   - HEAD == baseline AND HEAD != target → file kept its original version; the delta
     was dropped cleanly (vendor side). Most common, and the benign-probable case.
   - HEAD != baseline → file changed after the weld: inspect; hand-fix (good) or
     mangled merge (bad).
   - HEAD == target → the delta is present.

## Pitfalls

- **Broken/grafted history still allows per-file comparison.** `git rev-list
  --max-parents=0`, `git diff <base>`, and `git show --stat <commit>` FAIL when a
  parent commit object is missing (`error: Could not read <sha>`). `git show
  <commit>:<path>` and `git cat-file -e <commit>:<path>` read only the tree/blob and
  work fine — use them. The baseline can be the oldest commit whose tree reads; its
  missing parent does not matter.
- **Do not trust the target source as ground truth if the delta was generated between
  two revisions.** Verify the target tree itself carries the change
  (`grep` for the signature line) before treating it as the "intended" endpoint.
- **Present a signature line as proof.** Pick the distinctive added/changed line the
  patch intends and `grep` the final tree — presence/absence is the irrefutable
  evidence for the report, better than raw diff counts (which are dominated by the
  whole-tree version gap).
