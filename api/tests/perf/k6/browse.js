// M10 load scenario (test plan: 10 concurrent users browsing the map and searching for 15
// minutes, p95 within the M5 budgets: search under 300 ms, map activity under 150 ms).
// Each virtual user signs in as its own account, load1 to load10 (search is limited per user).
// Run: k6 run -e BASE=https://host -e PASSWORD=... browse.js (accounts load1..load10@example.org).
import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  scenarios: { browse: { executor: "constant-vus", vus: 10, duration: __ENV.DURATION || "15m" } },
  insecureSkipTLSVerify: __ENV.INSECURE === "1",
  noCookiesReset: true, // keep each user's session across iterations (k6 clears it by default)
  thresholds: {
    "http_req_duration{name:search}": ["p(95)<300"],
    "http_req_duration{name:map}": ["p(95)<150"],
    "http_req_failed": ["rate<0.01"],
    checks: ["rate>0.99"],
  },
};

const BASE = __ENV.BASE;
const WORDS = ["", "NIS2", "data protection", "incident", "AI", "cyber", "privacy", "GDPR", "security"];
const VIEWS = ["country", "region"];
const PERIODS = [7, 30, 90];

export default function () {
  // Each user signs in once, staggered; k6's cookie jar then keeps its session.
  if (__ITER === 0) {
    sleep((__VU - 1) * 0.7);
    const res = http.post(`${BASE}/api/v1/auth/login`,
      JSON.stringify({ email: `load${__VU}@example.org`, password: __ENV.PASSWORD }),
      { headers: { "Content-Type": "application/json", Origin: BASE }, tags: { name: "login" } });
    check(res, { "signed in": (r) => r.status === 200 });
  }
  const page = http.get(`${BASE}/`, { tags: { name: "page" } });
  check(page, { "page 200": (r) => r.status === 200 });
  const view = VIEWS[Math.floor(Math.random() * VIEWS.length)];
  const days = PERIODS[Math.floor(Math.random() * PERIODS.length)];
  const map = http.get(`${BASE}/api/v1/map/activity?period_days=${days}&view_by=${view}`,
    { headers: { "X-Regwatch-Passive": "1" }, tags: { name: "map" } });
  check(map, { "map 200": (r) => r.status === 200 });
  sleep(1 + Math.random() * 2);
  const q = WORDS[Math.floor(Math.random() * WORDS.length)];
  const search = http.post(`${BASE}/api/v1/search`,
    JSON.stringify({ q, page: 1, page_size: 25, highlight: Boolean(q) }),
    { headers: { "Content-Type": "application/json", Origin: BASE }, tags: { name: "search" } });
  check(search, { "search 200": (r) => r.status === 200 });
  sleep(2 + Math.random() * 3);
}
