# Python Workers imports

`from workers import WorkerEntrypoint, Response` is **not** the stdlib.
The module is `workers-runtime-sdk`, vendored by **pywrangler** into `python_modules/`.

## What failed (2026-08-20, wrangler 4.124.0, code 10021)

`npx wrangler deploy` uploaded `app/entry.py` without vendoring `workers`.
Pyodide then raised `ModuleNotFoundError: No module named 'workers'`.
Cloudflare hint: workers-py >= 1.9, or `disable_python_external_sdk`.

Do **not** set `disable_python_external_sdk` here. That flag is the old embedded SDK.
We want the external SDK + pywrangler vendor path.

## Required chain

1. `pyproject.toml` lists runtime deps (`stripe`, `fastapi`, …) and dev group `workers-py>=1.9`, `workers-runtime-sdk`.
2. `uv run pywrangler sync` writes `python_modules/`.
3. `uv run pywrangler deploy` (not bare wrangler) bundles those modules.
4. `compatibility_flags = ["python_workers"]` stays on.

## Next import that will fail if skipped

`import stripe` at the top of `app/entry.py` is also not stdlib.
It must be in `[project].dependencies` so pywrangler vendors it. FastAPI/asgi stay lazy.
