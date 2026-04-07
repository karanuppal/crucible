# django__django-13195

- Source: SWE-bench Verified
- Repo: `django/django`
- Base commit: `156a2138db20abc89933121e4ff2ee2ce56a173a`
- Difficulty: `15 min - 1 hour`
- Category: API behavior / regression
- Focus: `delete_cookie()` preserves `samesite`

## FAIL_TO_PASS

- `test_delete_cookie_samesite (responses.test_cookie.DeleteCookieTests)`
- `test_delete_cookie_secure_samesite_none (responses.test_cookie.DeleteCookieTests)`
- `test_session_delete_on_end (sessions_tests.tests.SessionMiddlewareTests)`
- `test_session_delete_on_end_with_custom_domain_and_path (sessions_tests.tests.SessionMiddlewareTests)`
- `test_cookie_setings (messages_tests.test_cookie.CookieTests)`

## Problem statement

`HttpResponse.delete_cookie()` should preserve the cookie's `samesite` behavior when expiring cookies, to avoid browsers rejecting or mishandling deletion headers.
