#!/bin/bash
# /deps - Check for outdated packages and security issues
# Usage: /deps

# ============================================
# CUSTOMIZE THESE FOR YOUR PROJECT
# ============================================
CHECK_OUTDATED=true
CHECK_SECURITY=true
SHOW_DETAILS=true
# ============================================

echo "📦 Dependency Health Check"
echo ""

HAS_ISSUES=false

# Node.js / npm projects
if [ -f "package.json" ]; then
    echo "🔍 Checking npm dependencies..."
    echo ""

    # Check for outdated packages
    if [ "$CHECK_OUTDATED" = true ]; then
        echo "Step 1/2: Checking for outdated packages..."

        OUTDATED=$(npm outdated --json 2>/dev/null)

        if [ -n "$OUTDATED" ] && [ "$OUTDATED" != "{}" ]; then
            echo "⚠️  Outdated packages found:"
            echo ""

            if [ "$SHOW_DETAILS" = true ]; then
                npm outdated
            else
                echo "$OUTDATED" | grep -oP '".*?"' | head -5
            fi

            HAS_ISSUES=true
            echo ""
        else
            echo "✅ All packages up to date"
            echo ""
        fi
    fi

    # Security audit
    if [ "$CHECK_SECURITY" = true ]; then
        echo "Step 2/2: Running security audit..."

        # Run npm audit
        AUDIT_OUTPUT=$(npm audit --json 2>/dev/null)
        VULNERABILITIES=$(echo "$AUDIT_OUTPUT" | grep -oP '(?<="total":)\d+' | head -1)

        if [ -n "$VULNERABILITIES" ] && [ "$VULNERABILITIES" -gt 0 ]; then
            echo "⚠️  Security vulnerabilities found: $VULNERABILITIES"
            echo ""

            if [ "$SHOW_DETAILS" = true ]; then
                npm audit
                echo ""
                echo "💡 Fix with: npm audit fix"
            fi

            HAS_ISSUES=true
            echo ""
        else
            echo "✅ No security vulnerabilities"
            echo ""
        fi
    fi

# Python projects
elif [ -f "requirements.txt" ] || [ -f "pyproject.toml" ]; then
    echo "🔍 Checking Python dependencies..."
    echo ""

    # Check if pip-audit is available
    if command -v pip-audit &> /dev/null; then
        echo "Step 1/2: Running security audit..."

        if pip-audit; then
            echo "✅ No security vulnerabilities"
        else
            echo "⚠️  Security issues found"
            HAS_ISSUES=true
        fi
        echo ""
    else
        echo "⚠️  pip-audit not installed"
        echo "   Install with: pip install pip-audit"
        echo ""
    fi

    # Check for outdated packages
    if [ "$CHECK_OUTDATED" = true ]; then
        echo "Step 2/2: Checking for outdated packages..."

        OUTDATED=$(pip list --outdated 2>/dev/null)

        if [ -n "$OUTDATED" ]; then
            echo "⚠️  Outdated packages:"
            echo ""
            echo "$OUTDATED"
            HAS_ISSUES=true
        else
            echo "✅ All packages up to date"
        fi
        echo ""
    fi

# Go projects
elif [ -f "go.mod" ]; then
    echo "🔍 Checking Go dependencies..."
    echo ""

    echo "Step 1/2: Checking for outdated modules..."

    OUTDATED=$(go list -u -m all 2>/dev/null | grep '\[')

    if [ -n "$OUTDATED" ]; then
        echo "⚠️  Outdated modules:"
        echo ""
        echo "$OUTDATED"
        echo ""
        echo "💡 Update with: go get -u ./... && go mod tidy"
        HAS_ISSUES=true
    else
        echo "✅ All modules up to date"
    fi
    echo ""

    # Check vulnerabilities with govulncheck if available
    if command -v govulncheck &> /dev/null; then
        echo "Step 2/2: Running vulnerability check..."

        if govulncheck ./...; then
            echo "✅ No vulnerabilities found"
        else
            echo "⚠️  Vulnerabilities detected"
            HAS_ISSUES=true
        fi
    else
        echo "Step 2/2: Skipping vulnerability check"
        echo "   Install govulncheck: go install golang.org/x/vuln/cmd/govulncheck@latest"
    fi
    echo ""

# Rust projects
elif [ -f "Cargo.toml" ]; then
    echo "🔍 Checking Rust dependencies..."
    echo ""

    echo "Step 1/2: Checking for outdated crates..."

    if command -v cargo-outdated &> /dev/null; then
        if cargo outdated; then
            echo "✅ Dependency check complete"
        fi
    else
        echo "⚠️  cargo-outdated not installed"
        echo "   Install with: cargo install cargo-outdated"
    fi
    echo ""

    # Security audit
    if command -v cargo-audit &> /dev/null; then
        echo "Step 2/2: Running security audit..."

        if cargo audit; then
            echo "✅ No vulnerabilities found"
        else
            echo "⚠️  Vulnerabilities detected"
            HAS_ISSUES=true
        fi
    else
        echo "Step 2/2: Skipping security audit"
        echo "   Install cargo-audit: cargo install cargo-audit"
    fi
    echo ""

else
    echo "❌ No supported dependency file found"
    echo "   Supported: package.json, requirements.txt, pyproject.toml, go.mod, Cargo.toml"
    exit 1
fi

# Summary
echo "==========================================​"
echo ""

if [ "$HAS_ISSUES" = true ]; then
    echo "⚠️  Action required: Review and update dependencies"
    exit 1
else
    echo "✅ All dependency checks passed"
    exit 0
fi
