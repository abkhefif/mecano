---
description: Run lint, typecheck, and tests in sequence with fail-fast behavior
allowed-tools: Bash
---

Execute the quality checks automation script:

bash .claude/commands/scripts/quality.sh

This runs lint → typecheck → tests in sequence, stopping at the first failure.
