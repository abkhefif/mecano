#!/bin/bash
# /clean - Reset project to clean state
# Usage: /clean [--force]

# ============================================
# CUSTOMIZE THESE FOR YOUR PROJECT
# ============================================
KILL_DEV_SERVERS=true
CLEAN_DEPENDENCIES=false  # Set to true to remove node_modules, etc.
CLEAN_BUILD_ARTIFACTS=true
CLEAN_CACHE=true
BUILD_DIRS=("dist" "build" "out" ".next" "target")  # Add your build dirs
CACHE_DIRS=("node_modules/.cache" ".cache" "__pycache__" ".pytest_cache")
# ============================================

echo "🧹 Cleaning Project"
echo ""

FORCE_MODE=false
if [ "$1" = "--force" ]; then
    FORCE_MODE=true
    echo "⚠️  FORCE MODE ENABLED"
    echo ""
fi

# Kill dev server processes
if [ "$KILL_DEV_SERVERS" = true ]; then
    echo "Step 1/4: Killing dev server processes..."

    # Common dev server ports
    PORTS=(3000 3001 4200 5000 5173 8000 8080 8888)

    KILLED=false
    for PORT in "${PORTS[@]}"; do
        if lsof -ti:$PORT &>/dev/null; then
            echo "  Killing process on port $PORT..."
            lsof -ti:$PORT | xargs kill -9 2>/dev/null || true
            KILLED=true
        fi
    done

    # Kill common dev server process names
    PROCESS_NAMES=("node" "npm" "vite" "next-server" "react-scripts")

    for PROC in "${PROCESS_NAMES[@]}"; do
        if pgrep -f "$PROC.*dev" &>/dev/null; then
            echo "  Killing $PROC dev processes..."
            pkill -9 -f "$PROC.*dev" 2>/dev/null || true
            KILLED=true
        fi
    done

    if [ "$KILLED" = true ]; then
        echo "✅ Dev servers killed"
    else
        echo "📝 No dev servers running"
    fi
    echo ""
else
    echo "Step 1/4: Skipping dev server cleanup (disabled)"
    echo ""
fi

# Clean dependencies
if [ "$CLEAN_DEPENDENCIES" = true ]; then
    echo "Step 2/4: Cleaning dependencies..."

    if [ "$FORCE_MODE" = false ]; then
        echo "⚠️  This will remove dependency directories"
        echo "   Run with --force to confirm"
        echo ""
    else
        CLEANED=false

        if [ -d "node_modules" ]; then
            echo "  Removing node_modules..."
            rm -rf node_modules
            CLEANED=true
        fi

        if [ -d "venv" ] || [ -d ".venv" ]; then
            echo "  Removing Python venv..."
            rm -rf venv .venv
            CLEANED=true
        fi

        if [ -d "vendor" ]; then
            echo "  Removing vendor..."
            rm -rf vendor
            CLEANED=true
        fi

        if [ "$CLEANED" = true ]; then
            echo "✅ Dependencies cleaned"
        else
            echo "📝 No dependencies to clean"
        fi
        echo ""
    fi
else
    echo "Step 2/4: Skipping dependency cleanup (disabled)"
    echo ""
fi

# Clean build artifacts
if [ "$CLEAN_BUILD_ARTIFACTS" = true ]; then
    echo "Step 3/4: Cleaning build artifacts..."

    CLEANED=false
    for DIR in "${BUILD_DIRS[@]}"; do
        if [ -d "$DIR" ]; then
            echo "  Removing $DIR/..."
            rm -rf "$DIR"
            CLEANED=true
        fi
    done

    if [ "$CLEANED" = true ]; then
        echo "✅ Build artifacts cleaned"
    else
        echo "📝 No build artifacts to clean"
    fi
    echo ""
else
    echo "Step 3/4: Skipping build artifacts (disabled)"
    echo ""
fi

# Clean cache directories
if [ "$CLEAN_CACHE" = true ]; then
    echo "Step 4/4: Cleaning cache..."

    CLEANED=false
    for DIR in "${CACHE_DIRS[@]}"; do
        if [ -d "$DIR" ]; then
            echo "  Removing $DIR/..."
            rm -rf "$DIR"
            CLEANED=true
        fi
    done

    # Clean coverage reports
    if [ -d "coverage" ] || [ -d "htmlcov" ]; then
        echo "  Removing coverage reports..."
        rm -rf coverage htmlcov .coverage coverage.out
        CLEANED=true
    fi

    # Clean log files
    if ls *.log &>/dev/null; then
        echo "  Removing log files..."
        rm -f *.log
        CLEANED=true
    fi

    if [ "$CLEANED" = true ]; then
        echo "✅ Cache cleaned"
    else
        echo "📝 No cache to clean"
    fi
    echo ""
else
    echo "Step 4/4: Skipping cache cleanup (disabled)"
    echo ""
fi

# Summary
echo "==========================================​"
echo ""
echo "✅ Project cleaned!"
echo ""

if [ "$CLEAN_DEPENDENCIES" = true ] && [ "$FORCE_MODE" = true ]; then
    echo "💡 Next steps:"
    echo "   - Reinstall dependencies (npm install, pip install, etc.)"
    echo "   - Rebuild project if needed"
fi
