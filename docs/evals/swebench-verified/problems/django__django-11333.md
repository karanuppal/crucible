# django__django-11333

- Source: SWE-bench Verified
- Repo: `django/django`
- Base commit: `55b68de643b5c2d5f0a8ea7587ab3b2966021ccc`
- Difficulty: `15 min - 1 hour`
- Category: optimization / internal behavior
- Focus: URLResolver cache duplication

## FAIL_TO_PASS

- `test_resolver_cache_default__root_urlconf (urlpatterns.test_resolvers.ResolverCacheTests)`

## Problem statement

Optimization: Multiple URLResolvers may be unintentionally constructed by calls to `django.urls.resolvers.get_resolver`.

### Description

The issue describes duplicate resolver construction and duplicated expensive `_populate()` work when `get_resolver()` is first called before `set_urlconf()` and then later during request handling.
