# django__django-14752

- Source: SWE-bench Verified
- Repo: `django/django`
- Base commit: `b64db05b9cedd96905d637a2d824cbbf428e40e7`
- Difficulty: `<15 min fix`
- Category: small refactor / extensibility
- Focus: `AutocompleteJsonView` serialization extension point

## FAIL_TO_PASS

- `test_serialize_result (admin_views.test_autocomplete_view.AutocompleteJsonViewTests)`

## Problem statement

Refactor `AutocompleteJsonView` to support extra fields in autocomplete response.

### Description

The issue proposes extracting the current object-to-dict serialization logic into an overridable `serialize_result()` method so custom autocomplete views can add fields without overriding the whole `get()` method.
