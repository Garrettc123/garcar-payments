from __future__ import annotations

import asyncio
import os

import uvicorn

from app.e2e_worker import worker_loop


async def main() -> None:
    stop = asyncio.Event()
    config = uvicorn.Config("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), log_level="info")
    server = uvicorn.Server(config)
    api_task = asyncio.create_task(server.serve(), name="api")
    worker_task = asyncio.create_task(worker_loop(stop), name="checkout-worker")
    try:
        await api_task
    finally:
        stop.set()
        worker_task.cancel()
        await asyncio.gather(worker_task, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
