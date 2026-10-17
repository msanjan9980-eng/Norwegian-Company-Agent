# Agent Limitations & Source Rights

## Source Policy
- **Official registers:** Brønnøysundregistrene Enhetsregisteret and Regnskapsregisteret APIs. Open data, no authentication.
- **NAV:** `pam-stilling-feed.nav.no` public feed. No authentication.
- **Google News RSS:** Public RSS feeds. No authentication.
- **Company websites:** Crawled only after the exact entity is verified via the registry name/org-number check. `robots.txt` is respected.
- **Brave Search (optional):** Used only for candidate discovery. Never falls back to scraping search results as evidence.

## Known Limitations
- **JavaScript Shells:** Enterprise sites (React/Next.js) may not yield JSON-LD without a headless browser. Our Playwright fallback attempts to render these, but avoids heavy timeouts.
- **NAV Coverage:** The NAV public feed only contains current active postings. Historical jobs are not available via this endpoint.
- **LinkedIn:** LinkedIn does not permit automated scraping. We rely only on registry data and public company sites.

## Outbound URL Policy

Implemented in `src/norway_company_agent/url_safety.py`, applied to every outbound fetch in the pipeline.

- **Scheme restriction:** Only `http://` and `https://` URLs are allowed. All other schemes are rejected before the request is made.
- **SSRF protection:** Hostnames are resolved via `socket.getaddrinfo`; every returned IP is checked against loopback, private, link-local, reserved, and multicast ranges. If any resolved IP is blocked, the request is aborted.
- **Redirect safety:** A custom `HTTPRedirectHandler` caps the redirect chain at 3 hops and re-runs the SSRF check on each redirect target.
- **Bounded fetching:** Each request is capped at 2 MB (`MAX_BYTES`) with a 10-second timeout (`TIMEOUT`).
- **Known limitation:** The resolver returns IPs, then the actual fetch resolves again. A malicious DNS server could return a public IP for the check and a private IP for the fetch (DNS rebinding). Mitigating this requires socket-level IP pinning, which the stdlib-only implementation does not do. This is a residual risk, not a claim of full mitigation.
