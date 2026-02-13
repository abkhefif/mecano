#!/bin/bash
# /pr-create - Create PR with generated description
# Usage: /pr-create [base-branch]

# ============================================
# CUSTOMIZE THESE FOR YOUR PROJECT
# ============================================
DEFAULT_BASE_BRANCH="main"  # or master, develop, etc.
RUN_FINAL_CHECKS=true
FINAL_CHECK_COMMAND="./.claude/commands/scripts/quality.sh"
AUTO_OPEN_BROWSER=false
# ============================================

set -e

echo "🚀 Creating Pull Request"
echo ""

# Get base branch
BASE_BRANCH="${1:-$DEFAULT_BASE_BRANCH}"
CURRENT_BRANCH=$(git branch --show-current)

if [ "$CURRENT_BRANCH" = "$BASE_BRANCH" ]; then
    echo "❌ Cannot create PR from $BASE_BRANCH to itself"
    echo "   Create a feature branch first"
    exit 1
fi

echo "  From: $CURRENT_BRANCH"
echo "  To:   $BASE_BRANCH"
echo ""

# Check for gh CLI
if ! command -v gh &> /dev/null; then
    echo "❌ GitHub CLI (gh) not found"
    echo "   Install from: https://cli.github.com/"
    exit 1
fi

# Run final checks
if [ "$RUN_FINAL_CHECKS" = true ]; then
    echo "Step 1/4: Running final quality checks..."

    if [ -f "$FINAL_CHECK_COMMAND" ]; then
        if bash "$FINAL_CHECK_COMMAND"; then
            echo "✅ Quality checks passed"
            echo ""
        else
            echo ""
            echo "❌ Quality checks failed"
            echo "   Fix issues before creating PR"
            exit 1
        fi
    else
        echo "⚠️  Quality check script not found, skipping..."
        echo ""
    fi
else
    echo "Step 1/4: Skipping quality checks (disabled)"
    echo ""
fi

# Push branch
echo "Step 2/4: Pushing branch to remote..."
if git push -u origin "$CURRENT_BRANCH" 2>/dev/null || git push origin "$CURRENT_BRANCH"; then
    echo "✅ Branch pushed"
    echo ""
else
    echo "❌ Failed to push branch"
    exit 1
fi

# Generate PR description from commits
echo "Step 3/4: Generating PR description..."

# Get commit messages since base branch
COMMITS=$(git log --pretty=format:"- %s" "$BASE_BRANCH"..HEAD)

if [ -z "$COMMITS" ]; then
    echo "⚠️  No commits found since $BASE_BRANCH"
    COMMITS="- Initial changes"
fi

# Get file change summary
FILES_CHANGED=$(git diff --name-status "$BASE_BRANCH"..HEAD | wc -l)
INSERTIONS=$(git diff --shortstat "$BASE_BRANCH"..HEAD | grep -oP '\d+(?= insertion)' || echo "0")
DELETIONS=$(git diff --shortstat "$BASE_BRANCH"..HEAD | grep -oP '\d+(?= deletion)' || echo "0")

PR_TITLE=$(git log -1 --pretty=format:"%s")

PR_BODY=$(cat <<EOF
## Summary

$COMMITS

## Changes
- **Files changed:** $FILES_CHANGED
- **Insertions:** +$INSERTIONS
- **Deletions:** -$DELETIONS

## Test Plan
- [ ] Tests pass locally
- [ ] Code reviewed
- [ ] Documentation updated (if needed)

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)

echo "✅ Description generated"
echo ""

# Create PR
echo "Step 4/4: Creating pull request..."

if [ "$AUTO_OPEN_BROWSER" = true ]; then
    PR_URL=$(gh pr create --base "$BASE_BRANCH" --title "$PR_TITLE" --body "$PR_BODY" --web)
else
    PR_URL=$(gh pr create --base "$BASE_BRANCH" --title "$PR_TITLE" --body "$PR_BODY")
fi

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Pull request created!"
    echo ""
    echo "   $PR_URL"
    echo ""
    exit 0
else
    echo ""
    echo "❌ Failed to create PR"
    exit 1
fi
