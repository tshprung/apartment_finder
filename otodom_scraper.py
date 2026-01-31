#!/usr/bin/env python3
"""
Otodom Real Estate Scraper
Searches for apartments in Wroclaw matching specific criteria
"""

import json
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, List, Set
from urllib.parse import urlencode

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager


# Search criteria
SEARCH_PARAMS = {
    "locations": "wroclaw",
    "pricePerMeterMax": 12000,
    "areaMin": 35,
    "areaMax": 55,
    "roomsNumber": "[TWO,THREE]",
    "extras": "[BALCONY,ELEVATOR]",
    "limit": 72,
}

# File to store seen listing IDs
SEEN_FILE = Path("seen_listings.json")

# Email config (from environment variables)
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
    """Setup Chrome driver with options to avoid detection"""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


def get_wroclaw_center_coords() -> tuple:
    """Wroclaw center coordinates (Rynek)"""
    return 51.1079, 17.0385


def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in km using Haversine formula"""
    from math import radians, sin, cos, sqrt, atan2

    R = 6371  # Earth radius in km

    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


def scrape_listings(driver: webdriver.Chrome) -> List[Dict]:
    """Scrape listings from Otodom
    
    Note: Floor filtering (not ground/top) cannot be done in URL params,
    must be checked manually in email or needs detail page scraping.
    """
    base_url = "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/dolnoslaskie/wroclaw/wroclaw/wroclaw"
    params = urlencode(SEARCH_PARAMS, safe="[]")
    url = f"{base_url}?{params}"

    print(f"Fetching: {url}")
    driver.get(url)

    # Wait for listings to load
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[data-cy='listing-item']"))
        )
    except Exception as e:
        print(f"Error waiting for listings: {e}")
        return []

    listings = []
    center_lat, center_lon = get_wroclaw_center_coords()

    # Find all listing cards
    cards = driver.find_elements(By.CSS_SELECTOR, "[data-cy='listing-item']")
    print(f"Found {len(cards)} listings")

    for card in cards:
        try:
            # Extract listing ID
            listing_id = card.get_attribute("id")
            if not listing_id:
                continue

            # Extract link
            link_elem = card.find_element(By.CSS_SELECTOR, "a[href*='/pl/oferta/']")
            link = link_elem.get_attribute("href")

            # Extract title/address
            title_elem = card.find_element(By.CSS_SELECTOR, "[data-cy='listing-item-title']")
            title = title_elem.text.strip()

            # Extract price
            price_elem = card.find_element(By.CSS_SELECTOR, "[data-cy='listing-item-price']")
            price_text = price_elem.text.strip()

            # Extract details (area, rooms, floor)
            details = {}
            detail_elems = card.find_elements(By.CSS_SELECTOR, "[data-cy='listing-item-details'] dd")
            for elem in detail_elems:
                text = elem.text.strip()
                if "m²" in text:
                    details["area"] = text
                elif "piętro" in text.lower() or "parter" in text.lower():
                    details["floor"] = text
                elif "pokoje" in text.lower() or "pokój" in text.lower():
                    details["rooms"] = text

            # Try to get coordinates for distance calculation
            # This might not be available in listing cards, skip distance check for now
            distance = None

            listing = {
                "id": listing_id,
                "title": title,
                "price": price_text,
                "area": details.get("area", "N/A"),
                "rooms": details.get("rooms", "N/A"),
                "floor": details.get("floor", "N/A"),
                "link": link,
                "distance_km": distance,
            }

            # Calculate price per m² if possible
            try:
                price_val = int("".join(filter(str.isdigit, price_text)))
                area_val = float(details.get("area", "0").replace("m²", "").replace(",", ".").strip())
                if area_val > 0:
                    listing["price_per_m2"] = f"{price_val / area_val:.0f} zł/m²"
                else:
                    listing["price_per_m2"] = "N/A"
            except (ValueError, KeyError):
                listing["price_per_m2"] = "N/A"

            listings.append(listing)

        except Exception as e:
            print(f"Error parsing listing: {e}")
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
    msg["Subject"] = f"Otodom: {len(new_listings)} new apartments in Wrocław"
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
            <div class="detail">Area: {listing['area']} | Rooms: {listing['rooms']} | Floor: {listing['floor']}</div>
            <div class="detail">Price/m²: {listing['price_per_m2']}</div>
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
    print(f"Starting Otodom scraper at {datetime.now()}")

    # Load seen listings
    seen = load_seen_listings()
    print(f"Previously seen listings: {len(seen)}")

    # Setup driver
    driver = setup_driver()

    try:
        # Scrape listings
        listings = scrape_listings(driver)
        print(f"Total listings found: {len(listings)}")

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
