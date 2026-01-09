/**
 * k6 Load Test Script for Performance Benchmarking
 *
 * Usage:
 *   # Install k6: https://k6.io/docs/getting-started/installation/
 *
 *   # Run against local:
 *   k6 run scripts/load-test.js
 *
 *   # Run against specific URL:
 *   k6 run -e BASE_URL=http://localhost:8000 scripts/load-test.js
 *
 *   # Run with more VUs for stress testing:
 *   k6 run --vus 50 --duration 60s scripts/load-test.js
 *
 *   # Compare before/after:
 *   git checkout main
 *   ./scripts/start-dev.sh &
 *   k6 run scripts/load-test.js --out json=results-main.json
 *
 *   git checkout optimizations
 *   ./scripts/start-dev.sh &
 *   k6 run scripts/load-test.js --out json=results-optimized.json
 */

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend } from 'k6/metrics';
import { textSummary } from 'https://jslib.k6.io/k6-summary/0.0.1/index.js';

// Custom metrics
const errorRate = new Rate('errors');
const healthLatency = new Trend('health_latency', true);
const feedbackStatsLatency = new Trend('feedback_stats_latency', true);
const dashboardLatency = new Trend('dashboard_latency', true);
const docsetLatency = new Trend('docset_latency', true);
const staticAssetLatency = new Trend('static_asset_latency', true);

// Test configuration
export const options = {
  stages: [
    { duration: '10s', target: 10 },  // Ramp up to 10 users
    { duration: '30s', target: 10 },  // Stay at 10 users
    { duration: '10s', target: 20 },  // Ramp up to 20 users
    { duration: '30s', target: 20 },  // Stay at 20 users
    { duration: '10s', target: 0 },   // Ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<500'],  // 95% of requests under 500ms
    errors: ['rate<0.1'],               // Error rate under 10%
    health_latency: ['p(95)<100'],      // Health check under 100ms
    feedback_stats_latency: ['p(95)<200'], // Feedback stats under 200ms (was slow with N+1)
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';

export default function () {
  // Health check endpoints (should be fast)
  group('Health Checks', function () {
    const healthRes = http.get(`${BASE_URL}/health`);
    healthLatency.add(healthRes.timings.duration);
    check(healthRes, {
      'health status is 200': (r) => r.status === 200,
      'health has status field': (r) => JSON.parse(r.body).status === 'healthy',
    }) || errorRate.add(1);

    const readyRes = http.get(`${BASE_URL}/readiness`);
    check(readyRes, {
      'readiness status is 200': (r) => r.status === 200,
      'database is connected': (r) => JSON.parse(r.body).database === 'connected',
    }) || errorRate.add(1);
  });

  sleep(0.5);

  // Static assets (should have cache headers)
  group('Static Assets', function () {
    const cssRes = http.get(`${BASE_URL}/static/dashboard.css`);
    staticAssetLatency.add(cssRes.timings.duration);
    check(cssRes, {
      'CSS returns 200': (r) => r.status === 200,
      'CSS has Cache-Control': (r) => r.headers['Cache-Control'] !== undefined,
    }) || errorRate.add(1);
  });

  sleep(0.5);

  // API endpoints (test the N+1 fixes)
  group('API Endpoints', function () {
    // Feedback stats - was loading ALL feedback into memory before fix
    const feedbackRes = http.get(`${BASE_URL}/api/feedback/stats`);
    feedbackStatsLatency.add(feedbackRes.timings.duration);
    check(feedbackRes, {
      'feedback stats returns 200': (r) => r.status === 200,
      'feedback stats under 200ms': (r) => r.timings.duration < 200,
    }) || errorRate.add(1);
  });

  sleep(0.5);

  // Dashboard (main page)
  group('Dashboard', function () {
    const dashRes = http.get(`${BASE_URL}/`);
    dashboardLatency.add(dashRes.timings.duration);
    check(dashRes, {
      'dashboard returns 200': (r) => r.status === 200,
      'dashboard under 1s': (r) => r.timings.duration < 1000,
    }) || errorRate.add(1);
  });

  sleep(0.5);

  // Docset page with pagination
  group('Docset Pages', function () {
    // Test pagination params
    const docsetRes = http.get(`${BASE_URL}/docset/azure-functions?page=1&per_page=25`);
    docsetLatency.add(docsetRes.timings.duration);
    check(docsetRes, {
      'docset returns 200 or 404': (r) => r.status === 200 || r.status === 404,
    });
  });

  sleep(1);
}

// Summary output
export function handleSummary(data) {
  const summary = {
    timestamp: new Date().toISOString(),
    metrics: {
      http_req_duration_p95: data.metrics.http_req_duration?.values['p(95)'],
      http_req_duration_avg: data.metrics.http_req_duration?.values.avg,
      health_latency_p95: data.metrics.health_latency?.values['p(95)'],
      feedback_stats_latency_p95: data.metrics.feedback_stats_latency?.values['p(95)'],
      dashboard_latency_p95: data.metrics.dashboard_latency?.values['p(95)'],
      error_rate: data.metrics.errors?.values.rate,
      requests_total: data.metrics.http_reqs?.values.count,
    },
  };

  console.log('\n=== Performance Summary ===');
  console.log(`Total Requests: ${summary.metrics.requests_total}`);
  console.log(`Overall p95 Latency: ${summary.metrics.http_req_duration_p95?.toFixed(2)}ms`);
  console.log(`Health Check p95: ${summary.metrics.health_latency_p95?.toFixed(2)}ms`);
  console.log(`Feedback Stats p95: ${summary.metrics.feedback_stats_latency_p95?.toFixed(2)}ms`);
  console.log(`Dashboard p95: ${summary.metrics.dashboard_latency_p95?.toFixed(2)}ms`);
  console.log(`Error Rate: ${(summary.metrics.error_rate * 100)?.toFixed(2)}%`);
  console.log('===========================\n');

  return {
    'summary.json': JSON.stringify(summary, null, 2),
    stdout: textSummary(data, { indent: ' ', enableColors: true }),
  };
}
