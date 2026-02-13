---
description: Auto-detect and run tests with coverage
allowed-tools: Bash
argument-hint: [optional-path-or-pattern]
---

Execute the test automation script with coverage reporting:

bash .claude/commands/scripts/test.sh $ARGUMENTS

The script will auto-detect the test framework (Jest, Vitest, pytest, Go, Rust) and run with coverage.
