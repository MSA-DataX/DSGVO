"""Dev launcher for Windows.

The uvicorn CLI calls ``asyncio.run()`` *before* it imports ``app.main``,
which means the event-loop policy set at the top of main.py runs too
late on Windows — by then the SelectorEventLoop is already in use and
Playwright's ``asyncio.create_subprocess_exec`` call (needed to spawn
Chromium) raises ``NotImplementedError``.

This launcher sets the Proactor policy *before* importing uvicorn, then
boots the server programmatically. Run this instead of ``uvicorn …`` on
Windows::

    python run_dev.py

No ``--reload`` because reload spawns a child process that regularly
does *not* inherit the policy we set here. Restart manually after code
changes (Ctrl+C, re-run).
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn  # noqa: E402  -- must come after the policy override

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8080,
        reload=False,
        log_level="info",
    )
