# Otodom Real Estate Scraper

Automated scraper for Wrocław apartments on Otodom.pl

## Search Criteria

- **Location**: Wrocław (max 2-3km from center)
- **Price/m²**: ≤12,000 PLN
- **Area**: 35-55 m²
- **Rooms**: 2-3
- **Features**: Elevator, Balcony
- **Floor**: Not ground, not top ⚠️ **Manual check required** (Otodom API doesn't support this filter)

## Important Notes

⚠️ **Floor filtering**: Otodom doesn't allow filtering "not ground, not top" in search. You'll need to check the floor info manually when you receive listings. The scraper shows floor info in the email.

## Setup

### 1. Fork/Clone Repository

```bash
git clone <your-repo-url>
cd <repo-name>
```

### 2. Configure Email Notifications

Go to your GitHub repository → Settings → Secrets and variables → Actions

Add two secrets:
- `EMAIL_FROM`: Your Gmail address (e.g., yourname@gmail.com)
- `EMAIL_PASSWORD`: Your Gmail App Password (see below)

**How to get Gmail App Password:**
1. Go to Google Account settings
2. Security → 2-Step Verification (enable if not already)
3. App passwords → Generate new
4. Select "Mail" and "Other (Custom name)"
5. Copy the 16-character password

### 3. Enable GitHub Actions

Go to repository → Actions → Enable workflows

### 4. Test Manually

Go to Actions → Daily Otodom Scraper → Run workflow

## How It Works

1. **Daily Schedule**: Runs at 8 AM Poland time
2. **Scraping**: Fetches listings matching criteria
3. **Tracking**: Stores seen listing IDs in `seen_listings.json`
4. **Email**: Sends HTML email with new listings only
5. **Persistence**: Commits updated seen listings back to repo

## Files

- `otodom_scraper.py` - Main scraper
- `requirements.txt` - Python dependencies
- `.github/workflows/daily_scrape.yml` - Automation config
- `seen_listings.json` - Tracking file (auto-generated)

## Manual Testing Locally

```bash
pip install -r requirements.txt

# Set environment variables
export EMAIL_FROM="your@gmail.com"
export EMAIL_PASSWORD="your-app-password"

python otodom_scraper.py
```

## Customization

Edit `otodom_scraper.py` to modify:
- `SEARCH_PARAMS` - Change search criteria
- `EMAIL_TO` - Change recipient email
- Distance filtering (currently disabled, needs coordinates from detail pages)

## Notes

- Otodom may change their HTML structure, requiring scraper updates
- Free GitHub Actions: 2,000 minutes/month
- Gmail has sending limits: ~500 emails/day
- Floor filtering (not ground/top) needs manual verification in listings
