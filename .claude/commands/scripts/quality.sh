#!/bin/bash
# /quality - Run lint, typecheck, and tests in sequence
# Usage: /quality

# ============================================
# CUSTOMIZE THESE FOR YOUR PROJECT
# ============================================
RUN_LINT=true
RUN_TYPECHECK=true
RUN_TESTS=true
LINT_COMMAND="npm run lint"
TYPECHECK_COMMAND="npm run typecheck"
TEST_COMMAND="npm test"
# ============================================

set -e

echo "🔍 Running quality checks..."
echo ""

STEP=1
TOTAL_STEPS=0
[ "$RUN_LINT" = true ] && ((TOTAL_STEPS++))
[ "$RUN_TYPECHECK" = true ] && ((TOTAL_STEPS++))
[ "$RUN_TESTS" = true ] && ((TOTAL_STEPS++))

# Lint check
if [ "$RUN_LINT" = true ]; then
    echo "Step $STEP/$TOTAL_STEPS: Linting code..."
    if $LINT_COMMAND; then
        echo "✅ Lint passed"
        echo ""
        ((STEP++))
    else
        echo ""
        echo "❌ Quality check failed at: Lint"
        echo "   Fix linting errors and try again"
        exit 1
    fi
fi

# Type check
if [ "$RUN_TYPECHECK" = true ]; then
    echo "Step $STEP/$TOTAL_STEPS: Type checking..."
    if $TYPECHECK_COMMAND; then
        echo "✅ Type check passed"
        echo ""
        ((STEP++))
    else
        echo ""
        echo "❌ Quality check failed at: Type check"
        echo "   Fix type errors and try again"
        exit 1
    fi
fi

# Tests
if [ "$RUN_TESTS" = true ]; then
    echo "Step $STEP/$TOTAL_STEPS: Running tests..."
    if $TEST_COMMAND; then
        echo "✅ Tests passed"
        echo ""
    else
        echo ""
        echo "❌ Quality check failed at: Tests"
        echo "   Fix failing tests and try again"
        exit 1
    fi
fi

echo "✅ All quality checks passed!"
exit 0
