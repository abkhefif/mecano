#!/bin/bash
# /pr-fetch - Fetch and checkout PR branch locally
# Usage: /pr-fetch <pr-number>

# ============================================
# CUSTOMIZE THESE FOR YOUR PROJECT
# ============================================
RUN_TESTS_AFTER_FETCH=true
TEST_COMMAND="./.claude/commands/scripts/test.sh"
SHOW_DIFF_SUMMARY=true
# ============================================

set -e

if [ -z "$1" ]; then
    echo "❌ PR number required"
    echo "   Usage: /pr-fetch <pr-number>"
    exit 1
fi

PR_NUMBER="$1"

echo "🔍 Fetching PR #$PR_NUMBER"
echo ""

# Check for gh CLI
if ! command -v gh &> /dev/null; then
    echo "❌ GitHub CLI (gh) not found"
    echo "   Install from: https://cli.github.com/"
    exit 1
fi

# Check if PR exists
echo "Step 1/5: Verifying PR exists..."
if ! gh pr view "$PR_NUMBER" &>/dev/null; then
    echo "❌ PR #$PR_NUMBER not found"
    exit 1
fi

echo "✅ PR found"
echo ""

# Get PR details
echo "Step 2/5: Fetching PR details..."
PR_TITLE=$(gh pr view "$PR_NUMBER" --json title -q .title)
PR_AUTHOR=$(gh pr view "$PR_NUMBER" --json author -q .author.login)
PR_BRANCH=$(gh pr view "$PR_NUMBER" --json headRefName -q .headRefName)

echo "  Title: $PR_TITLE"
echo "  Author: $PR_AUTHOR"
echo "  Branch: $PR_BRANCH"
echo ""

# Checkout PR
echo "Step 3/5: Checking out PR branch..."
if gh pr checkout "$PR_NUMBER"; then
    echo "✅ Checked out PR #$PR_NUMBER"
    echo ""
else
    echo "❌ Failed to checkout PR"
    exit 1
fi

# Show diff summary
if [ "$SHOW_DIFF_SUMMARY" = true ]; then
    echo "Step 4/5: Diff summary..."

    # Get base branch
    BASE_BRANCH=$(gh pr view "$PR_NUMBER" --json baseRefName -q .baseRefName)

    echo ""
    echo "📊 Changes vs $BASE_BRANCH:"
    git diff --stat "$BASE_BRANCH"..HEAD

    echo ""
    echo "📝 Modified files:"
    git diff --name-status "$BASE_BRANCH"..HEAD

    echo ""
else
    echo "Step 4/5: Skipping diff summary (disabled)"
    echo ""
fi

# Run tests
if [ "$RUN_TESTS_AFTER_FETCH" = true ]; then
    echo "Step 5/5: Running tests to verify PR..."

    if [ -f "$TEST_COMMAND" ]; then
        if bash "$TEST_COMMAND"; then
            echo ""
            echo "✅ Tests passed on PR branch"
        else
            echo ""
            echo "⚠️  Tests failed on PR branch"
            echo "   This PR may have issues"
        fi
    else
        echo "⚠️  Test script not found, skipping..."
    fi
else
    echo "Step 5/5: Skipping tests (disabled)"
fi

echo ""
echo "✅ PR #$PR_NUMBER ready for review"
echo ""
echo "   Current branch: $PR_BRANCH"
echo "   View PR: gh pr view $PR_NUMBER --web"
