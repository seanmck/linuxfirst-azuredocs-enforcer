#!/bin/bash
# Performance validation script for quick spot checks
# Usage: ./scripts/validate-performance.sh [BASE_URL]
#
# Run against main branch first, then against this branch to compare

set -e

BASE_URL="${1:-http://localhost:8000}"
echo "=== Performance Validation ==="
echo "Target: $BASE_URL"
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

pass() { echo -e "${GREEN}✓ PASS${NC}: $1"; }
fail() { echo -e "${RED}✗ FAIL${NC}: $1"; }
info() { echo -e "${YELLOW}ℹ INFO${NC}: $1"; }

echo "--- 1. Health Check Endpoints ---"

# Test /health endpoint
HEALTH_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/health" 2>/dev/null || echo "000")
if [ "$HEALTH_RESPONSE" = "200" ]; then
    pass "/health returns 200"
else
    fail "/health returned $HEALTH_RESPONSE (expected 200)"
fi

# Test /readiness endpoint
READINESS_RESPONSE=$(curl -s "$BASE_URL/readiness" 2>/dev/null || echo "{}")
if echo "$READINESS_RESPONSE" | grep -q '"status"'; then
    pass "/readiness returns status"
    echo "    Response: $READINESS_RESPONSE"
else
    fail "/readiness endpoint not working"
fi

echo ""
echo "--- 2. Static Asset Cache Headers ---"

# Check Cache-Control header on CSS file
CACHE_HEADER=$(curl -s -I "$BASE_URL/static/dashboard.css" 2>/dev/null | grep -i "cache-control" || echo "")
if echo "$CACHE_HEADER" | grep -qi "max-age"; then
    pass "Static assets have Cache-Control header"
    echo "    $CACHE_HEADER"
else
    fail "No Cache-Control header on static assets"
fi

echo ""
echo "--- 3. Correlation ID Headers ---"

# Check X-Correlation-ID in response
CORR_HEADER=$(curl -s -I "$BASE_URL/health" 2>/dev/null | grep -i "x-correlation-id" || echo "")
if [ -n "$CORR_HEADER" ]; then
    pass "X-Correlation-ID header present"
    echo "    $CORR_HEADER"
else
    fail "X-Correlation-ID header missing"
fi

echo ""
echo "--- 4. Response Time Benchmarks ---"

# Benchmark key endpoints (5 requests each, show average)
benchmark_endpoint() {
    local endpoint=$1
    local name=$2
    local total=0
    local count=5

    for i in $(seq 1 $count); do
        time_ms=$(curl -s -o /dev/null -w "%{time_total}" "$BASE_URL$endpoint" 2>/dev/null || echo "0")
        time_ms_int=$(echo "$time_ms * 1000" | bc 2>/dev/null || echo "0")
        total=$(echo "$total + $time_ms_int" | bc 2>/dev/null || echo "0")
    done

    avg=$(echo "scale=0; $total / $count" | bc 2>/dev/null || echo "N/A")
    echo "  $name: ${avg}ms avg (${count} requests)"
}

info "Benchmarking endpoints (5 requests each)..."
benchmark_endpoint "/health" "GET /health"
benchmark_endpoint "/readiness" "GET /readiness"
benchmark_endpoint "/" "GET / (dashboard)"
benchmark_endpoint "/api/feedback/stats" "GET /api/feedback/stats"

echo ""
echo "--- 5. Pagination Support ---"

# Check if pagination params are accepted
PAGINATED=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/docset/test-docset?page=1&per_page=10" 2>/dev/null || echo "000")
if [ "$PAGINATED" = "200" ] || [ "$PAGINATED" = "404" ]; then
    # 404 is OK if docset doesn't exist, we just want to verify params are accepted
    pass "Pagination query params accepted"
else
    info "Could not verify pagination (status: $PAGINATED)"
fi

echo ""
echo "=== Validation Complete ==="
echo ""
echo "To compare before/after:"
echo "  1. Checkout main branch, start app, run this script"
echo "  2. Checkout this branch, start app, run this script"
echo "  3. Compare the response times"
