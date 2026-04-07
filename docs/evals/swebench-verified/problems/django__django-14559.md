# django__django-14559

- Source: SWE-bench Verified
- Repo: `django/django`
- Base commit: `d79be3ed39b76d3e34431873eec16f6dd354ab17`
- Difficulty: `15 min - 1 hour`
- Category: behavioral feature enhancement
- Focus: `bulk_update()` returns matched row count

## FAIL_TO_PASS

- `test_empty_objects (queries.test_bulk_update.BulkUpdateTests)`
- `test_large_batch (queries.test_bulk_update.BulkUpdateTests)`
- `test_updated_rows_when_passing_duplicates (queries.test_bulk_update.BulkUpdateTests)`

## Problem statement

Include number of rows matched in `bulk_update()` return value.

### Description

Unlike `update()`, `bulk_update()` returns `None`. The issue asks for an integer return value representing matched/updated rows.
