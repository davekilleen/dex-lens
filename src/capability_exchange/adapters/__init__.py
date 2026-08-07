"""Host Adapter implementations (M-A).

One subpackage per adapter. Every adapter here lives on the diagnosis side
and is therefore read-only by construction (non-negotiable boundary 1): the
same structural scan that guards :mod:`capability_exchange.adapter` runs at
import time over every adapter subpackage — a public callable whose name
denotes a mutating operation breaks the import, not just a test.
"""
