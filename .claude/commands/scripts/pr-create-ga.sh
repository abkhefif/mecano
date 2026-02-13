#!/bin/bash
# /pr-create-ga - Create PR with GitHub Actions integration
# Usage: /pr-create-ga [base-branch]
#
# This is an extended example showing how to integrate PR creation
# with GitHub Actions for automated review workflows.

# ============================================
# CUSTOMIZE THESE FOR YOUR PROJECT
# ============================================
DEFAULT_BASE_BRANCH="main"
RUN_FINAL_CHECKS=true
FINAL_CHECK_COMMAND="./.claude/commands/scripts/quality.sh"
AUTO_OPEN_BROWSER=false

# GitHub Actions webhook configuration
ENABLE_GA_WEBHOOK=false  # Set to true to enable
GA_WEBHOOK_URL=""  # Your GitHub Actions webhook URL
GA_WORKFLOW_ID="pr-review.yml"  # The workflow to trigger
# ============================================

set -e

echo "🚀 Creating Pull Request (with GitHub Actions)"
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
    echo "Step 1/5: Running final quality checks..."

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
    echo "Step 1/5: Skipping quality checks (disabled)"
    echo ""
fi

# Push branch
echo "Step 2/5: Pushing branch to remote..."
if git push -u origin "$CURRENT_BRANCH" 2>/dev/null || git push origin "$CURRENT_BRANCH"; then
    echo "✅ Branch pushed"
    echo ""
else
    echo "❌ Failed to push branch"
    exit 1
fi

# Generate PR description
echo "Step 3/5: Generating PR description..."

COMMITS=$(git log --pretty=format:"- %s" "$BASE_BRANCH"..HEAD)

if [ -z "$COMMITS" ]; then
    echo "⚠️  No commits found since $BASE_BRANCH"
    COMMITS="- Initial changes"
fi

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

## Automated Review
This PR will trigger automated review via GitHub Actions.

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)

echo "✅ Description generated"
echo ""

# Create PR
echo "Step 4/5: Creating pull request..."

if [ "$AUTO_OPEN_BROWSER" = true ]; then
    PR_URL=$(gh pr create --base "$BASE_BRANCH" --title "$PR_TITLE" --body "$PR_BODY" --web)
else
    PR_URL=$(gh pr create --base "$BASE_BRANCH" --title "$PR_TITLE" --body "$PR_BODY")
fi

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Failed to create PR"
    exit 1
fi

# Extract PR number from URL
PR_NUMBER=$(echo "$PR_URL" | grep -oP '\d+$')

echo "✅ Pull request created: #$PR_NUMBER"
echo ""

# Trigger GitHub Actions workflow (optional)
if [ "$ENABLE_GA_WEBHOOK" = true ]; then
    echo "Step 5/5: Triggering GitHub Actions workflow..."

    # Get repository info
    REPO_OWNER=$(gh repo view --json owner -q .owner.login)
    REPO_NAME=$(gh repo view --json name -q .name)

    # Trigger workflow using gh workflow run
    # This requires the workflow to have workflow_dispatch trigger
    if gh workflow run "$GA_WORKFLOW_ID" \
        -f pr_number="$PR_NUMBER" \
        -f branch="$CURRENT_BRANCH" \
        2>/dev/null; then
        echo "✅ GitHub Actions workflow triggered"
        echo "   Workflow: $GA_WORKFLOW_ID"
        echo "   Watch progress: gh run watch"
    else
        echo "⚠️  Failed to trigger GitHub Actions workflow"
        echo "   You may need to configure workflow_dispatch in your workflow file"
        echo ""
        echo "   Add this to your .github/workflows/$GA_WORKFLOW_ID:"
        echo "   "
        echo "   on:"
        echo "     workflow_dispatch:"
        echo "       inputs:"
        echo "         pr_number:"
        echo "           description: 'PR number to review'"
        echo "           required: true"
        echo "         branch:"
        echo "           description: 'Branch name'"
        echo "           required: true"
    fi

    # Alternative: Use curl to trigger via webhook (if configured)
    # Uncomment and configure if you have a custom webhook endpoint
    #
    # if [ -n "$GA_WEBHOOK_URL" ]; then
    #     PAYLOAD=$(cat <<EOF
    # {
    #   "pr_number": "$PR_NUMBER",
    #   "branch": "$CURRENT_BRANCH",
    #   "base_branch": "$BASE_BRANCH",
    #   "repository": "$REPO_OWNER/$REPO_NAME"
    # }
    # EOF
    #     )
    #
    #     if curl -X POST \
    #         -H "Content-Type: application/json" \
    #         -d "$PAYLOAD" \
    #         "$GA_WEBHOOK_URL" &>/dev/null; then
    #         echo "✅ Webhook triggered"
    #     else
    #         echo "⚠️  Webhook failed"
    #     fi
    # fi

    echo ""
else
    echo "Step 5/5: GitHub Actions integration disabled"
    echo "   Enable by setting ENABLE_GA_WEBHOOK=true"
    echo ""
fi

echo "==========================================​"
echo ""
echo "✅ Pull request created!"
echo ""
echo "   $PR_URL"
echo ""
echo "Next steps:"
echo "  - View PR: gh pr view $PR_NUMBER --web"
echo "  - Watch checks: gh pr checks $PR_NUMBER --watch"
echo "  - View workflow runs: gh run list --branch $CURRENT_BRANCH"

exit 0
