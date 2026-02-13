#!/bin/bash
# /overview - Pre-compute comprehensive project context
# Usage: /overview

# ============================================
# CUSTOMIZE THESE FOR YOUR PROJECT
# ============================================
SHOW_COVERAGE=true
SHOW_DEPENDENCIES=true
SHOW_BUILD_ARTIFACTS=true
BUILD_DIR="dist"  # or build, out, target, etc.
# ============================================

echo "📊 Project Status Report"
echo "==========================================​"
echo ""

# Git Status
echo "🔍 Git Status:"
if git rev-parse --git-dir > /dev/null 2>&1; then
    CURRENT_BRANCH=$(git branch --show-current)
    echo "  Branch: $CURRENT_BRANCH"

    # Check if branch tracks remote
    UPSTREAM=$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null)
    if [ -n "$UPSTREAM" ]; then
        echo "  Tracking: $UPSTREAM"

        # Check sync status
        LOCAL=$(git rev-parse @)
        REMOTE=$(git rev-parse @{u})
        BASE=$(git merge-base @ @{u})

        if [ "$LOCAL" = "$REMOTE" ]; then
            echo "  Status: ✅ Up to date"
        elif [ "$LOCAL" = "$BASE" ]; then
            echo "  Status: ⚠️  Behind remote (need to pull)"
        elif [ "$REMOTE" = "$BASE" ]; then
            echo "  Status: ⚠️  Ahead of remote (need to push)"
        else
            echo "  Status: ⚠️  Diverged (need to merge/rebase)"
        fi
    else
        echo "  Tracking: No upstream branch"
    fi

    # Show modified files
    echo ""
    echo "  Modified files:"
    git status --short | head -20

    if [ $(git status --short | wc -l) -gt 20 ]; then
        echo "  ... and $(($(git status --short | wc -l) - 20)) more"
    fi

    # Last commit
    echo ""
    echo "  Last commit:"
    git log -1 --pretty=format:"  %h - %s (%cr)"
    echo ""
else
    echo "  ❌ Not a git repository"
fi

echo ""
echo "==========================================​"

# Dependencies Status
if [ "$SHOW_DEPENDENCIES" = true ]; then
    echo ""
    echo "📦 Dependencies:"

    if [ -f "package.json" ]; then
        if [ -d "node_modules" ]; then
            echo "  ✅ node_modules installed"

            # Check for package-lock changes
            if git diff --name-only | grep -q "package-lock.json\|yarn.lock\|pnpm-lock.yaml"; then
                echo "  ⚠️  Lock file has changes (run npm install)"
            fi
        else
            echo "  ❌ node_modules missing (run npm install)"
        fi
    fi

    if [ -f "requirements.txt" ] || [ -f "pyproject.toml" ]; then
        if [ -d "venv" ] || [ -d ".venv" ]; then
            echo "  ✅ Python venv exists"
        else
            echo "  ⚠️  No venv detected"
        fi
    fi

    if [ -f "go.mod" ]; then
        if [ -d "vendor" ]; then
            echo "  ✅ Go vendor directory present"
        else
            echo "  📝 Using Go modules (no vendor)"
        fi
    fi

    echo ""
    echo "==========================================​"
fi

# Build Artifacts
if [ "$SHOW_BUILD_ARTIFACTS" = true ]; then
    echo ""
    echo "🏗️  Build Artifacts:"

    if [ -d "$BUILD_DIR" ]; then
        BUILD_SIZE=$(du -sh "$BUILD_DIR" 2>/dev/null | cut -f1)
        echo "  ✅ $BUILD_DIR/ exists ($BUILD_SIZE)"

        # Check if build is stale
        if [ -f "package.json" ]; then
            if [ "$BUILD_DIR" -ot "package.json" ] || [ "$BUILD_DIR" -ot "src" ]; then
                echo "  ⚠️  Build may be stale"
            fi
        fi
    else
        echo "  📝 No build artifacts (run build command)"
    fi

    echo ""
    echo "==========================================​"
fi

# Test Coverage
if [ "$SHOW_COVERAGE" = true ]; then
    echo ""
    echo "🧪 Test Coverage:"

    if [ -f "coverage/coverage-summary.json" ]; then
        echo "  ✅ Coverage report available"
        echo "     View at: coverage/index.html"
    elif [ -f "htmlcov/index.html" ]; then
        echo "  ✅ Coverage report available"
        echo "     View at: htmlcov/index.html"
    elif [ -f "coverage.out" ]; then
        echo "  ✅ Coverage report available (coverage.out)"
    else
        echo "  📝 No coverage report (run tests with coverage)"
    fi

    echo ""
    echo "==========================================​"
fi

# Summary
echo ""
echo "✅ Status report complete"
