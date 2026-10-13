#!/usr/bin/env python3
"""Compatibility shim: the harness was renamed to turnpike.

Kept so in-flight agent sessions and old docs that call harness.py keep working.
New code should call turnpike.py.
"""
from turnpike import *          # noqa: F401,F403 -- re-export for `import harness` users
from turnpike import main

if __name__ == "__main__":
    main()
