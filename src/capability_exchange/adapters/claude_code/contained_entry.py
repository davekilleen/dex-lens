"""``python -m`` shim for the contained collection child process.

Deliberately **not** imported by the package ``__init__`` (so runpy does
not execute a module that is already loaded) and deliberately empty of any
logic: the child's behavior lives in :mod:`.contained`.
"""

import sys

from capability_exchange.adapters.claude_code.contained import main

if __name__ == "__main__":
    sys.exit(main())
