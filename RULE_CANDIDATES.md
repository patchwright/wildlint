# Rule candidates — evaluated, not shipped

Running log of WL006+ candidates that were designed+validated but did NOT ship,
so the next rule-authoring pass doesn't re-derive them. A candidate ships only
if it surfaces REAL bugs at near-zero FP in shippable (IN_BAND, non-denylisted,
on-master-HEAD, untaken) repos — the same bar the gift-PR fleet uses.

## 2026-07-07 — two candidates evaluated, neither shipped

### Candidate A: `os.path.join(a, "/absolute-literal")` silent base-discard
- **Idea:** `os.path.join(BASE, "/etc/x")` returns `"/etc/x"` (BASE silently
  discarded). Classic footgun, AST-detectable when the absolute arg is a literal.
- **Validation:** grepped a large site-packages tree (1273 `os.path.join` calls).
  **0** instances of a non-first absolute-literal arg. Real but vanishingly rare
  in practice (absolute paths are almost always variables, not literals).
- **Verdict: DEAD (0/1273 yield).** Same failure mode as the WL001 dogfood — a
  real pattern that doesn't occur in surviving code. Do not ship.

### Candidate B: `.lstrip/.rstrip/.strip` with a multi-char literal (char-set vs prefix/suffix confusion)
- **Idea:** `s.lstrip("data:")` strips any combo of `d/a/t/:` from the left, not
  the prefix `"data:"`. Fix is usually `removeprefix`/`removesuffix` (3.9+). A
  well-known footgun.
- **Validation:** 304 multi-char-literal strip occurrences in site-packages.
  MIXED: many are intentional char-sets (`"<> '"`, `"|{}|"`, regex `"bu"` flags,
  `"\0"`), several are real bugs (`.lstrip("Version ")`, `.rstrip("/n")` botched
  escape meant `"\n"`, `.strip("```sql")`).
- **Sub-pattern "botched escape" (`.rstrip("/n")` etc.):** near-zero FP, but the
  flagship instance (`huggingface_hub`) is (a) off master HEAD already and
  (b) a DENYLISTED org — not shippable.
- **Verdict: NOT SHIPPED.** The broad pattern is high-FP (would erode wildlint's
  near-zero-FP reputation if defaulted). A narrow sub-pattern (literal contains
  `/\w` suggesting a botched escape, OR a ≥3-letter keyword adjacent to
  punctuation like `"data:"`/`"Version "`/`"```"`) could ship as a PEDANTIC-tier
  rule (like WL003) IF a clean instance surfaces in a shippable repo. Re-assess
  then; do not speculatively ship on the current evidence.

## Meta-finding (2026-07-07)
Both candidates mirror the gift-PR find-rate drought: the AST-detectable surface
is thin, and real hits cluster in denylisted big orgs or are already fixed
upstream. The durable rule-growth mechanism stays the documented slow loop:
**each cleanly-detectable SHIPPED bug class → a rule; each shipped numerical bug
→ a property template.** Speculative rule-authoring ahead of a shipped class
produces low-yield/high-FP rules. Grow at "one real bug at a time."
