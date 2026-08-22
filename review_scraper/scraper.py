import time
import re
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import pandas as pd
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
from bs4 import BeautifulSoup
import sys
import builtins
from urllib.parse import unquote

# ---------------------------------------------------------------------------
# Anti-detection constants
# ---------------------------------------------------------------------------
CHROME_ARGS = [
    '--disable-blink-features=AutomationControlled',
    '--new-window',
    # WebGL / GPU – prevent Google Maps from falling back to Lite mode
    '--use-gl=swiftshader',
    '--enable-webgl',
    '--enable-webgl2',
    # Extra stealth flags
    '--disable-features=IsolateOrigins,site-per-process',
    '--disable-site-isolation-trials',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-infobars',
    '--disable-extensions',
    '--disable-popup-blocking',
    '--disable-translate',
    '--disable-background-timer-throttling',
    '--disable-renderer-backgrounding',
    '--disable-backgrounding-occluded-windows',
]

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

STEALTH_INIT_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.chrome = { runtime: {} };
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters);
"""

# Override print to write to stderr by default so that stdout contains only the final JSON data.
# This prevents log messages from interfering with JSON parsing in the middleware.
_print = builtins.print
def print(*args, **kwargs):
    if 'file' not in kwargs:
        kwargs['file'] = sys.stderr
        if 'flush' not in kwargs:
            kwargs['flush'] = True
    _print(*args, **kwargs)

def parse_relative_time(relative_str: str) -> str:
    """
    Parses a Google Maps relative review date (e.g. "3 年前", "2 months ago")
    and returns the absolute date in YYYY-MM-DD format.
    """
    if not relative_str or relative_str == "N/A":
        return "N/A"
    
    # Strip common prefixes and suffixes
    clean_str = (relative_str
                 .replace("上次編輯：", "")
                 .replace("編輯於", "")
                 .replace("(已編輯)", "")
                 .replace("(Edited)", "")
                 .strip())
    
    now = datetime.now()
    
    try:
        # Years (e.g., "3 年前", "3 years ago")
        if re.search(r'(\d+)\s*(?:年|year)', clean_str):
            years = int(re.search(r'(\d+)', clean_str).group(1))
            date_val = now - relativedelta(years=years)
            return date_val.strftime("%Y-%m-%d")
        elif "a year" in clean_str or "an year" in clean_str or clean_str == "1年前":
            date_val = now - relativedelta(years=1)
            return date_val.strftime("%Y-%m-%d")
            
        # Months (e.g., "2 個月前", "2 months ago")
        elif re.search(r'(\d+)\s*(?:個月|month)', clean_str):
            months = int(re.search(r'(\d+)', clean_str).group(1))
            date_val = now - relativedelta(months=months)
            return date_val.strftime("%Y-%m-%d")
        elif "a month" in clean_str or clean_str == "1個月前":
            date_val = now - relativedelta(months=1)
            return date_val.strftime("%Y-%m-%d")
            
        # Weeks (e.g., "3 週前", "3 weeks ago", "a week ago")
        elif re.search(r'(\d+)\s*(?:週|星期|week)', clean_str):
            weeks = int(re.search(r'(\d+)', clean_str).group(1))
            date_val = now - timedelta(weeks=weeks)
            return date_val.strftime("%Y-%m-%d")
        elif "a week" in clean_str or clean_str == "1週前" or clean_str == "1星期前":
            date_val = now - timedelta(weeks=1)
            return date_val.strftime("%Y-%m-%d")
            
        # Days (e.g., "5 天前", "5 days ago", "yesterday")
        elif re.search(r'(\d+)\s*(?:天|day)', clean_str):
            days = int(re.search(r'(\d+)', clean_str).group(1))
            date_val = now - timedelta(days=days)
            return date_val.strftime("%Y-%m-%d")
        elif "a day" in clean_str or "yesterday" in clean_str or "昨天" in clean_str or clean_str == "1天前":
            date_val = now - timedelta(days=1)
            return date_val.strftime("%Y-%m-%d")
            
        # Hours (e.g., "18 小時前", "18 hours ago")
        elif re.search(r'(\d+)\s*(?:小時|hour)', clean_str):
            hours = int(re.search(r'(\d+)', clean_str).group(1))
            date_val = now - timedelta(hours=hours)
            return date_val.strftime("%Y-%m-%d")
        elif "an hour" in clean_str or clean_str == "1小時前":
            date_val = now - timedelta(hours=1)
            return date_val.strftime("%Y-%m-%d")
            
        # Minutes (e.g., "30 分鐘前", "30 minutes ago")
        elif re.search(r'(\d+)\s*(?:分鐘|minute)', clean_str):
            minutes = int(re.search(r'(\d+)', clean_str).group(1))
            date_val = now - timedelta(minutes=minutes)
            return date_val.strftime("%Y-%m-%d")
        elif "a minute" in clean_str or clean_str == "1分鐘前":
            date_val = now - timedelta(minutes=1)
            return date_val.strftime("%Y-%m-%d")
            
        # Just now / Today (e.g., "剛剛", "just now", "today")
        elif "剛剛" in clean_str or "just now" in clean_str or "today" in clean_str or "今天" in clean_str:
            return now.strftime("%Y-%m-%d")
            
    except Exception as e:
        print(f"Error parsing relative date '{relative_str}': {e}")
        
    return relative_str

def _dismiss_review_dialog(page):
    """Dismiss the 'Write a Review' modal dialog that Google Maps sometimes shows
    when navigating via query_place_id URLs. This modal intercepts all pointer
    events on the underlying page."""
    try:
        dialog = page.query_selector('div[role="dialog"].goog-reviews-write-widget-modal-content')
        if not dialog:
            return
        print("[Python Scraper] Found 'Write a Review' modal dialog, dismissing...")
        # Press Escape to close the modal
        page.keyboard.press("Escape")
        page.wait_for_timeout(1000)
        # Verify it's gone
        dialog_after = page.query_selector('div[role="dialog"].goog-reviews-write-widget-modal-content')
        if dialog_after:
            # Try clicking the backdrop
            page.evaluate('''() => {
                const bg = document.querySelector('.goog-reviews-write-widget-modal-bg');
                if (bg) bg.click();
            }''')
            page.wait_for_timeout(1000)
        print("[Python Scraper] Dismissed 'Write a Review' dialog.")
    except Exception as e:
        print(f"[Python Scraper] Failed to dismiss review dialog: {e}")


def _switch_to_newest_sort(page):
    """Click the sort menu and select '最新' (Newest) to get chronological order.
    Google Maps defaults to '最相關' (Most relevant) which buries no-text and
    short reviews, causing systematic bias in scraped data."""
    try:
        # The sort button: aria-label="排序評論" or class "S9kvJb"
        sort_button = page.query_selector('button[aria-label*="排序"], button[aria-label*="Sort"], button.S9kvJb, button.g88MCb')
        if not sort_button:
            print("[Python Scraper] Could not find sort button, using default sort order.")
            return
        sort_button.click()
        print("[Python Scraper] Clicked sort button, waiting for dropdown...")

        # Wait for the dropdown menu to actually appear
        try:
            page.wait_for_selector('[role="menuitemradio"]', timeout=5000)
        except Exception:
            # Dropdown didn't appear — may have a modal overlay or wrong button.
            # Dismiss any remaining dialogs and retry.
            print("[Python Scraper] Dropdown didn't appear. Dismissing dialogs and retrying...")
            _dismiss_review_dialog(page)
            sort_button_retry = page.query_selector('button[aria-label="排序評論"], button[aria-label*="排序"], button[aria-label*="Sort"]')
            if sort_button_retry:
                sort_button_retry.click()
                try:
                    page.wait_for_selector('[role="menuitemradio"]', timeout=5000)
                except Exception:
                    print("[Python Scraper] Dropdown still didn't appear after retry.")
                    return
            else:
                print("[Python Scraper] Could not find sort button for retry.")
                return

        # Click '最新' option in the dropdown menu
        newest_clicked = page.evaluate('''() => {
            const items = Array.from(document.querySelectorAll('[role="menuitemradio"]'));
            for (const item of items) {
                const text = item.textContent.trim();
                if (text === '最新' || text === 'Newest') {
                    item.click();
                    return true;
                }
            }
            // Debug: log what options were found
            const texts = items.map(i => i.textContent.trim());
            console.log('Sort menu items found:', JSON.stringify(texts));
            return false;
        }''')

        if newest_clicked:
            print("[Python Scraper] Switched to '最新' (Newest) sort order.")
            page.wait_for_timeout(2000)  # Wait for reviews to reload
        else:
            # Log available options for debugging
            options = page.evaluate('''() => {
                return Array.from(document.querySelectorAll('[role="menuitemradio"]'))
                    .map(i => i.textContent.trim());
            }''')
            print(f"[Python Scraper] Could not find '最新' option. Available options: {options}")
    except Exception as e:
        print(f"[Python Scraper] Failed to switch sort order: {e}")


def scroll_and_extract_reviews(page, max_reviews: int = 50):
    """
    Scrolls the Google Maps review pane down to sequentially load lazy-loaded elements.
    """
    reviews_data = []
    print("[Python Scraper] Waiting for review elements (.jftiEf) to appear...")
    # Ensure reviews are loaded by waiting or scrolling a bit
    try:
        page.wait_for_selector('.jftiEf', timeout=15000)
        print("[Python Scraper] Found initial review elements.")
    except Exception as e:
        # If not found, try to scroll the main scrollable area a few times to trigger lazy loading
        print(f"[Python Scraper] Initial wait for reviews timeout/error: {e}. Attempting to scroll main pane...")
        page.evaluate('''
            var main_pane = document.querySelector('.kA9KIf.dS8AEf, div[role="main"] .kA9KIf, .m6QErb.DxyBCb');
            if (main_pane) {
                for (let i = 0; i < 5; i++) {
                    setTimeout(() => { main_pane.scrollTop += 3000; }, i * 1000);
                }
            }
        ''')
        time.sleep(6) # wait for the scrolling to finish
        try:
            page.wait_for_selector('.jftiEf', timeout=15000)
            print("[Python Scraper] Found review elements after scrolling main pane.")
        except Exception as e_fallback:
            print(f"[Python Scraper] Could not find any review elements (.jftiEf) even after scrolling: {e_fallback}")
            return reviews_data
    
    # Dismiss any "撰寫評論" (Write a Review) modal that may overlay the page
    _dismiss_review_dialog(page)

    # Switch to "最新" (Newest) sort before scrolling to avoid "最相關" bias
    _switch_to_newest_sort(page)

    last_review_count = 0
    consecutive_same_count = 0
    print("[Python Scraper] Starting review scroll loop...")
    
    while len(reviews_data) < max_reviews:
        # Scroll down by finding the closest scrollable container to the reviews
        page.evaluate('''
            var reviews = document.querySelectorAll('.jftiEf');
            if (reviews.length > 0) {
                var target = reviews[0].parentElement;
                // Go up the tree to find the nearest scrollable container
                while (target && target.tagName !== 'BODY') {
                    if (target.scrollHeight > target.clientHeight) {
                        target.scrollTop = target.scrollHeight;
                        break;
                    }
                    target = target.parentElement;
                }
            }
        ''')
        
        # Wait a bit for the new elements to load
        time.sleep(1.5)
        
        # Click "More" buttons to expand long texts
        try:
            page.evaluate('''
                const buttons = Array.from(document.querySelectorAll('button'));
                for (const btn of buttons) {
                    if (btn.classList.contains('w8nwRe') || 
                        btn.classList.contains('kyuIte') || 
                        btn.textContent.trim() === '全文' || 
                        btn.textContent.trim() === 'More' || 
                        btn.textContent.includes('顯示更多') ||
                        (btn.getAttribute('aria-label') && (
                            btn.getAttribute('aria-label').includes('See more') || 
                            btn.getAttribute('aria-label').includes('全文') ||
                            btn.getAttribute('aria-label').includes('顯示更多')
                        ))
                    ) {
                        btn.click();
                    }
                }
            ''')
            time.sleep(0.5) # Wait a short moment for the content to expand and render
        except Exception as e:
            print(f"Error expanding reviews: {e}")
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        
        # The main wrapper for a single review
        review_elements = soup.find_all("div", class_="jftiEf")
        print(f"[Python Scraper] Currently found {len(review_elements)} review elements on page (Target: {max_reviews}).")
        
        # If no new reviews are loading, we might have hit the end
        if len(review_elements) == last_review_count:
            consecutive_same_count += 1
            print(f"[Python Scraper] Review count didn't increase ({len(review_elements)}). Consecutive attempts: {consecutive_same_count}/3")
            if consecutive_same_count >= 3:
                print("[Python Scraper] Hit the end of reviews or page stopped loading new ones.")
                break
        else:
            consecutive_same_count = 0
            
        last_review_count = len(review_elements)
    
        # Re-parse to avoid duplicates and get structured data
        reviews_data = []
        for el in review_elements[:max_reviews]:
            try:
                # Username
                user_name_el = el.find("div", class_="d4r55")
                user_name = user_name_el.text.strip() if user_name_el else "Unknown User"
                
                # Rating Stars (Based on aria-label "5 stars")
                rating_el = el.find("span", class_="kvMYJc")
                rating = rating_el["aria-label"] if rating_el and "aria-label" in rating_el.attrs else "N/A"
                if rating != "N/A":
                    # Extract just the number
                    rating = rating.split(" ")[0]
                
                # Relative Time
                time_el = el.find("span", class_="rsqaWe")
                review_time = time_el.text.strip() if time_el else "N/A"
                
                # Review Text
                text_el = el.find("span", class_="wiI7pd")
                review_text = text_el.text.strip() if text_el else ""
                
                # Pictures (Background URLs from button elements inside the review)
                images = []
                img_buttons = el.find_all("button", class_="Tya61d")
                for img_btn in img_buttons:
                    style = img_btn.get("style", "")
                    if "background-image" in style:
                        # Extract URL from background-image: url("...")
                        url_part = style.split('url("')[-1].split('")')[0]
                        images.append(url_part)
                
                reviews_data.append({
                    "Username": user_name,
                    "Stars": rating,
                    "Time": parse_relative_time(review_time),
                    "RawTime": review_time,
                    "Text": review_text,
                    "Images": ", ".join(images)
                })
            except Exception as e:
                print(f"Error parsing a review element: {e}")
                continue

    return reviews_data

def safe_rmtree(path: str, max_retries: int = 10, delay: float = 0.5):
    """
    Attempts to delete a directory, retrying if files are locked.
    """
    import shutil
    import time
    import os
    if not os.path.exists(path):
        return
    for i in range(max_retries):
        try:
            shutil.rmtree(path)
            print(f"[Python Scraper] Successfully removed directory: {path}")
            return
        except Exception as e:
            if i == max_retries - 1:
                print(f"[Python Scraper] Warning: Final attempt to delete {path} failed: {e}")
                shutil.rmtree(path, ignore_errors=True)
            else:
                print(f"[Python Scraper] Directory {path} locked or busy, retrying in {delay}s... (Attempt {i+1}/{max_retries})")
                time.sleep(delay)

def cleanup_old_sessions(parent_dir: str, max_age_seconds: int = 300):
    """
    Cleans up any subdirectories in parent_dir that are older than max_age_seconds.
    Also cleans up legacy chrome_auth_data_* directories in the current working directory.
    """
    import os
    import time
    
    # 1. Clean up legacy directories in current working directory
    now = time.time()
    for item in os.listdir("."):
        if os.path.isdir(item) and item.startswith("chrome_auth_data_") and item != "chrome_auth_data":
            try:
                mtime = os.path.getmtime(item)
                if now - mtime > max_age_seconds:
                    print(f"[Python Scraper] Cleaning up legacy auth directory in cwd: {item}")
                    safe_rmtree(item)
            except Exception as e:
                print(f"[Python Scraper] Warning: failed to clean up legacy directory {item}: {e}")
                
    # 2. Clean up session directories in the parent_dir
    if not os.path.exists(parent_dir):
        return
    for item in os.listdir(parent_dir):
        item_path = os.path.join(parent_dir, item)
        if os.path.isdir(item_path) and item.startswith("session_"):
            try:
                mtime = os.path.getmtime(item_path)
                if now - mtime > max_age_seconds:
                    print(f"[Python Scraper] Cleaning up expired session directory: {item_path}")
                    safe_rmtree(item_path)
            except Exception as e:
                print(f"[Python Scraper] Warning: failed to clean up old session {item_path}: {e}")

def extract_place_name_from_url(url: str) -> str:
    """
    Extracts the human-readable place name from a Google Maps URL.
    e.g. https://www.google.com/maps/place/%E5%B0%8F%E9%AB%98%E6%8B%89%E9%BA%B5/... -> '小高拉麵'
         https://www.google.com/maps/search/?api=1&query=Second+Floor+貳樓師大店&... -> 'Second Floor 貳樓師大店'
    Returns the decoded place name, or the original string if it is already a place name (not a URL).
    """
    if not url.startswith("http://") and not url.startswith("https://"):
        return url
    # /maps/place/<name>/...
    match = re.search(r'/maps/place/([^/@]+)', url)
    if match:
        raw = match.group(1)
        decoded = unquote(raw).replace('+', ' ').strip()
        if decoded:
            return decoded
    # /maps/search/?api=1&query=<name>&...
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if 'query' in qs:
        decoded = qs['query'][0].replace('+', ' ').strip()
        if decoded:
            return decoded
    return ""


def _launch_browser_context(p, user_data_dir: str):
    """
    Launches a Playwright Chromium persistent context with anti-detection measures.
    Tries system Chrome first, then falls back to bundled Chromium.
    """
    launch_kwargs = dict(
        user_data_dir=user_data_dir,
        headless=False,
        ignore_default_args=["--enable-automation"],
        args=CHROME_ARGS,
        locale="zh-TW",
        viewport={"width": 1280, "height": 900},
        user_agent=USER_AGENT,
    )

    try:
        print("[Python Scraper] Attempting to launch system Google Chrome (channel='chrome')...")
        context = p.chromium.launch_persistent_context(channel="chrome", **launch_kwargs)
        print("[Python Scraper] System Google Chrome launched successfully.")
    except Exception as e:
        print(f"[Python Scraper] Failed to launch system Google Chrome: {e}")
        print("[Python Scraper] Falling back to default Playwright Chromium browser...")
        try:
            context = p.chromium.launch_persistent_context(**launch_kwargs)
            print("[Python Scraper] Playwright Chromium browser launched successfully.")
        except Exception as fallback_e:
            print(f"[Python Scraper] Fallback launch failed: {fallback_e}")
            print("[Python Scraper] Critical Hint: Make sure you ran 'playwright install' "
                  "or no other chrome process is locking the user data directory.")
            raise fallback_e

    return context


def _check_place_loaded(page) -> bool:
    """
    Returns True if the Google Maps place detail panel has loaded properly
    (i.e. the h1 place name is populated and/or tabs are present).
    """
    try:
        h1_elements = page.locator("h1").all()
        for h1 in h1_elements:
            text = h1.inner_text().strip()
            if text and text not in ("Google 地圖", "Google Maps", "結果", "Results"):
                return True
        # Also check for tabs
        tabs = page.locator("[role='tab']").all()
        if len(tabs) >= 2:
            return True
    except Exception:
        pass
    return False


def _click_reviews_tab(page) -> bool:
    """
    Finds and clicks the Reviews tab on a Google Maps place page.
    Returns True if the Reviews tab was found and selected.
    """
    click_result = page.evaluate('''() => {
        const keywords = ['評論', '评论', 'review', 'クチコミ', '리뷰', 'reseña', 'avis', 'rezension', 'recensioni', 'comentários', 'отзывы'];
        const excludeKeywords = ['撰寫', 'write', 'post', 'add', 'create', '編輯', 'edit'];

        const tabs = Array.from(document.querySelectorAll('[role="tab"]'));

        // 1. Find the Reviews tab by text/aria-label keywords
        let reviewsTab = tabs.find(tab => {
            const text = tab.textContent.trim().toLowerCase();
            const label = (tab.getAttribute('aria-label') || '').toLowerCase();
            const matchesKw = keywords.some(kw => text.includes(kw) || label.includes(kw));
            const matchesExclude = excludeKeywords.some(ex => text.includes(ex) || label.includes(ex));
            return matchesKw && !matchesExclude;
        });

        // 2. Fallback: match by jslog ID 145620 (Google Maps compiled ID for Reviews tab)
        if (!reviewsTab) {
            reviewsTab = tabs.find(tab => {
                const jslog = tab.getAttribute('jslog') || '';
                return jslog.includes('145620');
            });
        }

        if (reviewsTab) {
            const isSelected = reviewsTab.getAttribute('aria-selected') === 'true' ||
                              (reviewsTab.className && reviewsTab.className.includes('selected'));
            if (isSelected) {
                return { success: true, action: "none", message: "Reviews tab is already selected", name: reviewsTab.textContent.trim() };
            } else {
                reviewsTab.click();
                return { success: true, action: "click_tab", message: "Clicked reviews tab", name: reviewsTab.textContent.trim() };
            }
        }

        // 3. Fallback: look for review-count buttons/links (e.g. the star rating area)
        const interactives = Array.from(document.querySelectorAll('button, [role="button"], a'));
        let reviewsBtn = interactives.find(btn => {
            const text = btn.textContent.trim().toLowerCase();
            const label = (btn.getAttribute('aria-label') || '').toLowerCase();
            const matchesKw = keywords.some(kw => text.includes(kw) || label.includes(kw));
            const matchesExclude = excludeKeywords.some(ex => text.includes(ex) || label.includes(ex));
            const isReviewTrigger = text.includes('更多') || text.includes('more') || /\\d+/.test(text) || text === '評論' || text === 'reviews';
            return matchesKw && !matchesExclude && isReviewTrigger;
        });

        if (reviewsBtn) {
            reviewsBtn.click();
            return { success: true, action: "click_button", message: "Clicked reviews button/link", name: reviewsBtn.textContent.trim() };
        }

        return { success: false, message: "Could not find any Reviews tab or button" };
    }''')

    print(f"[Python Scraper] Tab click result: {click_result}")
    success = click_result.get("success", False)
    if success and click_result.get("action") != "none":
        time.sleep(4)  # Wait for the reviews panel to load
    return success


def navigate_to_place_reviews(page, url: str) -> bool:
    """
    Navigates to the Google Maps place page and activates the Reviews tab.

    Strategy:
      Navigate to maps.google.com first, then use the search box to search for the place name or URL.
      This bypasses the bot detection which normally hides the reviews tab.
      For place_id URLs, search the place_id directly in the search box.
    """
    # If URL contains a bare place_id (no query name), visit Maps homepage
    # first (to get cookies/bypass bot detection), then navigate to the place.
    place_id_match = re.search(r'place_id:(ChIJ[\w-]+)', url)
    if place_id_match:
        place_id = place_id_match.group(1)
        print(f"[Python Scraper] place_id URL detected: {place_id}")
        print("[Python Scraper] Visiting Maps homepage first for cookies...")
        page.goto("https://www.google.com/maps?hl=zh-TW", wait_until="domcontentloaded", timeout=30000)
        time.sleep(4)
        # Dismiss consent dialog
        try:
            page.evaluate('''() => {
                const btns = Array.from(document.querySelectorAll('button, form button'));
                const acceptBtn = btns.find(b => b.textContent.includes('全部同意') || b.textContent.includes('Accept all') || b.textContent.includes('同意'));
                if (acceptBtn) acceptBtn.click();
            }''')
            time.sleep(2)
        except Exception:
            pass
        # Now navigate to the place via query_place_id
        target_url = f"https://www.google.com/maps/search/?api=1&query=_&query_place_id={place_id}"
        print(f"[Python Scraper] Navigating to: {target_url}")
        page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(8)
        if _check_place_loaded(page):
            return _click_reviews_tab(page)
        print("[Python Scraper] place_id navigation failed to load place panel.")
        return False
    else:
        place_name = extract_place_name_from_url(url)
        search_query = place_name if place_name else url
        print(f"[Python Scraper] Search query: '{search_query}'")

    print("[Python Scraper] Navigating to Google Maps home page first to bypass bot detection...")
    page.goto("https://www.google.com/maps?hl=zh-TW", wait_until="domcontentloaded", timeout=30000)
    time.sleep(4)

    # Dismiss any consent dialogs if present
    try:
        page.evaluate('''() => {
            const btns = Array.from(document.querySelectorAll('button, form button'));
            const acceptBtn = btns.find(b => b.textContent.includes('全部同意') || b.textContent.includes('Accept all') || b.textContent.includes('同意'));
            if (acceptBtn) acceptBtn.click();
        }''')
        time.sleep(2)
    except Exception:
        pass

    print("[Python Scraper] Searching via search box...")
    try:
        page.fill('input#searchboxinput, input[name="q"]', search_query)
        time.sleep(1)
        page.keyboard.press("Enter")
        time.sleep(8)
    except Exception as e:
        print(f"[Python Scraper] Failed to search via search box: {e}.")
        if url.startswith("http://") or url.startswith("https://"):
            print("[Python Scraper] Falling back to direct URL navigation.")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(6)
        else:
            return False

    # Check if the search landed directly on a place page (single result)
    if _check_place_loaded(page):
        tabs = page.locator("[role='tab']").all()
        if len(tabs) >= 2:
            print("[Python Scraper] ✓ Search landed directly on place page.")
            return _click_reviews_tab(page)

    # Multiple search results – click the first result link
    print("[Python Scraper] Multiple search results found. Clicking first result...")
    result_links = page.locator('a[href*="/maps/place/"]').all()
    if not result_links:
        print("[Python Scraper] No result links found in search results. Trying to click reviews directly if available...")
        return _click_reviews_tab(page)

    # Try to match by place name; otherwise use the first result
    target_link = result_links[0]
    if place_name:
        for link in result_links:
            aria_label = (link.get_attribute("aria-label") or "").strip()
            if place_name.lower() in aria_label.lower():
                target_link = link
                break

    label = target_link.get_attribute("aria-label") or "(unknown)"
    print(f"[Python Scraper] Clicking result: '{label}'")
    target_link.click()
    time.sleep(8)

    if not _check_place_loaded(page):
        print("[Python Scraper] ✗ Place panel still not loaded after clicking search result.")
        return False

    print("[Python Scraper] ✓ Place panel loaded via search result click.")
    return _click_reviews_tab(page)


def scrape_google_maps_reviews(url: str, max_reviews: int = 50) -> pd.DataFrame:
    print(f"[Python Scraper] Starting scraper for URL: {url} (max_reviews={max_reviews})")
    import hashlib
    import os

    parent_dir = "chrome_auth_data"
    cleanup_old_sessions(parent_dir)

    url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()[:8]
    os.makedirs(parent_dir, exist_ok=True)
    user_data_dir = os.path.join(parent_dir, f"session_{url_hash}")
    print(f"[Python Scraper] User data directory set to: {user_data_dir}")

    data = []
    max_attempts = 3

    for attempt in range(1, max_attempts + 1):
        print(f"[Python Scraper] Scrape attempt {attempt} of {max_attempts}...")
        try:
            with sync_playwright() as p:
                context = _launch_browser_context(p, user_data_dir)

                page = context.pages[0] if context.pages else context.new_page()
                Stealth().apply_stealth_sync(page)
                page.add_init_script(STEALTH_INIT_SCRIPT)

                # Navigate to the place page and activate the Reviews tab
                tab_found = navigate_to_place_reviews(page, url)

                if not tab_found:
                    raise RuntimeError("Reviews tab/button not found")

                data = scroll_and_extract_reviews(page, max_reviews)
                context.close()
                print(f"[Python Scraper] Scrape process finished on attempt {attempt}. "
                      f"Extracted {len(data)} review records.")
                break  # Success, exit retry loop
        except Exception as run_e:
            print(f"[Python Scraper] Error during attempt {attempt}: {run_e}")
            if attempt < max_attempts:
                print("[Python Scraper] Retrying in 2 seconds...")
                time.sleep(2)
                continue
            else:
                if "Reviews tab/button not found" in str(run_e):
                    print(f"[Python Scraper] Failed to find reviews tab after {max_attempts} attempts.")
                    break
                raise run_e
        finally:
            if os.path.exists(user_data_dir):
                print(f"[Python Scraper] Cleaning up user data directory: {user_data_dir}")
                safe_rmtree(user_data_dir)

    return pd.DataFrame(data)

if __name__ == "__main__":
    import sys
    import json
    if len(sys.argv) > 1:
        # CLI execution mode
        url = sys.argv[1]
        max_reviews = 50
        if len(sys.argv) > 2:
            try:
                max_reviews = int(sys.argv[2])
            except ValueError:
                pass
        try:
            df = scrape_google_maps_reviews(url, max_reviews=max_reviews)
            if df.empty:
                print(json.dumps([]), file=sys.stdout)
            else:
                # Convert DataFrame to a list of dicts and print as JSON
                records = df.to_dict(orient="records")
                print(json.dumps(records, ensure_ascii=False), file=sys.stdout)
        except Exception as e:
            # Output error inside JSON to let caller handle
            print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stdout)
    else:
        # Default test block
        test_url = "https://www.google.com/maps/place/Googleplex/@37.4220656,-122.0840897,17z/data=!3m1!4b1!4m6!3m5!1s0x808fba02425dad8f:0x6c296c66619367e0!8m2!3d37.4220656!4d-122.0840897!16zL20vMDMweXNi?entry=ttu"
        df = scrape_google_maps_reviews(test_url, max_reviews=10)
        print(df.head(), file=sys.stdout)