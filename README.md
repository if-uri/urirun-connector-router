# urirun-connector-router

`urirun-connector-router` is the URI-routing kernel for ifURI/urirun.

It answers, before a natural-language plan is executed:

- which machine or node each URI step will run on,
- whether the URI target is known,
- whether a route/capability descriptor matches,
- whether an optional live node probe is reachable,
- whether the route is read-only or mutating, and whether safety denies it.

The pure API is dependency-light:

```python
from urirun_connector_router.routing import accept_plan, diagnose_plan

report = diagnose_plan(
    [{"uri": "kvm://host/screen/query/capture"}],
    {"nodes": [{"name": "lenovo", "url": "http://192.168.188.201:8765"}],
     "routes": [{"uri": "kvm://host/screen/query/capture", "node": "lenovo"}]},
)

verdict = accept_plan(
    [{"uri": "kvm://host/screen/query/capture"}],
    {"routes": [{"uri": "kvm://host/screen/query/capture", "node": "host",
                 "meta": {"contract": {"effect": "query"}}}]},
)
```

When `urirun` is installed, the package also exposes read-only `router://` routes:

- `router://host/route/query/resolve`
- `router://host/plan/query/diagnose`
- `router://host/plan/query/accept`
- `router://host/mesh/query/targets`

`diagnose` reports what is known about each candidate step. `accept` is the
deterministic pre-dispatch predicate used by autonomous flows: a plan is accepted
only when all steps route cleanly and contract metadata does not contradict the
URI effect (`query` vs `command`).
