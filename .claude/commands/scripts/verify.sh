#!/bin/bash
# /verify - Start app and run health checks
# Usage: /verify

# ============================================
# CUSTOMIZE THESE FOR YOUR PROJECT
# ============================================
DEV_COMMAND="npm run dev"  # or "npm start", "cargo run", "go run .", etc.
HEALTH_CHECK_URL="http://localhost:3000"  # Adjust port as needed
HEALTH_CHECK_PATH="/"  # or "/health", "/api/health"
MAX_WAIT_TIME=30  # seconds
CLEANUP_ON_EXIT=true
# ============================================

echo "🔍 Verifying Application"
echo ""

TEMP_LOG=$(mktemp)
SERVER_PID=""

# Cleanup function
cleanup() {
    if [ "$CLEANUP_ON_EXIT" = true ] && [ -n "$SERVER_PID" ]; then
        echo ""
        echo "Cleaning up..."
        kill $SERVER_PID 2>/dev/null
        wait $SERVER_PID 2>/dev/null
        rm -f "$TEMP_LOG"
        echo "✅ Cleanup complete"
    fi
}

trap cleanup EXIT

# Detect and start dev server
echo "Step 1/4: Starting development server..."

# Start server in background
$DEV_COMMAND > "$TEMP_LOG" 2>&1 &
SERVER_PID=$!

echo "  PID: $SERVER_PID"
echo "  Waiting for server to be ready..."
echo ""

# Wait for server to be ready
echo "Step 2/4: Waiting for server (max ${MAX_WAIT_TIME}s)..."

WAITED=0
READY=false

while [ $WAITED -lt $MAX_WAIT_TIME ]; do
    # Check if process is still running
    if ! kill -0 $SERVER_PID 2>/dev/null; then
        echo ""
        echo "❌ Server process died unexpectedly"
        echo ""
        echo "Last 20 lines of output:"
        tail -20 "$TEMP_LOG"
        exit 1
    fi

    # Try health check
    if curl -sf "${HEALTH_CHECK_URL}${HEALTH_CHECK_PATH}" > /dev/null 2>&1; then
        READY=true
        break
    fi

    sleep 1
    ((WAITED++))
    echo -ne "  Waited ${WAITED}s...\r"
done

echo ""

if [ "$READY" = false ]; then
    echo ""
    echo "❌ Server failed to start within ${MAX_WAIT_TIME}s"
    echo ""
    echo "Last 20 lines of output:"
    tail -20 "$TEMP_LOG"
    exit 1
fi

echo "✅ Server is ready!"
echo ""

# Run health checks
echo "Step 3/4: Running health checks..."

# Basic connectivity
if curl -sf "${HEALTH_CHECK_URL}${HEALTH_CHECK_PATH}" > /dev/null; then
    echo "  ✅ HTTP connectivity"
else
    echo "  ❌ HTTP connectivity failed"
    exit 1
fi

# Check response time
RESPONSE_TIME=$(curl -o /dev/null -s -w '%{time_total}' "${HEALTH_CHECK_URL}${HEALTH_CHECK_PATH}")
echo "  ✅ Response time: ${RESPONSE_TIME}s"

# Check status code
STATUS_CODE=$(curl -o /dev/null -s -w '%{http_code}' "${HEALTH_CHECK_URL}${HEALTH_CHECK_PATH}")
if [ "$STATUS_CODE" -eq 200 ]; then
    echo "  ✅ Status code: $STATUS_CODE"
else
    echo "  ⚠️  Status code: $STATUS_CODE (expected 200)"
fi

echo ""

# Summary
echo "Step 4/4: Verification summary..."
echo ""
echo "  Server URL: $HEALTH_CHECK_URL"
echo "  Server PID: $SERVER_PID"
echo "  Health: ✅ PASSING"
echo ""

if [ "$CLEANUP_ON_EXIT" = true ]; then
    echo "✅ Verification complete! (server will be stopped)"
else
    echo "✅ Verification complete! (server still running)"
    echo "   Stop with: kill $SERVER_PID"
fi

exit 0
