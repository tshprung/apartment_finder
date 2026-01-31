#!/usr/bin/env python3
"""
OLX Real Estate Scraper
Searches for apartments in Wroclaw matching specific criteria
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
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


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
        time.sleep(2)  # Wait for page load
        
        page_text = driver.page_source.lower()
        
        details = {
            "area": None,
            "rooms": None,
            "floor": None,
            "has_elevator": False,
            "has_balcony": False,
        }
        
        # Extract area - look for "Powierzchnia: X m²"
        area_match = re.search(r'powierzchnia[:\s]*(\d+[,.]?\d*)\s*m', page_text)
        if area_match:
            details["area"] = extract_number(area_match.group(1))
        
        # Extract rooms - look for "Liczba pokoi: X"
        rooms_match = re.search(r'liczba pokoi[:\s]*(\d+)', page_text)
        if rooms_match:
            details["rooms"] = int(extract_number(rooms_match.group(1)))
        
        # Extract floor - look for "Piętro: X" or "Poziom: X"
        floor_match = re.search(r'(piętro|poziom)[:\s]*(\d+|parter)', page_text)
        if floor_match:
            details["floor"] = floor_match.group(2)
        
        # Check for elevator
        details["has_elevator"] = any(word in page_text for word in ["winda", "elevator", "lift"])
        
        # Check for balcony
        details["has_balcony"] = any(word in page_text for word in ["balkon", "taras", "loggia"])
        
        return details
        
    except Exception as e:
        print(f"    Error fetching details: {e}")
        return None


def scrape_olx(driver: webdriver.Chrome) -> List[Dict]:
    """Scrape OLX listings"""
    import time
    
    # Base URL - all apartments in Wrocław for sale
    url = "https://www.olx.pl/nieruchomosci/mieszkania/sprzedaz/wroclaw/"
    
    print(f"Fetching: {url}")
    driver.get(url)
    time.sleep(3)
    
    listings = []
    
    # Find all listing cards
    try:
        cards = driver.find_elements(By.CSS_SELECTOR, "[data-cy='l-card']")
        print(f"Found {len(cards)} listing cards")
        
        if not cards:
            print("No cards found, trying alternative selector...")
            cards = driver.find_elements(By.CSS_SELECTOR, "div[data-cy='l-card']")
            print(f"Found {len(cards)} with alternative selector")
            
    except Exception as e:
        print(f"Error finding cards: {e}")
        return []
    
    print(f"Starting to iterate through {len(cards)} cards...")
    
    for idx, card in enumerate(cards):
        print(f"\n--- Processing card {idx + 1}/{len(cards)} ---")
        try:
            # Extract listing ID from link
            try:
                link_elem = card.find_element(By.CSS_SELECTOR, "a")
                link = link_elem.get_attribute("href")
            except Exception as e:
                print(f"  No link found - {e}")
                continue
            
            # Skip promoted/external links - but accept both olx.pl and otodom.pl
            if not link or not any(domain in link for domain in ["olx.pl", "otodom.pl"]):
                print(f"  Skipping external link: {link}")
                continue
                
            # Extract ID from URL
            listing_id = link.split("/")[-1].replace(".html", "")
            
            # Extract title - try multiple selectors
            title = None
            title_selectors = ["h6", "h4", "[data-cy='ad-title']", "a h6", "a h4"]
            for selector in title_selectors:
                try:
                    title_elem = card.find_element(By.CSS_SELECTOR, selector)
                    title = title_elem.text.strip()
                    if title:
                        break
                except:
                    continue
            
            if not title:
                print(f"  No title found with any selector")
                continue
            
            print(f"  Title: {title[:60]}")
            
            # Extract price
            try:
                price_elem = card.find_element(By.CSS_SELECTOR, "p[data-testid='ad-price']")
                price_text = price_elem.text.strip()
                price = extract_number(price_text)
                print(f"  Price text: '{price_text}' -> {price}")
            except Exception as e:
                print(f"  No price found - {e}")
                continue
            
            # Extract location and date from bottom section
            try:
                bottom_elem = card.find_element(By.CSS_SELECTOR, "p[data-testid='location-date']")
                location_date = bottom_elem.text.strip()
                parts = location_date.split(" - ")
                location = parts[0] if parts else "Wrocław"
            except:
                location = "Wrocław"
            
            # Try to get area and rooms from card content first
            try:
                # Get all text from card
                card_text = card.text.lower()
                
                # Try to find structured data in card
                rooms = None
                rooms_structured = re.search(r'liczba pokoi[:\s]*(\d+)', card_text)
                if rooms_structured:
                    rooms = int(extract_number(rooms_structured.group(1)))
                else:
                    # Fallback: look for "X pokoi" in general text
                    rooms_patterns = [
                        r'(\d+)[-\s]*poko[ij]',
                    ]
                    for pattern in rooms_patterns:
                        rooms_match = re.search(pattern, card_text)
                        if rooms_match:
                            rooms = int(extract_number(rooms_match.group(1)))
                            break
                
                # Try to find area in card
                area = None
                area_structured = re.search(r'powierzchnia[:\s]*(\d+[,.]?\d*)\s*m', card_text)
                if area_structured:
                    area = extract_number(area_structured.group(1))
                else:
                    # Fallback: look for "X m²" anywhere
                    area_match = re.search(r'(\d+[,.]?\d*)\s*m[²2]', card_text)
                    if area_match:
                        area = extract_number(area_match.group(1))
                
                # Check elevator in card text
                has_elevator = any(word in card_text for word in ["winda", "elevator", "lift"])
                
                # Check balcony in card text
                has_balcony = any(word in card_text for word in ["balkon", "taras", "balcony", "loggia"])
                
            except Exception as e:
                print(f"  Error parsing card text: {e}")
                area = None
                rooms = None
                has_elevator = False
                has_balcony = False
            
            # If critical data is missing from card, fetch detail page
            if area is None or rooms is None or not has_elevator:
                print(f"  Missing data in card, fetching detail page...")
                details = fetch_listing_details(driver, link)
                if details:
                    if area is None:
                        area = details["area"]
                    if rooms is None:
                        rooms = details["rooms"]
                    if not has_elevator:
                        has_elevator = details["has_elevator"]
                    if not has_balcony:
                        has_balcony = details["has_balcony"]
                    
                    print(f"  Detail page data: Area={area}, Rooms={rooms}, Elevator={has_elevator}, Balcony={has_balcony}")
            
            # Debug: print what we extracted
            print(f"  Checking: {title[:50]}...")
            print(f"    Link: {link}")
            print(f"    Area: {area}, Rooms: {rooms}, Price: {price}")
            print(f"    Elevator: {has_elevator}, Balcony: {has_balcony}")
            
            # Apply filters - be lenient if data is missing
            
            # MUST have elevator mentioned
            if not has_elevator:
                print(f"    REJECTED: no elevator mentioned")
                continue
            
            if area:
                if area < MIN_AREA or area > MAX_AREA:
                    print(f"    REJECTED: area {area} not in {MIN_AREA}-{MAX_AREA}")
                    continue
            else:
                print(f"    WARNING: No area found, including anyway")
                
            if rooms:
                if rooms < MIN_ROOMS or rooms > MAX_ROOMS:
                    print(f"    REJECTED: rooms {rooms} not in {MIN_ROOMS}-{MAX_ROOMS}")
                    continue
            else:
                print(f"    WARNING: No rooms found, including anyway")
            
            # Calculate price per m²
            price_per_m2 = None
            if area and area > 0 and price > 0:
                price_per_m2 = price / area
                if price_per_m2 > MAX_PRICE_PER_M2:
                    print(f"    REJECTED: price/m² {price_per_m2:.0f} > {MAX_PRICE_PER_M2}")
                    continue
            
            print(f"    ACCEPTED!")

            
            listing = {
                "id": listing_id,
                "title": title,
                "price": f"{price:,.0f} zł" if price else "N/A",
                "area": f"{area} m²" if area else "N/A",
                "rooms": rooms if rooms else "N/A",
                "price_per_m2": f"{price_per_m2:,.0f} zł/m²" if price_per_m2 else "N/A",
                "location": location,
                "has_elevator": "✓" if has_elevator else "?",
                "has_balcony": "✓" if has_balcony else "?",
                "link": link,
            }
            
            listings.append(listing)
            
        except Exception as e:
            print(f"Error parsing card: {e}")
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

    # Create email
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"OLX: {len(new_listings)} new apartments in Wrocław"
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO

    # HTML body
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
            </div>
            <div class="detail">📍 {listing['location']}</div>
            <div class="detail"><a href="{listing['link']}">View listing →</a></div>
        </div>
        """

    html_body += """
    </body>
    </html>
    """

    msg.attach(MIMEText(html_body, "html"))

    # Send email
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

    # Load seen listings
    seen = load_seen_listings()
    print(f"Previously seen listings: {len(seen)}")

    # Setup driver
    driver = setup_driver()

    try:
        # Scrape listings
        listings = scrape_olx(driver)
        print(f"Total listings found (after filters): {len(listings)}")

        # Filter new listings
        new_listings = [l for l in listings if l["id"] not in seen]
        print(f"New listings: {len(new_listings)}")

        if new_listings:
            # Send email
            send_email(new_listings)

            # Update seen listings
            seen.update(l["id"] for l in new_listings)
            save_seen_listings(seen)
        else:
            print("No new listings found")

    finally:
        driver.quit()

    print("Done")


if __name__ == "__main__":
    main()
