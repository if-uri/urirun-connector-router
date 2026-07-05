# urirun-connector-router


## AI Cost Tracking

![PyPI](https://img.shields.io/badge/pypi-costs-blue) ![Version](https://img.shields.io/badge/version-0.2.1-blue) ![Python](https://img.shields.io/badge/python-3.9+-blue) ![License](https://img.shields.io/badge/license-Apache--2.0-green)
![AI Cost](https://img.shields.io/badge/AI%20Cost-$0.30-orange) ![Human Time](https://img.shields.io/badge/Human%20Time-1.8h-blue) ![Model](https://img.shields.io/badge/Model-openrouter%2Fqwen%2Fqwen3--coder--next-lightgrey)

- 🤖 **LLM usage:** $0.3000 (2 commits)
- 👤 **Human dev:** ~$178 (1.8h @ $100/h, 30min dedup)

Generated on 2026-07-05 using [openrouter/qwen/qwen3-coder-next](https://openrouter.ai/qwen/qwen3-coder-next)

---



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


## License

Licensed under Apache-2.0.
