# Changelog

Entries below start at v0.8.3, where this file was introduced. For v0.1.0–v0.8.2,
see the [GitHub releases](https://github.com/patchwright/wildlint/releases) and `git tag -l`.

## v0.8.6 (2026-07-25)
- WL008: flag `time.time()` used for elapsed timing (use `perf_counter`)

## v0.8.5 (2026-07-25)
- WL007: flag `json.dump`/`json.dumps` without `default=` in numpy-adjacent code

## v0.8.4 (2026-07-25)
- WL003: guard-awareness — suppress when `len(x) >= N` is already in scope

## v0.8.3 (2026-07-25)
- WL006: flag `d.get(k) or None` falsy-collapse antipattern
