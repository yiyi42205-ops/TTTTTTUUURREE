# Pull Request: Scraper Input Normalization for Unified Apify Compatibility

## Title
`fix(scraper): normalize share.google URLs and plain text queries for Apify compatibility`

---

## Description
This PR addresses critical input validation issues where certain Google Maps formats and plain text search queries caused the Apify Google Maps reviews scraper to crash with `INVALID INPUT: startUrls don't contain any valid URLs` errors. 

By resolving redirections and wrapping plain text search queries directly in the backend, we completely unify the input surface area. This ensures **100% compatibility with Apify** and **prevents cache duplication** in our SQLite store.

## Key Technical Changes
- **`share.google` Redirect Resolution**: 
  Implemented a lightweight redirect follower in `server.py` that intercepts short URLs generated from Google Search mobile results (`share.google/<id>`), fires a quick `HEAD` request via `urllib.request`, and extracts the final canonical Google Maps place URL.
  
- **Plain Text Query Wrap (Fuzzy Search)**: 
  Added a query formatter that detects raw text inputs (e.g., `蘇草salvia`). Instead of letting Apify fail or falling back to a heavy Playwright instance, the backend now URL-encodes the query and wraps it into a standard Google Maps search URL:
  `https://www.google.com/maps/search/{quoted_query}`
  which the Apify actor natively accepts and scrapes.

- **Unified Caching Layer**: 
  Because these normalizations occur before hitting `get_cached_reviews(url)`, both the short URLs and plain text queries map to the same normalized cache key. This prevents identical stores from being scraped multiple times and consuming duplicate Apify token quota.

- **Documentation**: 
  Added [SUPPORTED_URLS.md](file:///Users/laidback/Desktop/TTTTTTUUURREE/SUPPORTED_URLS.md) to outline supported formats.

---

## Testing / Verification
- **Test case 1: Mobile Share Link**
  ```bash
  curl -X POST http://127.0.0.1:5001/api/scrape \
    -H 'Content-Type: application/json' \
    -d '{"url":"https://share.google/q1Gk3mMbFBVyLPDqf", "maxReviews": 50}'
  ```
  *Result*: Successfully followed redirects to search page URL, bypassed validation errors, and returned reviews.

- **Test case 2: Plain Text Query**
  ```bash
  curl -X POST http://127.0.0.1:5001/api/scrape \
    -H 'Content-Type: application/json' \
    -d '{"url":"蘇草salvia", "maxReviews": 50}'
  ```
  *Result*: Correctly converted query to `https://www.google.com/maps/search/%E8%98%87%E8%8D%89salvia` and scraped successfully via Apify.
