# Custom Middleware

Identity middleware (`user-identity`) runs automatically in HTTP mode.
Most apps never need to configure middleware.

For advanced use cases, you can add custom ASGI middleware or disable
auth entirely by passing a `middleware` list to `create_mcp_cli` or `build_asgi`:

```yaml
# Custom middleware alongside identity
middleware:
  - my_app.auth.RateLimiter
  - user-identity

# No auth (explicitly empty)
middleware: []
```

When `middleware` is specified, identity middleware is NOT injected
automatically — include `user-identity` explicitly if you still want
it.

Custom middleware must match the constructor signature:

```python
def __init__(self, app, verifier, store=None)
```

Middleware is stacked in order — first in the list is outermost
(processes requests first).
