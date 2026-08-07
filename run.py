#!/usr/bin/env python3
"""Convenience launcher so ``python run.py`` works from the repo root."""

from app.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
