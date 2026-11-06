---
name: antislop
version: 3.2.24
author: Miqdad Badjuber
license: MIT
description: Use when building UI, copy, or code to filter AI slop.
metadata:
  hermes:
    tags: [ui, copywriting, design, quality]
    related_skills: [writing-skills]
---

# Anti-Slop Filter

> Anti-Slop: Rules for AI Coding Agents. Filter out generic AI-generated UI, copy, and code patterns.

## When to Use
- **Use when** building or editing websites, web apps, or interfaces (`references/antislop-ui.md`).
- **Use when** writing headlines, CTAs, product copy (`references/antislop-copywriting.md`).
- **Use when** handling accessibility, contrast, focus states (`references/antislop-human.md`).
- **Use when** building mobile layouts and responsive grids (`references/antislop-layoutmobile.md`).
- **Use when** writing or auditing code comments (`references/antislop-code.md`).

## Core Principle
Technique with purpose, never technique as default. Read `references/antislop.md` for the full core rules.

## Updating this skill
This is a third-party install from https://github.com/miqdadbadjuber/anti-slop. To bump it to a newer release:
1. Clone the repo (`git clone --depth 1`). The repo carries one folder per sub-skill under `skills/<name>/`, each with a single `SKILL.md`.
2. Copy `skills/antislop/SKILL.md` → `references/antislop.md`, and `skills/<name>/SKILL.md` → `references/<name>.md` for each sub-skill (ui, copywriting, human, layoutmobile, code).
3. Also copy support scripts and reference dirs from the human/ui folders (`contrast-check.py`, `contrast-mcp.py`, `references/*`).
4. Bump `version:` in this file's frontmatter to match the repo's `skills/antislop/VERSION`.
5. Verify with skill_view that linked files resolve.
