#!/bin/bash
# /commit - Smart commit workflow with quality checks
# Usage: /commit [commit-message]

# ============================================
# CUSTOMIZE THESE FOR YOUR PROJECT
# ============================================
RUN_QUALITY_CHECKS=true
AUTO_PUSH=false
QUALITY_CHECK_COMMAND="./.claude/commands/scripts/quality.sh"
# ============================================

echo "📝 Smart Commit Workflow"
echo ""

# Check for changes
echo "Step 1/5: Checking for changes..."
if [ -z "$(git status --porcelain)" ]; then
    echo "❌ No changes to commit"
    exit 1
fi

echo "✅ Changes detected"
echo ""

# Show what will be committed
echo "Step 2/5: Reviewing changes..."
git status --short
echo ""

# Suggest commit message prefix based on changed files
suggest_prefix() {
    local changes=$(git status --porcelain)

    # Check for common patterns
    if echo "$changes" | grep -q "test\|spec"; then
        echo "test"
    elif echo "$changes" | grep -q "\.md$"; then
        echo "docs"
    elif echo "$changes" | grep -q "package\.json\|requirements\.txt\|go\.mod\|Cargo\.toml"; then
        echo "deps"
    elif echo "$changes" | grep -q "^A"; then
        echo "feat"
    elif echo "$changes" | grep -q "^D"; then
        echo "remove"
    else
        echo "update"
    fi
}

SUGGESTED_PREFIX=$(suggest_prefix)
echo "💡 Suggested prefix: $SUGGESTED_PREFIX"
echo ""

# Run quality checks
if [ "$RUN_QUALITY_CHECKS" = true ]; then
    echo "Step 3/5: Running quality checks..."

    if [ -f "$QUALITY_CHECK_COMMAND" ]; then
        if bash "$QUALITY_CHECK_COMMAND"; then
            echo "✅ Quality checks passed"
            echo ""
        else
            echo ""
            echo "❌ Quality checks failed"
            echo "   Fix issues before committing or disable quality checks"
            exit 1
        fi
    else
        echo "⚠️  Quality check script not found, skipping..."
        echo ""
    fi
else
    echo "Step 3/5: Skipping quality checks (disabled)"
    echo ""
fi

# Stage changes
echo "Step 4/5: Staging changes..."
git add -A
echo "✅ All changes staged"
echo ""

# Commit
echo "Step 5/5: Creating commit..."

if [ -n "$1" ]; then
    # Use provided message
    COMMIT_MSG="$*"
else
    # Prompt for message
    echo "Enter commit message:"
    read -r COMMIT_MSG

    if [ -z "$COMMIT_MSG" ]; then
        echo "❌ Commit message required"
        exit 1
    fi
fi

if git commit -m "$COMMIT_MSG"; then
    COMMIT_HASH=$(git rev-parse --short HEAD)
    echo "✅ Committed: $COMMIT_HASH"
    echo ""

    # Optional: Push
    if [ "$AUTO_PUSH" = true ]; then
        echo "Pushing to remote..."
        CURRENT_BRANCH=$(git branch --show-current)

        if git push origin "$CURRENT_BRANCH" 2>/dev/null; then
            echo "✅ Pushed to origin/$CURRENT_BRANCH"
        else
            # Try pushing with upstream
            if git push -u origin "$CURRENT_BRANCH"; then
                echo "✅ Pushed and set upstream to origin/$CURRENT_BRANCH"
            else
                echo "⚠️  Push failed - you may need to push manually"
            fi
        fi
    else
        echo "📝 Ready to push when you're ready"
        echo "   Run: git push"
    fi

    echo ""
    echo "✅ Commit workflow complete!"
    exit 0
else
    echo ""
    echo "❌ Commit failed"
    exit 1
fi
