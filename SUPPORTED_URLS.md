# Supported Google Maps URL Formats

The TrueRating scraper endpoint (`/api/scrape`) supports parsing and scraping Google Maps review data from the following URL and search formats:

## 1. 📱 Mobile Share Links
These are short URLs generated when users tap the "Share" button on mobile devices.

* **`https://maps.app.goo.gl/*`**
  * *Example:* `https://maps.app.goo.gl/q1Gk3mMb`
  * *Origin:* Google Maps Mobile App
  * *Status:* Natively supported by Apify.
  
* **`https://share.google/*`**
  * *Example:* `https://share.google/q1Gk3mMbFBVyLPDqf`
  * *Origin:* Google Search Mobile Results Page
  * *Status:* **Supported via custom redirection follow.** The backend follows HTTP redirects automatically to fetch and pass the canonical search/place URL to the scraper, preventing cache fragmentation.

---

## 2. 💻 Desktop & Standard URLs
These are standard URLs copied from a web browser address bar.

* **`https://www.google.com/maps/place/*`**
  * *Example:* `https://www.google.com/maps/place/Pa'+%C3%A9l+y+paella/@25.03,121.44`
  * *Status:* Natively supported.
  
* **`https://www.google.com/maps/search/*`**
  * *Example:* `https://www.google.com/maps/search/ramen/@25.03,121.44`
  * *Status:* Natively supported.
  
* **`https://www.google.com/maps?cid=*`**
  * *Example:* `https://www.google.com/maps?cid=127512837192837`
  * *Status:* Natively supported.

---

## 3. 🔍 Plain Text (Fuzzy Search)
If a URL is not provided, the scraper will fall back to search.

* **"Business Name / Search Query"**
  * *Example:* `蘇草salvia`
  * *Status:* The scraper will perform a search on Google Maps for the query and retrieve reviews for the best matching location.
