#!/usr/bin/env python3
"""
OLX Real Estate Scraper - Simplified version
Collects links first, then fetches details
"""

import json
import os
import re
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, List, Set

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By


# Search criteria
MIN_AREA = 35
MAX_AREA = 55
MIN_ROOMS = 2
MAX_ROOMS = 3
MAX_PRICE_PER_M2 = 12000

# File to store seen listing IDs
SEEN_FILE = Path("seen_listings_olx.json")

# Email config
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_TO = "tshprung@gmail.com"


def load_seen_listings() -> Set[str]:
    """Load previously seen listing IDs"""
    if SEEN_FILE.exists():
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen_listings(seen: Set[str]) -> None:
    """Save seen listing IDs"""
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f, indent=2)


def parse_floor(floor_str: str):
    """Parse floor string like '3/8' -> (current=3, total=8).
    'parter' or 'parter/4' -> (0, total). Returns (current, total) or (None, None) if unparseable."""
    if not floor_str or floor_str == "N/A":
        return None, None
    s = str(floor_str).strip().lower()
    # parter/N or N/parter
    match = re.match(r'^(parter|\d+)/(parter|\d+)$', s)
    if match:
        current = 0 if match.group(1) == "parter" else int(match.group(1))
        total = 0 if match.group(2) == "parter" else int(match.group(2))
        return current, total
    # standalone "parter"
    if s == "parter":
        return 0, None
    # Single number with no total
    try:
        return int(s), None
    except (ValueError, TypeError):
        return None, None


def is_floor_valid(floor_str: str) -> bool:
    """Reject parter (0), floor 1, and top floor. Returns True if valid or unknown."""
    current, total = parse_floor(floor_str)
    if current is None:
        return True  # unknown floor, don't reject
    if current <= 1:  # parter (0) or floor 1
        return False
    if total is not None and current >= total:
        return False
    return True


def setup_driver(stealth_mode: bool = False) -> webdriver.Chrome:
    """Setup Chrome driver with optional stealth mode for otodom.pl"""
    import random
    
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    # Randomize viewport size for otodom
    if stealth_mode:
        widths = [1366, 1440, 1536, 1600, 1920]
        heights = [768, 900, 864, 900, 1080]
        idx = random.randint(0, len(widths) - 1)
        chrome_options.add_argument(f"--window-size={widths[idx]},{heights[idx]}")
        # More realistic user agent
        chrome_options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
    else:
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
    
    if stealth_mode:
        # Extra anti-detection for otodom.pl
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(options=chrome_options)
    
    if stealth_mode:
        # Hide webdriver property and add more realistic navigator properties
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['pl-PL', 'pl', 'en-US', 'en']
                });
            """
        })
    
    return driver


def extract_number(text: str) -> float:
    """Extract first number from text"""
    match = re.search(r'[\d\s]+[,.]?\d*', text.replace(" ", ""))
    if match:
        return float(match.group().replace(",", ".").replace(" ", ""))
    return 0


def fetch_listing_details(driver: webdriver.Chrome, url: str, is_otodom: bool = False) -> Dict:
    """Fetch detailed info from listing page"""
    import time
    import random
    
    try:
        driver.get(url)
        
        # Human-like random delay
        if is_otodom:
            time.sleep(random.uniform(3, 5))
        else:
            time.sleep(2)
        
        # Human-like scrolling behavior for otodom
        if is_otodom:
            try:
                # Scroll down gradually
                scroll_height = driver.execute_script("return document.body.scrollHeight")
                current_position = 0
                scroll_increment = random.randint(300, 500)
                
                while current_position < scroll_height / 2:  # Scroll to middle
                    current_position += scroll_increment
                    driver.execute_script(f"window.scrollTo(0, {current_position});")
                    time.sleep(random.uniform(0.3, 0.7))
                
                # Scroll back up a bit
                driver.execute_script(f"window.scrollTo(0, {current_position - 200});")
                time.sleep(random.uniform(0.5, 1.0))
            except:
                pass
        
        # Try to accept cookies if popup appears
        try:
            cookie_buttons = [
                "button[data-cy='accept-consent']",
                "button[id='onetrust-accept-btn-handler']",
                "button.css-1xh1fol",
                "[data-testid='consent-accept']",
            ]
            for selector in cookie_buttons:
                try:
                    cookie_btn = driver.find_element(By.CSS_SELECTOR, selector)
                    cookie_btn.click()
                    time.sleep(random.uniform(1, 2) if is_otodom else 1)
                    print(f"  Accepted cookies")
                    break
                except:
                    continue
        except:
            pass
        
        # Wait for content to load with random delay
        if is_otodom:
            time.sleep(random.uniform(2, 4))
        else:
            time.sleep(2)
        
        page_text = driver.page_source.lower()
        
        # Debug: show snippet of page text for troubleshooting
        if "powierzchnia" in page_text:
            snippet_start = page_text.find("powierzchnia")
            snippet = page_text[snippet_start:snippet_start+100]
            print(f"  Found 'powierzchnia' in text: {snippet}")
        
        # Check if we're stuck on cookie/privacy page
        if "prywatnoś" in page_text and "powierzchnia" not in page_text:
            print(f"  WARNING: Stuck on privacy page, retrying...")
            time.sleep(3)
            driver.get(url)
            time.sleep(3)
            page_text = driver.page_source.lower()
        
        # Extract title
        title = "Unknown"
        title_blacklist = ["powiadomienia", "ogłoszenia", "wyszukaj", "filtry", "otodom", "olx"]
        try:
            title_selectors = ["[data-cy='ad-title']", "h1.sc-bdVTJa", "h1[data-testid='ad-title']", "h1", "h2", "h4"]
            for selector in title_selectors:
                try:
                    title_elem = driver.find_element(By.CSS_SELECTOR, selector)
                    candidate = title_elem.text.strip()
                    if candidate and len(candidate) > 5 and candidate.lower() not in title_blacklist:
                        title = candidate
                        break
                except:
                    continue
        except:
            pass
        
        # Extract price
        price = 0
        try:
            # Try multiple selectors
            price_selectors = [
                "[data-cy='ad-price']",
                ".css-okktvh-Text",
                "h3",
                "[data-testid='ad-price']",
                "strong",
            ]
            for selector in price_selectors:
                try:
                    price_elem = driver.find_element(By.CSS_SELECTOR, selector)
                    price_text = price_elem.text.strip()
                    if "zł" in price_text and "m²" not in price_text:  # Avoid price/m²
                        price = extract_number(price_text)
                        if price > 10000:  # Sanity check - at least 10k PLN
                            print(f"  Found price: {price_text} -> {price}")
                            break
                except:
                    continue
            
            # Fallback: search page source for price pattern
            if price == 0:
                # Look for "XXX XXX zł" pattern not followed by /m²
                price_pattern = re.search(r'(\d+[\s\d]*)\s*zł(?!\s*/\s*m)', page_text)
                if price_pattern:
                    price_str = price_pattern.group(1).replace(" ", "")
                    price = extract_number(price_str)
                    if price > 10000:
                        print(f"  Found price in text: {price}")
        except Exception as e:
            print(f"  Error extracting price: {e}")
        
        # Extract location
        location = "Wrocław"
        try:
            location_elem = driver.find_element(By.CSS_SELECTOR, "[data-cy='ad-location']")
            location = location_elem.text.strip()
        except:
            pass
        
        # Extract structured data (handles both OLX and Otodom formats)
        # Otodom: "powierzchnia","value":"43.43 m²"
        # OLX: powierzchnia: 43 m²
        area_match = re.search(r'powierzchnia[:\s",value]*(\d+[,.]?\d*)\s*m', page_text)
        area = extract_number(area_match.group(1)) if area_match else None
        
        # Also check title for area if not found
        if not area:
            title_area = re.search(r'(\d+[,.]?\d*)\s*m[²2]', title.lower())
            if title_area:
                area = extract_number(title_area.group(1))
        
        # Rooms: handles "liczba pokoi","value":"3 " or "liczba pokoi: 3"
        rooms_match = re.search(r'liczba pokoi[:\s",value]*(\d+)', page_text)
        rooms = int(extract_number(rooms_match.group(1))) if rooms_match else None
        
        # Also check for kawalerka/studio (1 room)
        if not rooms and any(word in page_text for word in ["kawalerk", "1 pokój"]):
            rooms = 1
        
        # Floor extraction - handles multiple formats:
        # OLX: "piętro: 1/3", "parter", "10 piętro"
        # Otodom JSON: "Piętro","value":"1/5"
        floor_match = re.search(r'pi[eę]tro[:\s",value]*([\d/]+|parter)', page_text, re.IGNORECASE)
        if not floor_match:
            # Try without colon: "10 piętro" 
            floor_match = re.search(r'(\d+)\s+pi[eę]tro', page_text, re.IGNORECASE)
        if not floor_match:
            floor_match = re.search(r'poziom[:\s]*([\d/]+|parter)', page_text, re.IGNORECASE)
        floor = floor_match.group(1) if floor_match else "N/A"
        
        # Get text from description element specifically (where "winda" appears)
        try:
            desc_elem = driver.find_element(By.CSS_SELECTOR, "div.css-19duwlz, div[data-cy='ad_description']")
            desc_text = desc_elem.text.lower()
            print(f"  Description found, length: {len(desc_text)} chars")
        except:
            desc_text = ""
            print(f"  WARNING: Could not find description element")
        
        # Get full page source but exclude "Podobne ogłoszenia" section
        page_source = driver.page_source.lower()
        # Remove similar listings section if present
        if "podobne ogłoszenia" in page_source:
            similar_idx = page_source.find("podobne ogłoszenia")
            page_text_clean = page_source[:similar_idx]
        else:
            page_text_clean = page_source
        
        # Search in description first (most reliable), then full page
        # But exclude negative phrases and "winda: nie" JSON pattern
        negative_elevator = any(phrase in desc_text for phrase in ["nie ma wind", "brak wind", "bez wind"])
        
        has_elevator = False
        if not negative_elevator:
            has_elevator = any(word in desc_text for word in ["winda", "windą", "windy", "windami", "elevator", "lift"])
        
        has_balcony = any(word in desc_text for word in ["balkon", "balkonem", "taras", "tarasem", "loggia"])
        
        if not has_elevator and not negative_elevator:
            # Fallback to full page source (excluding similar listings)
            # Check for negative patterns including JSON-LD
            negative_elevator = any(phrase in page_text_clean for phrase in [
                "nie ma wind", "brak wind", "bez wind", 
                '"winda","value":"nie"', 'winda: nie'
            ])
            if not negative_elevator:
                has_elevator = any(word in page_text_clean for word in ["winda", "windą", "windy", "windami", "elevator", "lift"])
        if not has_balcony:
            has_balcony = any(word in page_text_clean for word in ["balkon", "balkonem", "taras", "tarasem", "loggia"])

        
        return {
            "title": title,
            "price": price,
            "location": location,
            "area": area,
            "rooms": rooms,
            "floor": floor,
            "has_elevator": has_elevator,
            "has_balcony": has_balcony,
        }
        
    except Exception as e:
        print(f"  Error fetching details: {e}")
        return None


def scrape_otodom_search(driver: webdriver.Chrome, seen: Set[str]) -> List[Dict]:
    """Scrape otodom search results page directly to avoid bot detection on individual pages"""
    import time
    import random
    
    # Otodom search URL for Wrocław apartments for sale, 2-3 rooms, 35-55m²
    url = "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie,rynek-wtorny/dolnoslaskie/wroclaw/wroclaw/wroclaw?limit=72&ownerTypeSingleSelect=ALL&areaMin=35&areaMax=55&roomsNumber=%5BTWO%2CTHREE%5D&pricePerMeterMax=12000&extras=%5BBALCONY%2CLIFT%5D&by=DEFAULT&direction=DESC&viewType=listing"
    
    print(f"Fetching otodom search: {url}")
    driver.get(url)
    time.sleep(random.uniform(3, 5))
    
    # Accept cookies
    try:
        cookie_btn = driver.find_element(By.CSS_SELECTOR, "button[id='onetrust-accept-btn-handler']")
        cookie_btn.click()
        time.sleep(2)
        print("  Accepted cookies")
    except:
        pass
    
    # Scroll to load more results
    try:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
        time.sleep(2)
    except:
        pass
    
    listings = []
    
    try:
        # Find all listing cards - they're <article> elements
        cards = driver.find_elements(By.CSS_SELECTOR, "article[data-sentry-component='AdvertCard']")
        print(f"Found {len(cards)} otodom search result cards")
        
        for idx, card in enumerate(cards):
            try:
                # Extract link
                link_elem = card.find_element(By.CSS_SELECTOR, "a[data-cy='listing-item-link']")
                link = link_elem.get_attribute("href")
                
                if not link or "otodom.pl" not in link:
                    continue
                
                listing_id = link.split("/")[-1].replace(".html", "")
                
                # Skip already seen (accepted or rejected)
                if listing_id in seen:
                    continue
                
                # Mark as seen immediately (caches both accepted and rejected)
                seen.add(listing_id)
                
                # Extract data from card
                card_text = card.text.lower()
                
                # Debug: Print raw text for first card
                if idx == 0:
                    print(f"\n  === RAW TEXT FROM FIRST CARD ===")
                    print(card.text)
                    print(f"  === END RAW TEXT ===\n")
                
                # Title
                try:
                    title_elem = card.find_element(By.CSS_SELECTOR, "p[data-cy='listing-item-title']")
                    title = title_elem.text.strip()
                except:
                    title = "Unknown"
                
                # Price
                price = 0
                try:
                    price_elem = card.find_element(By.CSS_SELECTOR, "span[data-sentry-element='MainPrice']")
                    price_text = price_elem.text
                    price = extract_number(price_text)
                except:
                    pass
                
                # Area - look for "XX m²" pattern
                area = None
                area_match = re.search(r'(\d+[,.]?\d*)\s*m', card_text)
                if area_match:
                    area = extract_number(area_match.group(1))
                
                # Rooms - look for "X pokoje" or "X pokoi"
                rooms = None
                rooms_match = re.search(r'(\d+)\s*poko', card_text)
                if rooms_match:
                    rooms = int(rooms_match.group(1))
                
                # Floor - look for "piętro: X" or "X/Y" or "parter"
                floor = "N/A"
                floor_match = re.search(r'pi[eę]tro[:\s]*(parter|\d+[/\d]*)', card_text)
                if floor_match:
                    floor = floor_match.group(1)
                else:
                    floor_match = re.search(r'(parter|\d+)/(parter|\d+)', card_text)
                    if floor_match:
                        floor = f"{floor_match.group(1)}/{floor_match.group(2)}"
                
                # Elevator & Balcony - guaranteed by URL extras filter (LIFT+BALCONY)
                has_elevator = True
                has_balcony = True
                
                # Location - extract from Address element
                location = "Wrocław"
                try:
                    addr_elem = card.find_element(By.CSS_SELECTOR, "p[data-sentry-component='Address']")
                    location = addr_elem.text.strip()
                except Exception as addr_e:
                    if idx < 3:
                        print(f"    [DEBUG] Address extraction failed: {addr_e}")
                
                print(f"\n  Card {idx+1}: {title[:50]}")
                print(f"    Area: {area}, Rooms: {rooms}, Floor: {floor}, Price: {price}")
                print(f"    Location: {location}")
                
                # Only filter for floor (everything else filtered server-side by URL)
                if not is_floor_valid(floor):
                    print(f"    REJECTED: floor {floor} (floor 1 or top floor)")
                    continue
                
                print(f"    ACCEPTED!")
                
                # Price/m² calculation for display only
                price_per_m2 = None
                if area and area > 0 and price > 0:
                    price_per_m2 = price / area
                
                listing = {
                    "id": listing_id,
                    "title": title,
                    "price": f"{price:,.0f} zł" if price else "N/A",
                    "area": f"{area} m²" if area else "N/A",
                    "rooms": rooms if rooms else "N/A",
                    "price_per_m2": f"{price_per_m2:,.0f} zł/m²" if price_per_m2 else "N/A",
                    "location": location,
                    "floor": floor,
                    "has_elevator": "✓",
                    "has_balcony": "✓" if has_balcony else "?",
                    "link": link,
                }
                
                listings.append(listing)
                
            except Exception as e:
                print(f"    Error processing card {idx+1}: {e}")
                continue
    
    except Exception as e:
        print(f"Error scraping otodom search: {e}")
    
    return listings


def scrape_olx(driver: webdriver.Chrome, seen: Set[str]) -> List[Dict]:
    """Scrape OLX listings"""
    import time
    
    url = "https://www.olx.pl/nieruchomosci/mieszkania/sprzedaz/wroclaw/"
    
    print(f"Fetching: {url}")
    driver.get(url)
    time.sleep(3)
    
    # Collect all listing links first
    print("Collecting listing links...")
    listing_links = []
    
    try:
        cards = driver.find_elements(By.CSS_SELECTOR, "[data-cy='l-card']")
        print(f"Found {len(cards)} cards")
        
        for card in cards:
            try:
                link_elem = card.find_element(By.CSS_SELECTOR, "a")
                link = link_elem.get_attribute("href")
                
                if link and any(domain in link for domain in ["olx.pl", "otodom.pl"]):
                    listing_links.append(link)
            except:
                continue
                
    except Exception as e:
        print(f"Error collecting links: {e}")
        return []
    
    print(f"Collected {len(listing_links)} links")
    
    # Fetch details for each listing
    listings = []
    stealth_driver = None  # Lazy init for otodom URLs
    
    for idx, link in enumerate(listing_links):
        print(f"\n--- Listing {idx + 1}/{len(listing_links)} ---")
        print(f"  {link}")
        
        try:
            listing_id = link.split("/")[-1].replace(".html", "")
            
            # Skip already seen (accepted or rejected)
            if listing_id in seen:
                print(f"  Skipping (already seen)")
                continue
            
            # Mark as seen immediately
            seen.add(listing_id)
            
            # Use stealth driver for otodom.pl
            if "otodom.pl" in link:
                if stealth_driver is None:
                    print("  Initializing stealth driver for otodom.pl...")
                    stealth_driver = setup_driver(stealth_mode=True)
                details = fetch_listing_details(stealth_driver, link, is_otodom=True)
            else:
                details = fetch_listing_details(driver, link, is_otodom=False)
            
            if not details:
                continue
            
            area = details["area"]
            rooms = details["rooms"]
            has_elevator = details["has_elevator"]
            has_balcony = details["has_balcony"]
            price = details["price"]
            
            print(f"  Title: {details['title'][:60]}")
            print(f"  Area: {area}, Rooms: {rooms}, Floor: {details['floor']}, Price: {price}, Elevator: {has_elevator}")
            
            # Apply filters
            if not has_elevator:
                print(f"  REJECTED: no elevator")
                continue
            
            if area and (area < MIN_AREA or area > MAX_AREA):
                print(f"  REJECTED: area {area} not in {MIN_AREA}-{MAX_AREA}")
                continue
            
            if rooms and (rooms < MIN_ROOMS or rooms > MAX_ROOMS):
                print(f"  REJECTED: rooms {rooms} not in {MIN_ROOMS}-{MAX_ROOMS}")
                continue
            
            if not is_floor_valid(details['floor']):
                print(f"  REJECTED: floor {details['floor']} (floor 1 or top floor)")
                continue
            
            # Calculate price/m²
            price_per_m2 = None
            if area and area > 0 and price > 0:
                price_per_m2 = price / area
                if price_per_m2 > MAX_PRICE_PER_M2:
                    print(f"  REJECTED: price/m² {price_per_m2:.0f} > {MAX_PRICE_PER_M2}")
                    continue
            
            print(f"  ACCEPTED!")
            
            listing = {
                "id": listing_id,
                "title": details["title"],
                "price": f"{price:,.0f} zł" if price else "N/A",
                "area": f"{area} m²" if area else "N/A",
                "rooms": rooms if rooms else "N/A",
                "price_per_m2": f"{price_per_m2:,.0f} zł/m²" if price_per_m2 else "N/A",
                "location": details["location"],
                "floor": details["floor"],
                "has_elevator": "✓",
                "has_balcony": "✓" if has_balcony else "?",
                "link": link,
            }
            
            listings.append(listing)
            
        except Exception as e:
            print(f"  Error processing listing: {e}")
            continue
    
    # Cleanup stealth driver if created
    if stealth_driver:
        stealth_driver.quit()
    
    return listings


def send_email(new_listings: List[Dict]) -> None:
    """Send email with new listings"""
    if not EMAIL_FROM or not EMAIL_PASSWORD:
        print("Email credentials not configured. Skipping email.")
        print(f"\n{len(new_listings)} new listings found:")
        for listing in new_listings:
            print(f"  - {listing['title']}")
            print(f"    {listing['link']}")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"OLX: {len(new_listings)} new apartments in Wrocław"
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO

    html_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; }}
            .listing {{ border: 1px solid #ddd; margin: 10px 0; padding: 15px; border-radius: 5px; }}
            .listing h3 {{ margin: 0 0 10px 0; color: #2c3e50; }}
            .detail {{ color: #555; margin: 5px 0; }}
            .price {{ color: #27ae60; font-weight: bold; font-size: 18px; }}
            .feature {{ display: inline-block; margin-right: 10px; }}
            a {{ color: #3498db; text-decoration: none; }}
        </style>
    </head>
    <body>
        <h2>New Apartments in Wrocław ({len(new_listings)})</h2>
        <p>Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
    """

    for listing in new_listings:
        html_body += f"""
        <div class="listing">
            <h3>{listing['title']}</h3>
            <div class="price">{listing['price']}</div>
            <div class="detail">
                <span class="feature">📐 {listing['area']}</span>
                <span class="feature">🚪 {listing['rooms']} rooms</span>
                <span class="feature">💰 {listing['price_per_m2']}</span>
            </div>
            <div class="detail">
                <span class="feature">🏢 Elevator: {listing['has_elevator']}</span>
                <span class="feature">🌿 Balcony: {listing['has_balcony']}</span>
                <span class="feature">📍 Floor: {listing['floor']}</span>
            </div>
            <div class="detail">📍 {listing['location']}</div>
            <div class="detail"><a href="{listing['link']}">View listing →</a></div>
        </div>
        """

    html_body += "</body></html>"
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.send_message(msg)
        print(f"Email sent successfully to {EMAIL_TO}")
    except Exception as e:
        print(f"Error sending email: {e}")


def main():
    """Main function"""
    print(f"Starting OLX scraper at {datetime.now()}")

    seen = load_seen_listings()
    print(f"Previously seen listings: {len(seen)}")

    driver = setup_driver()
    stealth_driver = None

    try:
        # Scrape OLX
        olx_listings = scrape_olx(driver, seen)
        print(f"\nOLX listings found (after filters): {len(olx_listings)}")
        
        # Scrape otodom search page
        print(f"\n{'='*60}")
        print("Starting otodom search scraping...")
        print(f"{'='*60}")
        stealth_driver = setup_driver(stealth_mode=True)
        otodom_listings = scrape_otodom_search(stealth_driver, seen)
        print(f"\nOtodom listings found (after filters): {len(otodom_listings)}")
        
        # Combine results — all are new (seen check done inside scrape functions)
        all_listings = olx_listings + otodom_listings
        print(f"\nTotal new listings: {len(all_listings)}")

        if all_listings:
            send_email(all_listings)
        else:
            print("No new listings found")
        
        # Always save seen (includes both accepted and rejected)
        save_seen_listings(seen)

    finally:
        driver.quit()
        if stealth_driver:
            stealth_driver.quit()

    print("Done")


if __name__ == "__main__":
    main()
