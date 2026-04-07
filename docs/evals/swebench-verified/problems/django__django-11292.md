# django__django-11292

- Source: SWE-bench Verified
- Repo: `django/django`
- Base commit: `eb16c7260e573ec513d84cb586d96bdf508f3173`
- Difficulty: `15 min - 1 hour`
- Category: small CLI feature
- Focus: management command `--skip-checks`

## FAIL_TO_PASS

- `test_skip_checks (user_commands.tests.CommandRunTests)`

## Problem statement

Add `--skip-checks` option to management commands.

### Description

Management commands already support a `skip_checks` stealth option internally. The benchmark issue asks to expose it as a command-line option so users can skip system checks explicitly from the CLI.
