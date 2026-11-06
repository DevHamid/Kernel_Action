# Skill library maintenance — importing / updating third-party skill packs

When a user asks to "add this repo as a native skill" (a skill/knowledge repo such as anti-slop, superpowers, etc.), treat it as a library-sync operation, not a fresh install.

## Procedure
1. **Check whether it's already installed first.** Enumerate the profile's skills (`skills_list`, or glob `$HERMES_HOME/profiles/<profile>/skills/**`). Popular agent skill packs are frequently already present — blind-creating a duplicate fragments the library and the same rule later lives in two files.
2. **Fresh shallow clone upstream** for diffing: `git clone --depth 1 <url>`. Never diff against memory.
3. **Diff installed vs upstream per skill.** The repo ships its rules as a stable ID scheme (e.g. `R-01`…`R-40`); compare rule-ID sets and the declared `version:` between the installed and repo `SKILL.md`. Installed count < repo count ⇒ the installed pack is stale. An older installed version with fewer rules is a drift bug, not a different choice.
4. **Update in place — copy the BODY, keep the installed frontmatter.** The installed `SKILL.md` frontmatter carries the Hermes adaptation (platforms, tags, related_skills, author). Overwriting the whole file with the repo's raw frontmatter strips that adaptation. Split on the first `---\n`…`\n---\n` and splice: repo body + installed frontmatter.
5. **Copy the reference files the new body points to** (e.g. `WCAG.md`, `CORE-WEB-VITALS.md`) into the same skill's `references/`. A body that references a missing file is a latent break.
6. **Bump the frontmatter `version:` to the repo version** so the next diff sees the pack as current.
7. **Verify after the update**: re-grep rule IDs — installed set must equal repo set for every skill touched; confirm each `SKILL.md` still starts with `---\n` and the frontmatter block contains `name:`; confirm the new reference files landed.
8. **Clean up** the scratch clone.

## Pitfalls
- **A `"\nname: "` substring probe is a false negative** on valid frontmatter (the first key is typically `name:` directly after `---\n`, so `"\nname: "` does not match). To check frontmatter presence, parse the first line after the opening `---\n` rather than grep for a leading-newline name.
- **Only sync what's actually stale.** If a skill's rule count already matches upstream, leave it untouched — don't rewrite working files.
- **Per-skill rule counts are the ground truth**, not repo `README` claims; the README can lag the shipped skills.
- The scratch clone is disposable — delete it before finishing so it isn't scanned or committed later.
