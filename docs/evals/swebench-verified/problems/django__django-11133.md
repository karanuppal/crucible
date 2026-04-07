# django__django-11133

- Source: SWE-bench Verified
- Repo: `django/django`
- Base commit: `879cc3da6249e920b8d54518a0ae06de835d7373`
- Difficulty: `<15 min fix`
- Category: type/interop bug
- Focus: `HttpResponse` memoryview handling

## FAIL_TO_PASS

- `test_memoryview_content (httpwrappers.tests.HttpResponseTests)`

## Problem statement

HttpResponse doesn't handle memoryview objects.

### Description

`HttpResponse(memoryview(b"My Content"))` currently yields content like `b'<memory at ...>'` instead of the underlying bytes.

### Reproduction snippet

```python
from django.http import HttpResponse

response = HttpResponse(memoryview(b"My Content"))
print(response.content)
```

Expected: `b"My Content"`.
