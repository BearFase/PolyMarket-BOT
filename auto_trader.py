#!/usr/bin/env python3
"""Inactive paper-entry runner.

Whale-consensus analysis has been removed from the active application
pipeline. The research modules remain in the repository for possible future
redesign, but this runner cannot create paper positions.
"""

INACTIVE_MESSAGE = "No active paper-entry strategy is configured."


def main():
    print(INACTIVE_MESSAGE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
