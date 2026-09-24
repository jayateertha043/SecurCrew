"""Combined runner: collect, then publish, in one process.

Convenient for manual runs (``workflow_dispatch``) or a single-workflow setup.
The GitHub Actions workflow calls ``collect.py`` and ``publish.py`` directly,
but running this module does both phases sequentially with the same result.
"""

from __future__ import annotations

import sys

import collect
import publish


def run() -> int:
    rc = collect.run()
    if rc != 0:
        return rc
    return publish.run()


if __name__ == "__main__":
    sys.exit(run())
