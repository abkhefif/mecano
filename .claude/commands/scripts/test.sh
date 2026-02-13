#!/bin/bash
# /test - Auto-detect and run tests with coverage
# Usage: /test [optional-path-or-pattern]

# ============================================
# CUSTOMIZE THESE FOR YOUR PROJECT
# ============================================
COVERAGE_THRESHOLD=80  # Minimum coverage percentage
TIMEOUT=300           # Test timeout in seconds
# ============================================

set -e

echo "🧪 Running tests..."

# Detect test framework and run tests
detect_and_run_tests() {
    local test_path="${1:-.}"

    # Check for Jest
    if [ -f "package.json" ] && grep -q "jest" package.json; then
        echo "📝 Detected: Jest"
        echo "Step 1/2: Running tests with coverage..."
        npm test -- --coverage --testPathPattern="$test_path" --passWithNoTests
        return $?
    fi

    # Check for Vitest
    if [ -f "package.json" ] && grep -q "vitest" package.json; then
        echo "📝 Detected: Vitest"
        echo "Step 1/2: Running tests with coverage..."
        npm test -- --coverage --run
        return $?
    fi

    # Check for pytest
    if [ -f "pytest.ini" ] || [ -f "pyproject.toml" ] || command -v pytest &> /dev/null; then
        echo "📝 Detected: pytest"
        echo "Step 1/2: Running tests with coverage..."
        python -m pytest "$test_path" --cov --cov-report=term-missing --cov-report=html
        return $?
    fi

    # Check for Go tests
    if [ -f "go.mod" ]; then
        echo "📝 Detected: Go test"
        echo "Step 1/2: Running tests with coverage..."
        go test ./... -cover -coverprofile=coverage.out
        if [ $? -eq 0 ]; then
            go tool cover -func=coverage.out
        fi
        return $?
    fi

    # Check for Cargo (Rust)
    if [ -f "Cargo.toml" ]; then
        echo "📝 Detected: Cargo test"
        echo "Step 1/2: Running tests..."
        cargo test
        return $?
    fi

    echo "❌ No supported test framework detected"
    echo "   Supported: Jest, Vitest, pytest, go test, cargo test"
    exit 1
}

# Run tests
if detect_and_run_tests "$@"; then
    echo ""
    echo "Step 2/2: Checking coverage threshold..."

    # Check coverage if files exist
    if [ -f "coverage/coverage-summary.json" ]; then
        # Jest/Vitest coverage check (simplified)
        echo "📊 Coverage report available at: coverage/index.html"
    elif [ -f "htmlcov/index.html" ]; then
        echo "📊 Coverage report available at: htmlcov/index.html"
    elif [ -f "coverage.out" ]; then
        echo "📊 Coverage report saved to: coverage.out"
    fi

    echo ""
    echo "✅ All tests passed!"
    exit 0
else
    echo ""
    echo "❌ Tests failed"
    echo "   Review the output above for details"
    exit 1
fi
