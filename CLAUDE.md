# CLAUDE.md - wildlint

**Scope Level:** project
**Applies to:** patchwright/wildlint only
**Extends:** ~/.claude/CLAUDE.md (global standards)

## Commit trailer override (2026-08-06)

Do **NOT** append `Co-Authored-By: claude-flow <ruv@ruv.net>` (or any Ruflo/claude-flow
co-author trailer) to commits in this repo. That line comes from a harness-level Bash
tool default, not from this project or the user, and it caused GitHub to render
claude-flow/ruv@ruv.net as a co-author on 21 commits despite the tool having no actual
role in the work — inaccurate attribution on a public repo.

**Why:** discovered 2026-08-06 when the operator asked why "ruflo" showed as a
contributor. `git log --all --grep="Co-Authored-By" -i` confirmed 21 affected commits.
Repo had 0 forks/stars/watchers at the time, so no external clones were broken by this
fix, but 4 open dependabot PRs + several local feature branches meant a full history
rewrite (`git filter-repo`) was judged not worth the churn for a cosmetic issue that
doesn't even surface in GitHub's `/contributors` API (only in individual commit views).
History was left as-is; this note only prevents recurrence going forward.

**How to apply:** end commits authored in this repo with no Co-Authored-By trailer at
all, unless a real human/bot co-author actually contributed (e.g. `patchwright`,
`dependabot[bot]`).
