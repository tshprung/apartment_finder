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


def setup_driver() -> webdriver.Chrome:
    """Setup Chrome driver"""
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    )

    driver = webdriver.Chrome(options=chrome_options)
    return driver


def extract_number(text: str) -> float:
    """Extract first number from text"""
    match = re.search(r'[\d\s]+[,.]?\d*', text.replace(" ", ""))
    if match:
        return float(match.group().replace(",", ".").replace(" ", ""))
    return 0


def fetch_listing_details(driver: webdriver.Chrome, url: str) -> Dict:
    """Fetch detailed info from listing page"""
    import time
    
    try:
        driver.get(url)
        time.sleep(2)
        
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
                    time.sleep(1)
                    print(f"  Accepted cookies")
                    break
                except:
                    continue
        except:
            pass
        
        # Wait a bit more for content to load after cookie acceptance
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
        try:
            title_selectors = ["h1", "h2", "h4", "[data-cy='ad-title']"]
            for selector in title_selectors:
                try:
                    title_elem = driver.find_element(By.CSS_SELECTOR, selector)
                    title = title_elem.text.strip()
                    if title and len(title) > 5:
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
        
        # Extract structured data
        area_match = re.search(r'powierzchnia[:\s]*(\d+[,.]?\d*)\s*m', page_text)
        area = extract_number(area_match.group(1)) if area_match else None
        
        # Also check title for area if not found
        if not area:
            title_area = re.search(r'(\d+[,.]?\d*)\s*m[²2]', details["title"].lower())
            if title_area:
                area = extract_number(title_area.group(1))
        
        rooms_match = re.search(r'liczba pokoi[:\s]*(\d+)', page_text)
        rooms = int(extract_number(rooms_match.group(1))) if rooms_match else None
        
        # Also check for kawalerka/studio (1 room)
        if not rooms and any(word in page_text for word in ["kawalerk", "1 pokój"]):
            rooms = 1
        
        floor_match = re.search(r'(piętro|poziom)[:\s]*([\d/]+|parter)', page_text)
        floor = floor_match.group(2) if floor_match else "N/A"
        
        # Get text from description element specifically (where "winda" appears)
        try:
            desc_elem = driver.find_element(By.CSS_SELECTOR, "div.css-19duwlz, div[data-cy='ad_description']")
            desc_text = desc_elem.text.lower()
            print(f"  Description found, length: {len(desc_text)} chars")
        except:
            desc_text = ""
            print(f"  WARNING: Could not find description element")
        
        # Search in description first (most reliable), then full page
        has_elevator = any(word in desc_text for word in ["winda", "windą", "elevator", "lift"])
        has_balcony = any(word in desc_text for word in ["balkon", "balkonem", "taras", "tarasem", "loggia"])
        
        if not has_elevator:
            # Fallback to full page source
            page_text = driver.page_source.lower()
            has_elevator = any(word in page_text for word in ["winda", "windą", "elevator", "lift"])
        if not has_balcony:
            page_text = driver.page_source.lower()
            has_balcony = any(word in page_text for word in ["balkon", "balkonem", "taras", "tarasem", "loggia"])

        
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


def scrape_olx(driver: webdriver.Chrome) -> List[Dict]:
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
    
    for idx, link in enumerate(listing_links):
        print(f"\n--- Listing {idx + 1}/{len(listing_links)} ---")
        print(f"  {link}")
        
        try:
            listing_id = link.split("/")[-1].replace(".html", "")
            
            details = fetch_listing_details(driver, link)
            if not details:
                continue
            
            area = details["area"]
            rooms = details["rooms"]
            has_elevator = details["has_elevator"]
            has_balcony = details["has_balcony"]
            price = details["price"]
            
            print(f"  Title: {details['title'][:60]}")
            print(f"  Area: {area}, Rooms: {rooms}, Price: {price}, Elevator: {has_elevator}")
            
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

    try:
        listings = scrape_olx(driver)
        print(f"\nTotal listings found (after filters): {len(listings)}")

        new_listings = [l for l in listings if l["id"] not in seen]
        print(f"New listings: {len(new_listings)}")

        if new_listings:
            send_email(new_listings)
            seen.update(l["id"] for l in new_listings)
            save_seen_listings(seen)
        else:
            print("No new listings found")

    finally:
        driver.quit()

    print("Done")


if __name__ == "__main__":
    main()
