import os
import re
import json
import smtplib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from email.message import EmailMessage
from urllib.parse import urlparse, urljoin
import requests
import pandas as pd
from playwright.sync_api import sync_playwright
from gtts import gTTS
from bs4 import BeautifulSoup
from moviepy import ImageClip, AudioFileClip, concatenate_videoclips
from PIL import Image, ImageDraw, ImageFont
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# Optional: Google Sheets Integration
try:
    import gspread
    from googleapiclient.discovery import build
    from oauth2client.service_account import ServiceAccountCredentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False

# ==============================================================================
# CONFIGURATION & CREDENTIALS
# ==============================================================================
CONFIG = {
    # Custom LLM / NRP Nautilus Endpoint
    "NRP_ENDPOINT": os.getenv("NRP_ENDPOINT", "https://ellm.nrp-nautilus.io/v1"),
    "NRP_API_KEY": os.getenv("NRP_API_KEY", "your-nrp-api-key"),
    "MODEL_NAME": "qwen3",

    # Intelligence experiment settings
    # FAST = existing one-competitor workflow + compact strategic analysis
    # STANDARD = 3 competitors + deeper deterministic comparisons
    # DEEP = up to 5 competitors + expanded opportunity analysis
    "INTELLIGENCE_LEVEL": os.getenv("INTELLIGENCE_LEVEL", "FAST").upper(),
    "MAX_COMPETITORS": int(os.getenv("MAX_COMPETITORS", "5")),
    "LLM_MAX_TOKENS": int(os.getenv("LLM_MAX_TOKENS", "1600")),
    "CAPTURE_SCREENSHOT": os.getenv("CAPTURE_SCREENSHOT", "true").lower() == "true",
    "INTELLIGENCE_CACHE_FILE": "competitive_intelligence_cache.json",

    # Google Places API
    "GOOGLE_PLACES_KEY": os.getenv("GOOGLE_PLACES_KEY", "your-places-api-key"),

    # Decision-Maker Discovery Keys
    "APOLLO_API_KEY": os.getenv("APOLLO_API_KEY"),
    "HUNTER_API_KEY": os.getenv("HUNTER_API_KEY"),

    # Voice Settings
    "TTS_ENGINE": os.getenv("TTS_ENGINE", "google"),
    "ELEVENLABS_KEY": os.getenv("ELEVENLABS_KEY", "your-elevenlabs-key"),
    "VOICE_ID": "nPczCjzI2devNBz1zQrb",  # Brian (Executive Narrative)

    # Agency Branding & CTA
    "BRAND_PRIMARY": "ELKINS & CO.",
    "BRAND_SUBTITLE": "REVENUE STRATEGIES",
    "AGENCY_WEBSITE": "www.elkinsrevenue.com",
    "AGENCY_PHONE": "917-327-0636",
    "AGENCY_EMAIL": "lorren@elkinsrevenue.com",
    "CUSTOM_CTA": "Let us show you how we can help. Review this deck and schedule a meeting with us.",

    # Email SMTP Settings
    "SMTP_SERVER": "smtp.gmail.com",
    "SMTP_PORT": 465,
    "SENDER_EMAIL": os.getenv("SENDER_EMAIL", "your-email@domain.com"),
    "SENDER_PASSWORD": os.getenv("SENDER_PASSWORD", "your-app-password"),

# Data Persistence
    "GOOGLE_SHEET_NAME": "Prospecting Leads",
    # Paste your sheet ID directly here:
    "GOOGLE_SHEET_ID": os.getenv("GOOGLE_SHEET_ID", "1GhaLCdHN9NGVQaNZGqp4ONHoCsEM9zCVyVapuWwkNFw"),
    "GOOGLE_SHEETS_CREDENTIALS_JSON": r"G:\My Drive\Elkins Revenue Consulting\AI Agent Scripts\service_account.json",
    "FALLBACK_LOCAL_CSV": "prospecting_leads.csv",

    # Output Destination Directory
    "OUTPUT_DIR": Path(r"G:\My Drive\Elkins Revenue Consulting\AI Agent Scripts\ElkinsRev Prospect Videos")
}

try:
    CONFIG["OUTPUT_DIR"].mkdir(parents=True, exist_ok=True)
except Exception:
    CONFIG["OUTPUT_DIR"] = Path(__file__).resolve().parent / "output"
    CONFIG["OUTPUT_DIR"].mkdir(parents=True, exist_ok=True)

# Clean Executive Light Theme
STYLE = {
    "BG": (255, 255, 255),               # Pure White Canvas
    "CARD_BG": (248, 250, 252),          # Soft Gray Surface (#F8FAFC)
    "CARD_BORDER": (226, 232, 240),      # Subtle Divider (#E2E8F0)
    "TEXT_DARK": (15, 23, 42),           # Near Black (#0F172A)
    "TEXT_BODY": (30, 41, 59),           # Slate Body (#1E293B)
    "TEXT_MUTED": (100, 116, 139),       # Subtext Gray (#64748B)
    "BLUE": (37, 99, 235),               # Electric Cobalt (#2563EB)
    "PILL_BG": (239, 246, 255),          # Light Blue Pill Background (#EFF6FF)
    "DIVIDER": (203, 213, 225),          # Divider Line (#CBD5E1)
    "GREEN": (22, 163, 74),              # Accent Green
    "RED": (220, 38, 38)                 # Accent Red
}

# ==============================================================================
# TOKEN & COST TRACKING METRICS
# ==============================================================================
TOKEN_STATS = {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "llm_calls": 0
}

INTELLIGENCE_CACHE = {}
try:
    cache_path = Path(CONFIG["INTELLIGENCE_CACHE_FILE"])
    if cache_path.exists():
        INTELLIGENCE_CACHE = json.loads(cache_path.read_text(encoding="utf-8"))
except Exception:
    INTELLIGENCE_CACHE = {}

def save_intelligence_cache():
    try:
        Path(CONFIG["INTELLIGENCE_CACHE_FILE"]).write_text(
            json.dumps(INTELLIGENCE_CACHE, indent=2, default=str),
            encoding="utf-8"
        )
    except Exception:
        pass

def scrape_site_footprint_cached(website_url: str, cache_namespace="site") -> dict:
    """Reuse previously scraped competitor/site footprints when possible."""
    domain = extract_clean_domain(website_url)
    if not domain:
        return scrape_site_footprint(website_url)

    key = f"{cache_namespace}:{domain}"
    cached = INTELLIGENCE_CACHE.get(key)
    if isinstance(cached, dict) and cached.get("content_snippet") is not None:
        return cached

    result = scrape_site_footprint(website_url)
    # Keep cache limited to useful JSON-safe footprint data.
    try:
        INTELLIGENCE_CACHE[key] = result
        if len(INTELLIGENCE_CACHE) > 500:
            oldest = next(iter(INTELLIGENCE_CACHE))
            INTELLIGENCE_CACHE.pop(oldest, None)
    except Exception:
        pass
    return result

def print_usage_and_cost_summary(leads_processed: int):
    p_tokens = TOKEN_STATS["prompt_tokens"]
    c_tokens = TOKEN_STATS["completion_tokens"]
    total = TOKEN_STATS["total_tokens"]
    calls = TOKEN_STATS["llm_calls"]

    comm_prompt_cost = (p_tokens / 1_000_000) * 0.40
    comm_compl_cost = (c_tokens / 1_000_000) * 1.20
    commercial_equiv = comm_prompt_cost + comm_compl_cost

    print("\n" + "=" * 65)
    print("               RUN METRICS & COMMERCIAL COST SUMMARY")
    print("=" * 65)
    print(f"Total Leads Processed   : {leads_processed}")
    print(f"Total LLM Invocations   : {calls}")
    print("-" * 65)
    print(f"Prompt (Input) Tokens   : {p_tokens:,}")
    print(f"Completion Tokens       : {c_tokens:,}")
    print(f"Total Tokens Used       : {total:,}")
    print("-" * 65)
    print(f"Actual API Cost (NRP)   : $0.0000 (NSF Grant Funded)")
    print(f"Commercial Equivalent   : ${commercial_equiv:.4f}")
    if leads_processed > 0:
        print(f"Avg Cost per Lead       : ${commercial_equiv / leads_processed:.4f}")
    print("=" * 65 + "\n")

# ==============================================================================
# 1. DISCOVERY, ADVANCED SCRAPING & ENRICHMENT
# ==============================================================================
def find_businesses(category: str, location: str, limit: int = 1) -> list:
    """Discovers local targets via Google Places API (New) with expanded field masks."""
    api_key = CONFIG.get("GOOGLE_PLACES_KEY")
    if not api_key or "your-" in api_key:
        print("\n[MOCK MODE] Missing Google Places Key. Returning test mock lead.")
        return [{
            "name": f"Premier {category}",
            "website": "https://example.com",
            "address": location,
            "rating": 4.3,
            "review_count": 48,
            "editorial_summary": "Established regional service provider.",
            "primary_type": category.lower().replace(" ", "_"),
            "types": [category.lower().replace(" ", "_"), "business"],
            "phone": "+1 555-019-2831"
        }]

    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "places.displayName,places.websiteUri,places.formattedAddress,"
            "places.rating,places.userRatingCount,places.editorialSummary,"
            "places.primaryType,places.types,places.internationalPhoneNumber"
        )
    }
    payload = {"textQuery": f"{category} in {location}", "maxResultCount": max(1, min(limit, 20))}
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        data = res.json()
        places = data.get("places", [])
        return [{
            "name": p.get("displayName", {}).get("text", "Unknown"),
            "website": p.get("websiteUri", ""),
            "address": p.get("formattedAddress", ""),
            "rating": p.get("rating", 0.0),
            "review_count": p.get("userRatingCount", 0),
            "editorial_summary": p.get("editorialSummary", {}).get("text", "None Indexed"),
            "primary_type": p.get("primaryType", "general_business"),
            "types": p.get("types", []),
            "phone": p.get("internationalPhoneNumber", "Not Listed")
        } for p in places]
    except Exception as e:
        print(f"[Places API Error]: {e}")
        return []

def find_benchmark_competitor(category: str, location: str, exclude_name: str) -> dict:
    candidates = find_businesses(category, location, limit=5)
    for c in candidates:
        if c["name"].lower() != exclude_name.lower():
            return c
    return {
        "name": f"Top-Rated {category} Rival",
        "website": "https://example.com",
        "rating": 4.9,
        "review_count": 210,
        "address": location,
        "editorial_summary": "Top-tier regional benchmark.",
        "primary_type": category.lower(),
        "types": [],
        "phone": "+1 555-999-0000"
    }

def extract_clean_domain(website_url: str) -> str:
    if not website_url:
        return ""
    parsed = urlparse(website_url)
    domain = parsed.netloc or parsed.path
    if domain.startswith("www."):
        domain = domain[4:]
    return domain.split("/")[0].strip().lower()

def query_apollo_decision_maker(domain: str) -> dict:
    api_key = CONFIG.get("APOLLO_API_KEY")
    if not api_key or not domain:
        return None
    url = "https://api.apollo.io/v1/mixed_people/api_search"
    headers = {"Content-Type": "application/json", "X-Api-Key": api_key}
    payload = {
        "q_organization_domains_list": [domain],
        "person_titles": ["Owner", "Founder", "CEO", "President", "Managing Partner", "General Manager"],
        "page": 1, "per_page": 1
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=8)
        if res.status_code == 200:
            people = res.json().get("people", [])
            if people:
                p = people[0]
                name = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
                return {"name": name or "Business Leader", "title": p.get("title", "Executive"), "email": p.get("email")}
    except Exception:
        pass
    return None

def query_hunter_decision_maker(domain: str) -> dict:
    api_key = CONFIG.get("HUNTER_API_KEY")
    if not api_key or not domain:
        return None
    url = f"https://api.hunter.io/v2/domain-search?domain={domain}&seniority=executive&api_key={api_key}"
    try:
        res = requests.get(url, timeout=8)
        if res.status_code == 200:
            emails = res.json().get("data", {}).get("emails", [])
            if emails:
                e = emails[0]
                name = f"{e.get('first_name', '')} {e.get('last_name', '')}".strip()
                return {"name": name or "Business Leader", "title": e.get("position", "Owner"), "email": e.get("value")}
    except Exception:
        pass
    return None

def find_decision_maker(website_url: str, fallback_scraped_email: str) -> dict:
    domain = extract_clean_domain(website_url)
    apollo = query_apollo_decision_maker(domain)
    if apollo:
        email = apollo.get("email")
        if email and "@" in email and "email_not_unlocked" not in email:
            return {"name": apollo["name"], "title": apollo["title"], "email": email, "source": "Apollo.io"}
        return {"name": apollo["name"], "title": apollo["title"], "email": fallback_scraped_email, "source": "Apollo.io (Name Only)"}

    hunter = query_hunter_decision_maker(domain)
    if hunter:
        email = hunter.get("email")
        if email and "@" in email:
            return {"name": hunter["name"], "title": hunter["title"], "email": email, "source": "Hunter.io"}
        return {"name": hunter["name"], "title": hunter["title"], "email": fallback_scraped_email, "source": "Hunter.io (Name Only)"}

    return {"name": "Leadership", "title": "Owner / Executive", "email": fallback_scraped_email, "source": "Website Scrape"}

def scrape_site_footprint(website_url: str) -> dict:
    """Deep inspection of conversion elements, tech stack, tracking tags, and SEO tags."""
    details = {
        "email": "Not Listed",
        "social_links": [],
        "load_speed_sec": 1.4,
        "content_snippet": "",
        "missing_elements": [],
        "has_lead_form": False,
        "has_click_to_call": False,
        "has_schema": False,
        "has_meta_desc": False,
        "is_mobile_responsive": False,
        "has_booking_embed": False,
        "booking_platform": "None",
        "has_live_chat": False,
        "chat_platform": "None",
        "has_ssl": False,
        "has_privacy_policy": False,
        "cms_framework": "Custom / Static",
        "has_gtm": False,
        "has_ga4": False,
        "has_meta_pixel": False,
        "h1_count": 0,
        "h2_count": 0,
        "heading_issue": "None",
        "total_images": 0,
        "images_missing_alt": 0,
        "logo_img_path": "prospect_logo_temp.png"
    }
    if not website_url or not website_url.startswith("http"):
        details["missing_elements"].append("Inaccessible page")
        return details
    try:
        details["has_ssl"] = urlparse(website_url).scheme.lower() == "https"
        start = time.time()
        resp = requests.get(website_url, timeout=8, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        details["load_speed_sec"] = round(time.time() - start, 2)
        html_raw = resp.text
        html_lower = html_raw.lower()
        soup = BeautifulSoup(html_raw, "html.parser")

        # 1. Emails & Social Links
        emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', html_raw)
        valid_emails = [e for e in emails if not e.endswith(('.png', '.jpg', '.webp', '.svg'))]
        if valid_emails:
            details["email"] = valid_emails[0]

        for link in soup.find_all("a", href=True):
            href = link["href"].lower()
            for platform in ["facebook.com", "instagram.com", "linkedin.com", "youtube.com", "x.com"]:
                if platform in href and href not in details["social_links"]:
                    details["social_links"].append(href)
            if any(term in href for term in ["privacy", "terms", "legal"]):
                details["has_privacy_policy"] = True

        # 2. Conversion Signals & Booking Embeds
        details["has_lead_form"] = bool(soup.find_all("form"))
        details["has_click_to_call"] = bool(soup.find("a", href=re.compile(r"^tel:")))
        
        booking_platforms = {
            "calendly": "Calendly",
            "acuityscheduling": "Acuity",
            "chilipiper": "ChiliPiper",
            "leadconnector": "LeadConnector",
            "mindbody": "Mindbody",
            "setmore": "Setmore"
        }
        for slug, name in booking_platforms.items():
            if slug in html_lower:
                details["has_booking_embed"] = True
                details["booking_platform"] = name
                break

        # 3. Live Chat / SMS Widgets
        chat_platforms = {
            "intercom": "Intercom",
            "drift.com": "Drift",
            "tidio": "Tidio",
            "podium": "Podium",
            "zendesk": "Zendesk Chat",
            "crisp.chat": "Crisp"
        }
        for slug, name in chat_platforms.items():
            if slug in html_lower:
                details["has_live_chat"] = True
                details["chat_platform"] = name
                break

        # 4. Heading Architecture
        h1s = soup.find_all("h1")
        h2s = soup.find_all("h2")
        details["h1_count"] = len(h1s)
        details["h2_count"] = len(h2s)
        if details["h1_count"] == 0:
            details["heading_issue"] = "Missing H1 Tag"
            details["missing_elements"].append("Missing H1 Header")
        elif details["h1_count"] > 1:
            details["heading_issue"] = f"Duplicate H1 Tags ({details['h1_count']})"
        elif details["h2_count"] == 0:
            details["heading_issue"] = "No H2 Subheaders Found"

        # 5. CMS & Framework Detection
        generator = soup.find("meta", attrs={"name": re.compile(r"^generator$", re.I)})
        gen_content = generator.get("content", "").lower() if generator else ""
        if "wordpress" in gen_content or "wp-content" in html_lower:
            details["cms_framework"] = "WordPress"
        elif "webflow" in gen_content or "webflow" in html_lower:
            details["cms_framework"] = "Webflow"
        elif "squarespace" in html_lower:
            details["cms_framework"] = "Squarespace"
        elif "wix" in html_lower:
            details["cms_framework"] = "Wix"
        elif "shopify" in html_lower:
            details["cms_framework"] = "Shopify"

        # 6. Tracking & Analytics Stack
        details["has_gtm"] = "gtm-" in html_lower
        details["has_ga4"] = "g-" in html_lower or "google-analytics.com" in html_lower
        details["has_meta_pixel"] = "fbevents.js" in html_lower or "fbq(" in html_lower

        # 7. Image Accessibility (Alt tags)
        images = soup.find_all("img")
        details["total_images"] = len(images)
        details["images_missing_alt"] = sum(1 for img in images if not img.get("alt", "").strip())
        if details["images_missing_alt"] > 0:
            details["missing_elements"].append(f"{details['images_missing_alt']} Images Missing Alt Attributes")

        # 8. Schema & SEO Meta
        details["has_schema"] = any("schema.org" in t.text.lower() for t in soup.find_all("script", type="application/ld+json"))
        details["has_meta_desc"] = bool(soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)}))
        details["is_mobile_responsive"] = bool(soup.find("meta", attrs={"name": re.compile(r"^viewport$", re.I)}))

        if not details["has_lead_form"]:
            details["missing_elements"].append("No direct lead capture form")
        if not details["has_click_to_call"]:
            details["missing_elements"].append("No tap-to-call link")
        if not details["has_schema"]:
            details["missing_elements"].append("Missing structured schema markup")
        if not details["has_ssl"]:
            details["missing_elements"].append("Non-secure HTTP protocol")

        body_text = ' '.join([p.get_text() for p in soup.find_all(['p', 'h1', 'h2'])])
        details["content_snippet"] = body_text[:1200]
    except Exception:
        details["missing_elements"].append("Website slow or unreachable")
    return details

def capture_site_assets_playwright(website_url: str, shot_path: str = "homepage_temp.png", logo_path: str = "logo_temp.png") -> dict:
    result = {"screenshot_path": None, "logo_path": None}
    if not website_url or not website_url.startswith("http"):
        return result
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.goto(website_url, timeout=22000, wait_until="domcontentloaded")
            page.wait_for_timeout(1800)
            page.screenshot(path=shot_path)
            result["screenshot_path"] = shot_path

            for sel in ['header img[src*="logo" i]', 'nav img[src*="logo" i]', 'img[alt*="logo" i]']:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    el.screenshot(path=logo_path)
                    result["logo_path"] = logo_path
                    break
            browser.close()
    except Exception as e:
        print(f"    [Playwright Browser Pass Warning]: {e}")
    return result

# ==============================================================================
# 2. LLM AUDIT ENGINE & 10-SLIDE CONTENT GENERATOR
# ==============================================================================
def call_nrp_llm(prompt: str) -> str:
    headers = {"Authorization": f"Bearer {CONFIG['NRP_API_KEY']}", "Content-Type": "application/json"}
    payload = {
        "model": CONFIG["MODEL_NAME"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": CONFIG.get("LLM_MAX_TOKENS", 2400)
    }
    res = requests.post(f"{CONFIG['NRP_ENDPOINT']}/chat/completions", headers=headers, json=payload, timeout=120)
    res.raise_for_status()
    data = res.json()

    usage = data.get("usage", {})
    p_tokens = usage.get("prompt_tokens", 0)
    c_tokens = usage.get("completion_tokens", 0)
    t_tokens = usage.get("total_tokens", p_tokens + c_tokens)

    TOKEN_STATS["prompt_tokens"] += p_tokens
    TOKEN_STATS["completion_tokens"] += c_tokens
    TOKEN_STATS["total_tokens"] += t_tokens
    TOKEN_STATS["llm_calls"] += 1

    return data["choices"][0]["message"]["content"]


# ==============================================================================
# 2. AI PROSPECT INTELLIGENCE LAYER
# ==============================================================================
# This layer deliberately uses Python for deterministic work and sends only a
# compact evidence packet to the LLM. It is designed for experimentation:
# no claims are made about actual keyword rankings, ad spend, traffic, or AI
# search visibility unless an external data source is later connected.
# ==============================================================================

def _clamp(value, low=0, high=100):
    return max(low, min(high, int(round(value))))


def _bool_score(condition, good=100, bad=35):
    return good if condition else bad


def _tokenize(text):
    return set(re.findall(r"[a-z0-9]{3,}", (text or "").lower()))


def _business_terms(target):
    category = target.get("primary_type", "") or ""
    category = category.replace("_", " ")
    location = target.get("address", "") or ""
    parts = [p.strip() for p in re.split(r"[,|-]", location) if p.strip()]
    city = parts[0] if parts else ""
    return {
        "category": category.lower(),
        "city": city.lower(),
        "local_terms": [
            f"{category} {city}".strip().lower(),
            f"{category} near me".strip().lower(),
            f"best {category} {city}".strip().lower(),
            f"{category} services {city}".strip().lower(),
        ]
    }


def infer_search_intent(target, footprint):
    text = (footprint.get("content_snippet", "") + " " +
            target.get("editorial_summary", "")).lower()

    purchase = [
        "schedule", "book", "appointment", "call", "quote", "estimate",
        "pricing", "buy", "service", "contact", "emergency", "same day"
    ]
    research = [
        "how", "guide", "learn", "faq", "information", "resources",
        "tips", "blog", "explore"
    ]

    purchase_hits = sum(1 for x in purchase if x in text)
    research_hits = sum(1 for x in research if x in text)

    if purchase_hits >= max(3, research_hits + 1):
        primary = "Purchase / high commercial intent"
    elif research_hits > purchase_hits:
        primary = "Research / consideration"
    else:
        primary = "Mixed commercial + research intent"

    return {
        "primary": primary,
        "purchase_signals": purchase_hits,
        "research_signals": research_hits,
        "pre_purchase_questions": [
            "What does this service cost?",
            "How quickly can the business respond?",
            "Why should a local buyer choose this provider?"
        ]
    }


def build_keyword_opportunities(target, footprint, rival=None, rival_fp=None):
    terms = _business_terms(target)
    category = terms["category"]
    city = terms["city"]

    # These are opportunity hypotheses, not measured ranking gaps.
    candidates = [
        f"{category} {city}",
        f"best {category} {city}",
        f"{category} near me",
        f"{category} services {city}",
        f"{category} company {city}",
        f"{category} quote {city}",
        f"{category} estimate {city}",
        f"{category} emergency {city}",
    ]

    content = _tokenize(footprint.get("content_snippet", ""))
    scored = []

    for kw in candidates:
        words = _tokenize(kw)
        overlap = len(words & content)
        commercial = any(x in kw for x in ["best", "near me", "quote", "estimate", "company", "services"])
        score = 50 + (15 if commercial else 0) + (10 if overlap == 0 else 0) + (5 if city else 0)
        if footprint.get("has_meta_desc") is False:
            score += 5
        scored.append({
            "keyword": kw,
            "opportunity_score": _clamp(score),
            "reason": "Commercial/local phrase worth testing; current page evidence is limited."
        })

    scored.sort(key=lambda x: x["opportunity_score"], reverse=True)

    return {
        "type": "inferred_opportunities",
        "top_terms": scored[:5],
        "keyword_gap_note": (
            "These are inferred opportunity hypotheses from the page footprint. "
            "Connect an SEO data provider later to replace inference with measured rankings."
        )
    }


def score_local_search(target, footprint, rival=None, rival_fp=None):
    score = 100
    gaps = []

    if not footprint.get("has_schema"):
        score -= 15
        gaps.append("Add LocalBusiness/Organization structured data")
    if not footprint.get("has_meta_desc"):
        score -= 10
        gaps.append("Improve local search metadata")
    if not footprint.get("has_click_to_call"):
        score -= 12
        gaps.append("Add mobile tap-to-call")
    if not footprint.get("has_lead_form"):
        score -= 10
        gaps.append("Add local lead capture")
    if not footprint.get("is_mobile_responsive"):
        score -= 15
        gaps.append("Improve mobile rendering")
    if not footprint.get("has_ssl"):
        score -= 10
        gaps.append("Use HTTPS")
    if target.get("review_count", 0) < 50:
        score -= 8
        gaps.append("Build review volume")
    if target.get("rating", 0) and target.get("rating", 0) < 4.5:
        score -= 5
        gaps.append("Improve review sentiment")

    if rival:
        if rival.get("review_count", 0) > target.get("review_count", 0) * 1.5:
            gaps.append("Competitor has materially greater review volume")
            score -= 5
        if rival.get("rating", 0) > target.get("rating", 0) + 0.2:
            gaps.append("Competitor has higher visible rating")
            score -= 5

    return {
        "score": _clamp(score),
        "gaps": gaps[:6]
    }


def compare_competitors(target, target_fp, competitors):
    rows = []
    for rival, rival_fp in competitors:
        rows.append({
            "name": rival.get("name", "Unknown"),
            "rating": rival.get("rating", 0),
            "reviews": rival.get("review_count", 0),
            "speed_sec": rival_fp.get("load_speed_sec", 0),
            "lead_form": rival_fp.get("has_lead_form", False),
            "tap_to_call": rival_fp.get("has_click_to_call", False),
            "schema": rival_fp.get("has_schema", False),
            "booking": rival_fp.get("has_booking_embed", False),
        })

    target_metrics = {
        "rating": target.get("rating", 0),
        "reviews": target.get("review_count", 0),
        "speed_sec": target_fp.get("load_speed_sec", 0),
        "lead_form": target_fp.get("has_lead_form", False),
        "tap_to_call": target_fp.get("has_click_to_call", False),
        "schema": target_fp.get("has_schema", False),
        "booking": target_fp.get("has_booking_embed", False),
    }

    weaknesses = []
    for r in rows:
        if r["reviews"] > target_metrics["reviews"] * 1.5:
            weaknesses.append(f"{r['name']}: review volume materially exceeds target")
        if r["rating"] and target_metrics["rating"] and r["rating"] > target_metrics["rating"] + 0.2:
            weaknesses.append(f"{r['name']}: higher visible rating")
        if r["lead_form"] and not target_metrics["lead_form"]:
            weaknesses.append(f"{r['name']}: has lead capture while target does not")
        if r["tap_to_call"] and not target_metrics["tap_to_call"]:
            weaknesses.append(f"{r['name']}: has tap-to-call while target does not")
        if r["schema"] and not target_metrics["schema"]:
            weaknesses.append(f"{r['name']}: has structured data while target does not")
        if r["booking"] and not target_metrics["booking"]:
            weaknesses.append(f"{r['name']}: offers online booking while target does not")

    return {
        "target": target_metrics,
        "competitors": rows,
        "observed_gaps": weaknesses[:8]
    }


def build_competitive_attack_map(target, target_fp, intel):
    actions = []

    if not target_fp.get("has_click_to_call"):
        actions.append({
            "opportunity": "Mobile conversion",
            "competitor_weakness": "Competitors may provide easier contact paths",
            "client_advantage": "Can implement immediately",
            "evidence": "No tel: link detected",
            "difficulty": "Low",
            "impact": "High",
            "action": "Add persistent tap-to-call CTA"
        })

    if not target_fp.get("has_schema"):
        actions.append({
            "opportunity": "Local search",
            "competitor_weakness": "Structured-data visibility gap",
            "client_advantage": "Technical fix is controllable",
            "evidence": "No JSON-LD schema detected",
            "difficulty": "Low",
            "impact": "Medium",
            "action": "Deploy appropriate LocalBusiness schema"
        })

    if not target_fp.get("has_booking_embed"):
        actions.append({
            "opportunity": "Booking conversion",
            "competitor_weakness": "Competitors with booking can reduce friction",
            "client_advantage": "Can add scheduling without redesigning entire site",
            "evidence": "No recognized booking platform detected",
            "difficulty": "Medium",
            "impact": "High",
            "action": "Add online scheduling or consultation CTA"
        })

    if intel["local_search"]["score"] < 75:
        actions.append({
            "opportunity": "Local acquisition",
            "competitor_weakness": "Local search fundamentals are incomplete",
            "client_advantage": "Multiple technical improvements available",
            "evidence": "; ".join(intel["local_search"]["gaps"][:2]),
            "difficulty": "Medium",
            "impact": "High",
            "action": "Run local SEO foundation sprint"
        })

    return actions[:6]


def collect_competitive_intelligence(target, target_fp, category, location, primary_rival=None, primary_rival_fp=None):
    """Build compact strategic evidence without another LLM call."""
    level = CONFIG.get("INTELLIGENCE_LEVEL", "FAST")

    competitor_pairs = []
    if primary_rival:
        competitor_pairs.append((primary_rival, primary_rival_fp or {}))

    desired = 1 if level == "FAST" else (3 if level == "STANDARD" else min(CONFIG.get("MAX_COMPETITORS", 5), 5))

    if desired > 1:
        candidates = find_businesses(category, location, limit=desired + 2)
        candidates = [
            c for c in candidates
            if c.get("name", "").lower() != target.get("name", "").lower()
        ][:desired - 1]

        # Avoid duplicate scraping work when the first benchmark is returned again.
        existing_domains = {extract_clean_domain(r.get("website", "")) for r, _ in competitor_pairs}
        candidates = [
            c for c in candidates
            if extract_clean_domain(c.get("website", "")) not in existing_domains
        ]

        with ThreadPoolExecutor(max_workers=min(4, max(1, len(candidates)))) as ex:
            futures = {ex.submit(scrape_site_footprint_cached, c.get("website", ""), "competitor"): c for c in candidates}
            for future in as_completed(futures):
                c = futures[future]
                try:
                    competitor_pairs.append((c, future.result()))
                except Exception:
                    competitor_pairs.append((c, {}))

    search_intent = infer_search_intent(target, target_fp)
    keywords = build_keyword_opportunities(target, target_fp, primary_rival, primary_rival_fp)
    local = score_local_search(target, target_fp, primary_rival, primary_rival_fp)
    competitive = compare_competitors(target, target_fp, competitor_pairs)

    # Deterministic opportunity scores. Higher = greater opportunity for the agency.
    conversion_gap = 100
    if target_fp.get("has_lead_form"): conversion_gap -= 20
    if target_fp.get("has_click_to_call"): conversion_gap -= 20
    if target_fp.get("has_booking_embed"): conversion_gap -= 20
    if target_fp.get("has_live_chat"): conversion_gap -= 10
    conversion_gap = _clamp(conversion_gap)

    technical_gap = 100
    if target_fp.get("has_ssl"): technical_gap -= 10
    if target_fp.get("has_schema"): technical_gap -= 20
    if target_fp.get("has_meta_desc"): technical_gap -= 15
    if target_fp.get("is_mobile_responsive"): technical_gap -= 15
    if target_fp.get("heading_issue") == "None": technical_gap -= 10
    if target_fp.get("images_missing_alt", 0) == 0: technical_gap -= 10
    technical_gap = _clamp(technical_gap)

    competitive_score = 50 + min(40, len(competitive["observed_gaps"]) * 7)
    competitive_score = _clamp(competitive_score)

    overall = _clamp(
        local["score"] * 0.25 +
        conversion_gap * 0.30 +
        technical_gap * 0.20 +
        competitive_score * 0.25
    )

    intel = {
        "intelligence_level": level,
        "overall_opportunity_score": overall,
        "search_opportunity_score": _clamp((100 - technical_gap) * 0.5 + len(keywords["top_terms"]) * 7),
        "local_search": local,
        "conversion_opportunity_score": conversion_gap,
        "technical_gap_score": technical_gap,
        "competitive_opportunity_score": competitive_score,
        "search_intent": search_intent,
        "keyword_opportunities": keywords,
        "competitive_comparison": competitive,
        "confidence": {
            "website_signals": "Observed",
            "competitor_signals": "Observed",
            "keyword_opportunities": "Inferred",
            "search_intent": "Inferred",
            "competitor_traffic": "Not measured",
            "competitor_ad_spend": "Not measured",
            "ai_search_visibility": "Not measured"
        }
    }

    intel["competitive_attack_map"] = build_competitive_attack_map(target, target_fp, intel)
    intel["recommended_services"] = []

    if conversion_gap >= 60:
        intel["recommended_services"].append("Conversion optimization")
    if technical_gap >= 45:
        intel["recommended_services"].append("Technical SEO")
    if local["score"] < 80:
        intel["recommended_services"].append("Local SEO / Google Business Profile")
    if keywords["top_terms"]:
        intel["recommended_services"].append("Local search content / landing pages")
    if not target_fp.get("has_booking_embed"):
        intel["recommended_services"].append("Online booking / lead capture")

    # Keep the object deliberately compact before it enters the LLM prompt.
    return intel


def compact_strategy_packet(target, target_fp, rival, rival_fp, intel):
    """Reduce the full audit data to a small LLM evidence packet."""
    packet = {
        "level": intel["intelligence_level"],
        "scores": {
            "overall_opportunity": intel["overall_opportunity_score"],
            "search_opportunity": intel["search_opportunity_score"],
            "local_search_opportunity": intel["local_search"]["score"],
            "conversion_opportunity": intel["conversion_opportunity_score"],
            "competitive_opportunity": intel["competitive_opportunity_score"],
            "technical_gap": intel["technical_gap_score"],
        },
        "target": {
            "rating": target.get("rating", 0),
            "reviews": target.get("review_count", 0),
            "speed_sec": target_fp.get("load_speed_sec", 0),
            "missing_elements": target_fp.get("missing_elements", [])[:6],
        },
        "competitors": intel["competitive_comparison"]["competitors"][:5],
        "observed_competitor_gaps": intel["competitive_comparison"]["observed_gaps"][:6],
        "keyword_opportunities": [x["keyword"] for x in intel["keyword_opportunities"]["top_terms"][:5]],
        "search_intent": intel["search_intent"]["primary"],
        "local_gaps": intel["local_search"]["gaps"][:6],
        "recommended_services": intel["recommended_services"][:5],
        "attack_map": intel["competitive_attack_map"][:5],
        "confidence": intel["confidence"]
    }
    return packet

def generate_audit(target: dict, target_fp: dict, contact: dict, rival: dict = None, rival_fp: dict = None, strategy_packet: dict = None) -> dict:
    has_rival = rival is not None
    strategy_packet = strategy_packet or {}
    rival_context = ""
    if has_rival:
        rival_context = f"""
BENCHMARK COMPETITOR:
- Name: {rival['name']} | Rating: {rival['rating']} ({rival['review_count']} reviews)
- Speed: {rival_fp['load_speed_sec']}s | Form: {rival_fp['has_lead_form']} | Call: {rival_fp['has_click_to_call']}
"""

    prompt = f"""
Analyze this business and return ONLY a valid JSON object matching the requested schema.
Target Decision Maker: {contact['name']} ({contact['title']})
Business: {target['name']} | Website: {target['website']}
Google Rating: {target['rating']} stars ({target['review_count']} reviews) | Phone: {target.get('phone', 'N/A')}
Category / Type: {target.get('primary_type', 'Business')}
Google Editorial Summary: {target.get('editorial_summary', 'None')}
Load Speed: {target_fp['load_speed_sec']}s | SSL: {target_fp['has_ssl']} | Form: {target_fp['has_lead_form']} | Call: {target_fp['has_click_to_call']}
CMS: {target_fp['cms_framework']} | Booking: {target_fp['has_booking_embed']} ({target_fp['booking_platform']}) | Chat: {target_fp['has_live_chat']}
Analytics: GA4={target_fp['has_ga4']}, GTM={target_fp['has_gtm']}, MetaPixel={target_fp['has_meta_pixel']}
Heading Status: {target_fp['heading_issue']} | Missing Alt Imgs: {target_fp['images_missing_alt']}/{target_fp['total_images']}
Technical Flags: {target_fp['missing_elements']}
{rival_context}

COMPACT STRATEGY / INTELLIGENCE PACKET:
{json.dumps(strategy_packet, ensure_ascii=False, separators=(",", ":"))}

IMPORTANT EVIDENCE RULE:
- Treat website and competitor measurements as OBSERVED.
- Treat keyword opportunities and search intent as INFERRED hypotheses.
- Do not claim measured rankings, traffic, ad spend, backlink counts, or AI-search visibility unless supplied in the packet.
- Use the packet to improve the strategic recommendations without inventing facts.

CRITICAL INSTRUCTIONS:
1. 'intro_voiceover' MUST start EXACTLY with:
"We took a look at your current available digital marketing approach and think we can help you do better."
Followed by a concise breakdown of research performed and preview of the strategic solution.
2. Every slide in 'body_slides' MUST contain:
   - 'pill': Short category eyebrow string (e.g. "04 / TECHNICAL SEO HIERARCHY")
   - 'title': High-impact headline
   - 'bullets': EXACTLY 3 concise, punchy bullets (MAX 10-12 WORDS PER BULLET). These must NOT duplicate the voiceover text.
   - 'voiceover': 15-18 seconds spoken narrative.
3. Compute all required numeric scores (1-100) and gap metrics.

Return strictly this JSON schema:
{{
  "strategy": {{
    "overall_opportunity_score": 75,
    "search_opportunity_score": 70,
    "competitive_opportunity_score": 65,
    "local_search_opportunity_score": 80,
    "conversion_opportunity_score": 85,
    "top_keyword_opportunity": "best service city",
    "search_intent": "Purchase / high commercial intent",
    "recommended_services": ["Local SEO", "Conversion Optimization"],
    "competitive_weakness": "Short evidence-based statement",
    "outreach_angle": "Short personalized reason to contact this prospect",
    "confidence": "Medium"
  }},
  "scores": {{
    "seo": 70,
    "social_media": 65,
    "website_speed": 55,
    "content_clarity": 80,
    "lead_conversion": 50,
    "reputation": 75,
    "mobile_conversion_readiness": 50,
    "directory_nap_consistency": 80,
    "pipeline_leakage_index": 70
  }},
  "competitor_gap_margin": "Competitor leads by +1.2 stars, +162 reviews, and 2.1s faster mobile response",
  "quick_win": "Deploy instant tap-to-call links and LocalBusiness schema markup",
  "core_weakness": "Mobile conversion friction and unindexed structured schema",
  "solution": "Turnkey conversion architecture upgrade and mobile UX optimization",
  "email_subject": "Revenue diagnostic & lead conversion roadmap for {target['name']}",
  "email_body": "Hi {contact['name']}, we evaluated {target['name']}'s local conversion infrastructure and flagged key points of lead leakage. Attached is an executive briefing detailing the exact revenue roadmap.",
  "intro_voiceover": "We took a look at your current available digital marketing approach and think we can help you do better. We audited your page speed, mobile conversion capture, and local search presence to show where high-intent inquiries drop off, and the turnkey roadmap to resolve it.",
  "intro_bullets": [
    "Audited page speed, lead flow, and mobile conversion friction",
    "Identified key conversion bottlenecks suppressing local inquiries",
    "Delivering clear, zero-friction revenue recovery roadmap"
  ],
  "slide_2_viewport_voiceover": "Here is your current above-the-fold digital storefront on mobile and desktop. Notice how visitors must search for a contact point rather than engaging an immediate conversion trigger.",
  "slide_2_viewport_bullets": [
    "Current above-the-fold layout evaluated for immediate buyer action",
    "Key conversion triggers remain below the primary viewing fold",
    "Friction increases bounce rate among active local buyers"
  ],
  "slide_3_competitor_voiceover": "When comparing your digital presence against top local rivals, differences in review volume and conversion access immediately dictate which business captures the phone call.",
  "slide_3_competitor_bullets": [
    "Benchmark competitor maintains higher review volume and velocity",
    "Faster mobile response time secures immediate local search demand",
    "Opportunity to leapfrog competitor with streamlined booking capture"
  ],
  "body_slides": [
    {{
      "pill": "04 / CORE AUDIT FINDING",
      "title": "Primary Revenue Bottleneck",
      "bullets": [
        "Inaccessible mobile touchpoints drop high-intent visitors",
        "Page load latency slows mobile engagement",
        "Missing direct conversion capture links"
      ],
      "voiceover": "Our technical diagnostic reveals that prospective customers encounter excessive friction before initiating contact, causing high-intent mobile visitors to bounce."
    }},
    {{
      "pill": "05 / SEARCH & TECHNICAL ARCHITECTURE",
      "title": "Search Visibility & Schema Gap",
      "bullets": [
        "Missing LocalBusiness JSON-LD structured schema data",
        "Heading architecture lacks clear search entity hierarchy",
        "Unoptimized images degrade mobile page load speeds"
      ],
      "voiceover": "Search engines require structured JSON-LD data to surface your location and reviews in local search packs. Without it, competitors gain search rank advantage."
    }},
    {{
      "pill": "06 / CONVERSION INFRASTRUCTURE",
      "title": "Friction in Inbound Inquiry Flow",
      "bullets": [
        "Lack of prominent tap-to-call link on mobile viewports",
        "No embedded automated booking or consultation widget",
        "High-friction inquiry forms decrease submission rates"
      ],
      "voiceover": "Modern buyers expect zero friction. Adding automated booking calendar embeds and tap-to-call triggers immediately captures buyers ready to schedule."
    }},
    {{
      "pill": "07 / PIPELINE & REVENUE IMPACT",
      "title": "Market Share & Lead Leakage",
      "bullets": [
        "Suppressed inquiry volume directly impacts pipeline revenue",
        "Competitors capture high-intent local search queries",
        "Marketing spend yields diminished return on investment"
      ],
      "voiceover": "Every dropped visit represents lost revenue. When prospective clients cannot easily call or book from their phones, they immediately turn to alternative local providers."
    }},
    {{
      "pill": "08 / THE STRATEGIC FIX",
      "title": "High-ROI Turnkey Implementation",
      "bullets": [
        "Immediate quick win: install sticky tap-to-call and schema",
        "Rebuild fast-loading mobile-first conversion storefront",
        "Deploy automated scheduling to capture after-hours inquiries"
      ],
      "voiceover": "We recommend an immediate two-phase fix: deploy instant tap-to-call triggers and local schema markup, followed by a streamlined mobile conversion layout."
    }},
    {{
      "pill": "09 / THE GROWTH ROADMAP",
      "title": "The 4-Phase Growth Architecture",
      "bullets": [
        "Phase 1 & 2: Fix core technicals and capture local market demand",
        "Phase 3: Expand audience through hyper-targeted campaigns",
        "Phase 4: Maximize lifetime value with automated AI efficiency"
      ],
      "voiceover": "Our 4-phase growth framework systematically repairs foundation leakage, captures active local search demand, and scales client acquisition without operational overhead."
    }}
  ],
  "outro_voiceover": "Let us show you how we can help. Review this deck and schedule a meeting with our leadership team at elkinsrevenue.com."
}}
"""
    try:
        raw = call_nrp_llm(prompt)
        if not raw or not isinstance(raw, str):
            raise ValueError("NRP LLM returned empty or non-string response.")
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not match:
            raise ValueError("No JSON object found in LLM response.")
        return json.loads(match.group(0)) 
    except Exception as e:
        print(f"[LLM Fallback Used]: {e}")
        return {
            "scores": {
                "seo": 70, "social_media": 60, "website_speed": 65, "content_clarity": 75,
                "lead_conversion": 50, "reputation": 70, "mobile_conversion_readiness": 50,
                "directory_nap_consistency": 80, "pipeline_leakage_index": 70
            },
            "competitor_gap_margin": "Competitor leads in review volume and mobile response",
            "quick_win": "Deploy instant tap-to-call links and local schema markup",
            "core_weakness": "Mobile conversion friction and unindexed schema",
            "solution": "Mobile-first conversion architecture update",
            "email_subject": f"Digital performance brief for {target['name']}",
            "email_body": f"Hi {contact['name']}, we evaluated your digital presence and identified opportunities to capture more inbound inquiries.",
            "intro_voiceover": "We took a look at your current available digital marketing approach and think we can help you do better. We audited your site performance and conversion friction, and this briefing outlines our recommended roadmap.",
            "intro_bullets": ["Audited website performance & lead capture", "Identified primary points of conversion leakage", "Proposing turnkey strategic roadmap"],
            "slide_2_viewport_voiceover": "Here is your current above-the-fold layout. High-intent visitors must search for contact options rather than engaging a direct call trigger.",
            "slide_2_viewport_bullets": ["Evaluated desktop and mobile above-the-fold viewport", "Primary call-to-action is not immediately visible", "Friction increases drop-off among mobile buyers"],
            "slide_3_competitor_voiceover": "Comparing your business to local market rivals reveals clear opportunities to capture lost search and inquiry volume.",
            "slide_3_competitor_bullets": ["Rivals maintain higher star ratings and review velocity", "Faster mobile response captures local search traffic", "Opportunity to reclaim market share with faster booking"],
            "body_slides": [
                {
                    "pill": "04 / CORE AUDIT FINDING",
                    "title": "Primary Revenue Bottleneck",
                    "bullets": ["Slow mobile load and hidden call links", "Friction directs local demand to competitors", "Missing structured schema markup"],
                    "voiceover": "The primary bottleneck is digital friction that causes visitors to leave before contacting your business."
                },
                {
                    "pill": "05 / SEARCH & TECHNICAL ARCHITECTURE",
                    "title": "Search Visibility & Schema Gap",
                    "bullets": ["Missing LocalBusiness JSON-LD markup", "Heading tags lack clear entity structure", "Uncompressed media slows down load speeds"],
                    "voiceover": "Search engines require structured schema data to index your business accurately for local map pack placement."
                },
                {
                    "pill": "06 / CONVERSION INFRASTRUCTURE",
                    "title": "Inbound Inquiry Friction",
                    "bullets": ["No direct tap-to-call link on mobile", "Missing automated consultation booking flow", "Forms create unnecessary user friction"],
                    "voiceover": "Adding an immediate tap-to-call button and simple calendar booking will capture high-intent inquiries instantly."
                },
                {
                    "pill": "07 / PIPELINE & REVENUE IMPACT",
                    "title": "Market Share & Lead Leakage",
                    "bullets": ["Suppressed inbound inquiry flow", "Higher local drop-off rates", "Missed revenue opportunities"],
                    "voiceover": "Without direct click-to-call options, visitors looking for immediate service look elsewhere."
                },
                {
                    "pill": "08 / THE STRATEGIC FIX",
                    "title": "The High-ROI Solution",
                    "bullets": ["Add sticky tap-to-call and contact forms", "Deploy mobile conversion triggers", "Boost conversion capture rate"],
                    "voiceover": "We recommend an immediate tactical upgrade: streamlined forms, tap-to-call buttons, and responsive pages."
                },
                {
                    "pill": "09 / THE GROWTH ROADMAP",
                    "title": "4-Phase Growth Architecture",
                    "bullets": ["Phase 1 & 2: Core conversion and local SEO", "Phase 3: Omnipresent audience expansion", "Phase 4: AI retention and automated nurturing"],
                    "voiceover": "Our 4-phase framework provides a predictable model to turn digital interest into confirmed revenue."
                }
            ],
            "outro_voiceover": "Let us show you how we can help. Review this deck and schedule a meeting with our leadership team at elkinsrevenue.com."
        }

# ==============================================================================
# 3. GRAPHIC SLIDE RENDERER (PIL) - 10 SLIDE SUITE
# ==============================================================================

def load_font(arg1, arg2=None):
    """
    Universal font loader supporting both styles:
      - load_font(size, bold=True/False)
      - load_font(["arialbd.ttf", "segoeuib.ttf"], size)
    """
    if isinstance(arg1, (list, tuple)):
        font_names = arg1
        size = arg2 if arg2 is not None else 28
    else:
        size = arg1
        bold = bool(arg2)
        font_names = ["arialbd.ttf", "segoeuib.ttf", "helveticab.ttf"] if bold else ["arial.ttf", "segoeui.ttf", "helvetica.ttf"]

    for fn in font_names:
        try:
            return ImageFont.truetype(fn, size)
        except Exception:
            continue
    return ImageFont.load_default()



def render_single_page_scorecard(lead: dict, footprint: dict, contact: dict, rival: dict, rival_fp: dict, audit: dict, shot_path: str, out_pdf_path: str):
    """
    Renders an executive-grade 8.5x11 in @ 300 DPI (2550 x 3300 px) single-page audit report.
    Integrates the live browser screenshot, progress meters, technical audit, and competitor benchmark.
    """
    W, H = 2550, 3300
    img = Image.new("RGB", (W, H), color=(248, 250, 252))  # Soft slate canvas background
    draw = ImageDraw.Draw(img)

    # 1. High-Resolution Fonts for 300 DPI Canvas
    f_brand = load_font(["arialbd.ttf", "segoeuib.ttf"], 50)
    f_subbrand = load_font(["arialbd.ttf", "segoeuib.ttf"], 36)
    f_title = load_font(["arialbd.ttf", "segoeuib.ttf"], 58)
    f_meta = load_font(["arial.ttf", "segoeui.ttf"], 30)
    f_sec = load_font(["arialbd.ttf", "segoeuib.ttf"], 40)
    f_card_title = load_font(["arialbd.ttf", "segoeuib.ttf"], 32)
    f_score_num = load_font(["arialbd.ttf", "segoeuib.ttf"], 64)
    f_table_head = load_font(["arialbd.ttf", "segoeuib.ttf"], 30)
    f_table_body = load_font(["arial.ttf", "segoeui.ttf"], 28)
    f_table_body_b = load_font(["arialbd.ttf", "segoeuib.ttf"], 28)
    f_body = load_font(["arial.ttf", "segoeui.ttf"], 30)
    f_footer = load_font(["arialbd.ttf", "segoeuib.ttf"], 28)

    # Palette
    TEXT_DARK = (15, 23, 42)
    TEXT_BODY = (51, 65, 85)
    TEXT_MUTED = (100, 116, 139)
    BLUE = (37, 99, 235)
    BLUE_BG = (239, 246, 255)
    BORDER = (226, 232, 240)
    CARD_BG = (255, 255, 255)
    GREEN = (22, 163, 74)
    RED = (220, 38, 38)
    AMBER = (217, 119, 6)

    mx = 110
    y = 100

    # 1. HEADER & BRAND BAR
    brand_title = CONFIG.get("BRAND_PRIMARY", "ELKINS & CO.").upper()
    draw.text((mx, y), brand_title, fill=TEXT_DARK, font=f_brand)
    bbox_b = draw.textbbox((mx, y), brand_title, font=f_brand)
    draw.line([(bbox_b[2] + 25, y + 6), (bbox_b[2] + 25, y + 54)], fill=TEXT_MUTED, width=3)
    draw.text((bbox_b[2] + 45, y + 10), CONFIG.get("BRAND_SUBTITLE", "REVENUE STRATEGIES"), fill=BLUE, font=f_subbrand)

    # Eyebrow Tag Pill
    pill_text = "EXECUTIVE DIAGNOSTIC REPORT"
    pb = draw.textbbox((0, 0), pill_text, font=f_table_head)
    pw = pb[2] - pb[0] + 50
    draw.rounded_rectangle([W - mx - pw, y, W - mx, y + 60], radius=12, fill=BLUE_BG, outline=BLUE, width=2)
    draw.text((W - mx - pw + 25, y + 12), pill_text, fill=BLUE, font=f_table_head)

    y += 90
    draw.line([(mx, y), (W - mx, y)], fill=BORDER, width=3)
    y += 45

    # 2. PROSPECT HERO BANNER
    hero_h = 160
    draw.rounded_rectangle([mx, y, W - mx, y + hero_h], radius=18, fill=CARD_BG, outline=BORDER, width=2)
    draw.text((mx + 45, y + 28), f"Performance Audit: {lead.get('name', 'N/A')}", fill=TEXT_DARK, font=f_title)

    contact_name = contact.get("name", "Leadership") if contact else "Leadership"
    contact_title = contact.get("title", "Owner") if contact else "Owner"
    meta_1 = f"Decision Maker: {contact_name} ({contact_title})   |   Phone: {lead.get('phone', 'N/A')}"
    meta_2 = f"Primary Domain: {lead.get('website', 'N/A')}   |   Status: Live Audit Captured"
    draw.text((mx + 45, y + 90), meta_1, fill=TEXT_BODY, font=f_meta)
    draw.text((mx + 1150, y + 90), meta_2, fill=TEXT_MUTED, font=f_meta)

    y += hero_h + 45

    # 3. SPLIT SECTION: BROWSER VIEWPORT MOCKUP vs CORE METRIC GAUGES
    split_h = 750
    left_w = 1180
    right_x = mx + left_w + 50
    right_w = W - mx - right_x

    # Left: Desktop Browser Mockup
    draw.rounded_rectangle([mx, y, mx + left_w, y + split_h], radius=18, fill=CARD_BG, outline=BORDER, width=2)
    draw.rounded_rectangle([mx, y, mx + left_w, y + 54], radius=18, fill=(241, 245, 249))
    draw.rectangle([mx, y + 36, mx + left_w, y + 54], fill=(241, 245, 249))
    draw.ellipse([mx + 25, y + 20, mx + 43, y + 38], fill=(239, 68, 68))
    draw.ellipse([mx + 55, y + 20, mx + 73, y + 38], fill=(245, 158, 11))
    draw.ellipse([mx + 85, y + 20, mx + 103, y + 38], fill=(34, 197, 94))
    draw.text((mx + 130, y + 14), lead.get("website", "https://"), fill=TEXT_MUTED, font=f_table_body)

    if shot_path and os.path.exists(shot_path):
        try:
            with Image.open(shot_path) as s_img:
                s_img = s_img.convert("RGB")
                shot_render_h = split_h - 58
                s_resized = s_img.resize((left_w - 6, shot_render_h), Image.Resampling.LANCZOS)
                img.paste(s_resized, (mx + 3, y + 55))
        except Exception:
            draw.text((mx + 320, y + 340), "[Viewport Capture Active]", fill=TEXT_MUTED, font=f_sec)
    else:
        draw.text((mx + 320, y + 340), "[Viewport Capture Active]", fill=TEXT_MUTED, font=f_sec)

    # Right: Diagnostic Gauges
    scores = audit.get("scores", {})
    gauge_list = [
        ("Mobile Conversion Readiness", scores.get("mobile_conversion_readiness", scores.get("mobile", 52))),
        ("Page Load Speed Index", scores.get("website_speed", scores.get("speed", 65))),
        ("Directory / NAP Consistency", scores.get("directory_nap_consistency", 86)),
        ("Pipeline Leakage Defense", scores.get("pipeline_leakage_index", 70))
    ]

    card_h = (split_h - (3 * 22)) // 4
    gy = y
    for label, val in gauge_list:
        draw.rounded_rectangle([right_x, gy, right_x + right_w, gy + card_h], radius=16, fill=CARD_BG, outline=BORDER, width=2)
        score_c = GREEN if val >= 80 else (AMBER if val >= 60 else RED)

        draw.text((right_x + 35, gy + 26), label, fill=TEXT_DARK, font=f_card_title)
        draw.text((right_x + right_w - 140, gy + 15), f"{val}", fill=score_c, font=f_score_num)

        bar_w = right_w - 70
        bar_y = gy + 96
        draw.rounded_rectangle([right_x + 35, bar_y, right_x + 35 + bar_w, bar_y + 16], radius=8, fill=(226, 232, 240))
        draw.rounded_rectangle([right_x + 35, bar_y, right_x + 35 + int(bar_w * (val / 100)), bar_y + 16], radius=8, fill=score_c)
        gy += card_h + 22

    y += split_h + 45

    # 4. TECHNICAL INFRASTRUCTURE & CONVERSION STACK
    draw.text((mx, y), "TECHNICAL ARCHITECTURE & CONVERSION HYGIENE", fill=TEXT_DARK, font=f_sec)
    y += 55

    tech_w = W - (2 * mx)
    tech_h = 240
    draw.rounded_rectangle([mx, y, mx + tech_w, y + tech_h], radius=16, fill=CARD_BG, outline=BORDER, width=2)

    tech_items = [
        ("CMS Framework", footprint.get("cms_framework", "Custom / Static HTML"), False),
        ("Inbound Lead Form", "Detected Above Fold" if footprint.get("has_lead_form") else "MISSING / Friction Risk", not footprint.get("has_lead_form")),
        ("Click-to-Call Link", "Configured & Active" if footprint.get("has_click_to_call") else "MISSING on Mobile", not footprint.get("has_click_to_call")),
        ("SSL Security", "Enforced (HTTPS)" if footprint.get("has_ssl") else "NOT SECURE", not footprint.get("has_ssl")),
        ("Google Analytics 4", "Active Tracking" if footprint.get("has_ga4") else "NOT DETECTED", not footprint.get("has_ga4")),
        ("Tag Manager (GTM)", "Installed" if footprint.get("has_gtm") else "Not Deployed", False),
        ("Meta Ad Pixel", "Active" if footprint.get("has_meta_pixel") else "Not Detected", False),
        ("Structured Schema", "LocalBusiness Active" if footprint.get("has_schema") else "MISSING JSON-LD", not footprint.get("has_schema")),
        ("Booking Platform", footprint.get("booking_platform", "None Detected"), False),
        ("Live Chat Platform", footprint.get("chat_platform", "None Detected"), False),
        ("Image Alt Tags", f"{footprint.get('images_missing_alt', 0)} of {footprint.get('total_images', 0)} Missing", footprint.get("images_missing_alt", 0) > 5),
        ("Heading Checks", footprint.get("heading_issue", "Clean Hierarchy"), False)
    ]

    col_span = tech_w // 3
    for i, (label, val_str, is_flagged) in enumerate(tech_items):
        t_col = i // 4
        t_row = i % 4
        ix = mx + 40 + (t_col * col_span)
        iy = y + 26 + (t_row * 48)

        status_color = RED if is_flagged else (GREEN if any(k in val_str for k in ["Active", "Configured", "Detected"]) else TEXT_BODY)
        draw.text((ix, iy), f"{label}:", fill=TEXT_MUTED, font=f_table_body)
        draw.text((ix + 260, iy), val_str, fill=status_color, font=f_table_body_b)

    y += tech_h + 45

    # 5. COMPETITIVE BENCHMARK MATRIX
    draw.text((mx, y), "LOCAL COMPETITOR MARKET BENCHMARK", fill=TEXT_DARK, font=f_sec)
    y += 55

    bench_h = 240
    draw.rounded_rectangle([mx, y, mx + tech_w, y + bench_h], radius=16, fill=CARD_BG, outline=BORDER, width=2)

    col1_x = mx + 40
    col2_x = mx + 700
    col3_x = mx + 1350
    col4_x = mx + 1850

    draw.text((col1_x, y + 22), "BENCHMARK DIMENSION", fill=TEXT_MUTED, font=f_table_head)
    draw.text((col2_x, y + 22), f"YOUR BUSINESS ({lead.get('name', 'Prospect')[:20]})", fill=TEXT_DARK, font=f_table_head)
    rival_label = rival.get('name', 'Top Local Competitor')[:20] if rival else 'Top Local Competitor'
    draw.text((col3_x, y + 22), f"RIVAL ({rival_label})", fill=BLUE, font=f_table_head)
    draw.text((col4_x, y + 22), "ESTIMATED REVENUE IMPACT", fill=TEXT_MUTED, font=f_table_head)

    draw.line([(mx + 30, y + 68), (mx + tech_w - 30, y + 68)], fill=BORDER, width=2)

    t_stars = f"{lead.get('rating', 'N/A')}★ ({lead.get('review_count', 0)} reviews)"
    r_stars = f"{rival.get('rating', 4.8)}★ ({rival.get('review_count', 0)} reviews)" if rival else "N/A"
    t_speed = f"{footprint.get('load_speed_sec', 'N/A')}s"
    r_speed = f"{rival_fp.get('load_speed_sec', '1.1')}s" if rival_fp else "N/A"

    b_rows = [
        ("Public Reputation & Trust", t_stars, r_stars, audit.get("competitor_gap_margin", "Rival captures more high-intent volume")[:34]),
        ("Speed & Mobile Responsiveness", t_speed, r_speed, "Speed latency causing mobile visitor bounce"),
        ("Conversion Capture Infrastructure", "Forms & Call Check", "Optimized Booking Flow", "Pipeline leakage to top-ranking local options")
    ]

    for idx, (m_col, t_col, r_col, i_col) in enumerate(b_rows):
        ry = y + 84 + (idx * 48)
        draw.text((col1_x, ry), m_col, fill=TEXT_BODY, font=f_table_body)
        draw.text((col2_x, ry), t_col, fill=TEXT_DARK, font=f_table_body_b)
        draw.text((col3_x, ry), r_col, fill=BLUE, font=f_table_body_b)
        draw.text((col4_x, ry), i_col, fill=RED if any(k in i_col for k in ["leakage", "bounce"]) else TEXT_BODY, font=f_table_body)

    y += bench_h + 45

    # 6. STRATEGIC BOTTLENECKS & QUICK WIN
    box_w = (tech_w - 40) // 2
    box_h = 310

    # Weakness Box
    draw.rounded_rectangle([mx, y, mx + box_w, y + box_h], radius=16, fill=(254, 242, 242), outline=(254, 202, 202), width=2)
    draw.text((mx + 35, y + 25), "PRIMARY DETECTED REVENUE LEAK", fill=RED, font=f_table_head)
    weakness_text = audit.get("core_weakness", "Mobile friction and missing tap-to-call links redirect qualified inbound callers.")
    draw.text((mx + 35, y + 75), weakness_text[:120], fill=TEXT_DARK, font=f_card_title)
    draw.text((mx + 35, y + 155), "• Mobile abandonment due to missing direct tap-to-call links.", fill=TEXT_BODY, font=f_body)
    draw.text((mx + 35, y + 205), "• Local searchers bounce due to missing schema JSON-LD indexing.", fill=TEXT_BODY, font=f_body)
    draw.text((mx + 35, y + 255), "• Unleveraged review volume leaks traffic to higher-rated rivals.", fill=TEXT_BODY, font=f_body)

    # Solution Box
    bx2 = mx + box_w + 40
    draw.rounded_rectangle([bx2, y, bx2 + box_w, y + box_h], radius=16, fill=BLUE_BG, outline=(191, 219, 254), width=2)
    draw.text((bx2 + 35, y + 25), "HIGH-ROI TURNKEY SOLUTION & ROADMAP", fill=BLUE, font=f_table_head)
    quick_win_text = audit.get("quick_win", "Deploy 1-click tap-to-call mobile links, booking funnel, and local schema.")
    draw.text((bx2 + 35, y + 75), quick_win_text[:120], fill=TEXT_DARK, font=f_card_title)
    draw.text((bx2 + 35, y + 155), "• Deploy sticky smartphone tap-to-call links across all pages.", fill=TEXT_BODY, font=f_body)
    draw.text((bx2 + 35, y + 205), "• Implement LocalBusiness structured schema for Google Map Pack.", fill=TEXT_BODY, font=f_body)
    draw.text((bx2 + 35, y + 255), "• Launch automated review generation to close the competitor gap.", fill=TEXT_BODY, font=f_body)

    # 7. FOOTER CALL-TO-ACTION
    foot_y = H - 230
    draw.rounded_rectangle([mx, foot_y, W - mx, foot_y + 150], radius=16, fill=TEXT_DARK)
    draw.text((mx + 45, foot_y + 28), "READY TO ELIMINATE REVENUE LEAKAGE AND DOMINATE YOUR LOCAL MARKET?", fill=(255, 255, 255), font=f_card_title)

    contact_c = f"WEB: {CONFIG.get('AGENCY_WEBSITE', 'www.elkinsrevenue.com').lower()}   |   PHONE: {CONFIG.get('AGENCY_PHONE', '917-327-0636')}   |   EMAIL: {CONFIG.get('AGENCY_EMAIL', 'lorren@elkinsrevenue.com')}"
    draw.text((mx + 45, foot_y + 85), contact_c, fill=BLUE, font=f_footer)

    # Export PDF directly
    img.save(out_pdf_path, "PDF", resolution=300.0)
    print(f"  -> Executive Scorecard PDF successfully generated: {out_pdf_path}")
    return out_pdf_path

# ==============================================================================
# 5. DATA PERSISTENCE & OUTREACH DISPATCH
# ==============================================================================
from googleapiclient.discovery import build

SLIDES_SCOPES = [
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/drive"
]
CLIENT_SECRETS_FILE = r"G:\My Drive\Elkins Revenue Consulting\AI Agent Scripts\client_secrets.json"
TOKEN_FILE = r"G:\My Drive\Elkins Revenue Consulting\AI Agent Scripts\slides_token.json"

def get_slides_and_drive_service():
    """Authenticates as the human Google user via OAuth, giving full Drive storage capacity."""
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SLIDES_SCOPES)
        
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CLIENT_SECRETS_FILE):
                raise FileNotFoundError(f"Missing OAuth secrets file: {CLIENT_SECRETS_FILE}")
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SLIDES_SCOPES)
            creds = flow.run_local_server(port=0)
            
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())
            
    slides_service = build("slides", "v1", credentials=creds)
    drive_service = build("drive", "v3", credentials=creds)
    return slides_service, drive_service

def assemble_google_slides(lead: dict, footprint: dict, contact: dict, audit: dict, rival: dict, rival_fp: dict, shot_path: str = None, logo_path: str = None) -> str:
    slides_service, drive_service = get_slides_and_drive_service()
    clean_lead_name = lead.get('name', 'Prospect').strip()
    title = f"{clean_lead_name} - Digital Diagnostic & Revenue Roadmap"
    
    # 1. Create a brand-new, unique presentation inside your 'ElkinsRev Prospect Videos' folder
    target_folder_id = "1I3DrNVXGTJISxMenvtDvRtYOTWcPzD7f"
    file_metadata = {
        'name': title,
        'mimeType': 'application/vnd.google-apps.presentation',
        'parents': [target_folder_id]
    }
    file = drive_service.files().create(body=file_metadata, fields='id').execute()
    pres_id = file.get("id")

    # 2. Structure slide content
    slides_data = [
        {
            "pill": "CONFIDENTIAL EXECUTIVE BRIEFING · RESEARCH & STRATEGY",
            "title": f"Digital Diagnostic & Revenue Roadmap\nPrepared for {clean_lead_name}",
            "bullets": audit.get("intro_bullets", [
                "Audited page speed, lead flow, and mobile conversion friction",
                "Identified key conversion bottlenecks suppressing local inquiries",
                "Delivering clear, zero-friction revenue recovery roadmap"
            ])
        },
        {
            "pill": "02 / VISUAL CONVERSION AUDIT",
            "title": "Above-the-Fold Viewport & Mobile Access",
            "bullets": audit.get("slide_2_viewport_bullets", [
                "Current above-the-fold layout evaluated for immediate buyer action",
                "Key conversion triggers remain below the primary viewing fold",
                "Friction increases bounce rate among active local buyers"
            ])
        },
        {
            "pill": "03 / COMPETITIVE BENCHMARK",
            "title": f"Local Market Benchmark: {rival.get('name', 'Local Rival') if rival else 'Competitor'}",
            "bullets": audit.get("slide_3_competitor_bullets", [
                f"Benchmark rival holds {rival.get('rating', 4.8)}★ across {rival.get('review_count', 180)} reviews",
                f"Page speed clocked at {rival_fp.get('load_speed_sec', 1.2)}s response latency",
                "Clear opportunity to recapture local market share with frictionless booking"
            ])
        }
    ]
    
    for s in audit.get("body_slides", []):
        slides_data.append({
            "pill": s.get("pill", "DIAGNOSTIC FINDING"),
            "title": s.get("title", ""),
            "bullets": s.get("bullets", [])
        })
        
    slides_data.append({
        "pill": "10 / NEXT STEPS & CALL TO ACTION",
        "title": CONFIG.get("CUSTOM_CTA", "Let us show you how we can help. Review this deck and schedule a meeting with us."),
        "bullets": [
            f"Direct Website Consultation: {CONFIG.get('AGENCY_WEBSITE')}",
            f"Direct Leadership Inquiries: {CONFIG.get('AGENCY_PHONE')}",
            f"Executive Email Dispatch: {CONFIG.get('AGENCY_EMAIL')}"
        ]
    })

    # 3. Styling Palette
    COLOR_BG = {"red": 1.0, "green": 1.0, "blue": 1.0}
    COLOR_CARD = {"red": 0.97, "green": 0.98, "blue": 0.99}
    COLOR_BORDER = {"red": 0.88, "green": 0.91, "blue": 0.94}
    COLOR_BLUE = {"red": 0.145, "green": 0.388, "blue": 0.922}
    COLOR_PILL_BG = {"red": 0.937, "green": 0.965, "blue": 1.0}
    COLOR_DARK = {"red": 0.06, "green": 0.09, "blue": 0.16}
    COLOR_BODY = {"red": 0.12, "green": 0.16, "blue": 0.23}
    COLOR_MUTED = {"red": 0.40, "green": 0.45, "blue": 0.55}

    requests_list = []
    
    # 4. Generate the 10 styled slides
    for idx, slide_info in enumerate(slides_data):
        slide_id = f"exec_slide_{idx}"
        card_id = f"card_bg_{idx}"
        brand_id = f"brand_{idx}"
        pill_id = f"pill_{idx}"
        title_id = f"title_{idx}"
        body_id = f"body_{idx}"
        footer_id = f"footer_{idx}"

        # Create slide
        requests_list.append({
            "createSlide": {
                "objectId": slide_id,
                "slideLayoutReference": {"predefinedLayout": "BLANK"}
            }
        })

        # Set slide background color using updatePageProperties
        requests_list.append({
            "updatePageProperties": {
                "objectId": slide_id,
                "fields": "pageBackgroundFill.solidFill.color",
                "pageProperties": {
                    "pageBackgroundFill": {
                        "solidFill": {
                            "color": {"rgbColor": COLOR_BG}
                        }
                    }
                }
            }
        })

        # Soft Card Background (using ROUND_RECTANGLE)
        requests_list.append({
            "createShape": {
                "objectId": card_id,
                "shapeType": "ROUND_RECTANGLE",
                "elementProperties": {
                    "pageObjectId": slide_id,
                    "size": {"width": {"magnitude": 660, "unit": "PT"}, "height": {"magnitude": 345, "unit": "PT"}},
                    "transform": {"scaleX": 1, "scaleY": 1, "translateX": 30, "translateY": 30, "unit": "PT"}
                }
            }
        })
        requests_list.append({
            "updateShapeProperties": {
                "objectId": card_id,
                "fields": "shapeBackgroundFill.solidFill.color,outline.outlineFill.solidFill.color,outline.weight",
                "shapeProperties": {
                    "shapeBackgroundFill": {"solidFill": {"color": {"rgbColor": COLOR_CARD}}},
                    "outline": {"outlineFill": {"solidFill": {"color": {"rgbColor": COLOR_BORDER}}}, "weight": {"magnitude": 1.5, "unit": "PT"}}
                }
            }
        })

        # Brand Lockup
        requests_list.append({
            "createShape": {
                "objectId": brand_id,
                "shapeType": "TEXT_BOX",
                "elementProperties": {
                    "pageObjectId": slide_id,
                    "size": {"width": {"magnitude": 400, "unit": "PT"}, "height": {"magnitude": 25, "unit": "PT"}},
                    "transform": {"scaleX": 1, "scaleY": 1, "translateX": 55, "translateY": 48, "unit": "PT"}
                }
            }
        })
        requests_list.append({
            "insertText": {"objectId": brand_id, "text": f"{CONFIG.get('BRAND_PRIMARY', 'ELKINS & CO.')}  |  {CONFIG.get('BRAND_SUBTITLE', 'REVENUE STRATEGIES')}", "insertionIndex": 0}
        })
        requests_list.append({
            "updateTextStyle": {
                "objectId": brand_id, "fields": "fontFamily,fontSize,bold,foregroundColor", "textRange": {"type": "ALL"},
                "style": {"fontFamily": "Calibri", "fontSize": {"magnitude": 10, "unit": "PT"}, "bold": True, "foregroundColor": {"opaqueColor": {"rgbColor": COLOR_MUTED}}}
            }
        })

        # Category Eyebrow Pill (using ROUND_RECTANGLE)
        pill_txt = slide_info["pill"].upper()
        requests_list.append({
            "createShape": {
                "objectId": pill_id,
                "shapeType": "ROUND_RECTANGLE",
                "elementProperties": {
                    "pageObjectId": slide_id,
                    "size": {"width": {"magnitude": max(180, len(pill_txt) * 6.5), "unit": "PT"}, "height": {"magnitude": 20, "unit": "PT"}},
                    "transform": {"scaleX": 1, "scaleY": 1, "translateX": 55, "translateY": 82, "unit": "PT"}
                }
            }
        })
        requests_list.append({
            "updateShapeProperties": {
                "objectId": pill_id,
                "fields": "shapeBackgroundFill.solidFill.color,outline.outlineFill.solidFill.color,outline.weight",
                "shapeProperties": {
                    "shapeBackgroundFill": {"solidFill": {"color": {"rgbColor": COLOR_PILL_BG}}},
                    "outline": {"outlineFill": {"solidFill": {"color": {"rgbColor": COLOR_BLUE}}}, "weight": {"magnitude": 1, "unit": "PT"}}
                }
            }
        })
        requests_list.append({
            "insertText": {"objectId": pill_id, "text": pill_txt, "insertionIndex": 0}
        })
        requests_list.append({
            "updateTextStyle": {
                "objectId": pill_id, "fields": "fontFamily,fontSize,bold,foregroundColor", "textRange": {"type": "ALL"},
                "style": {"fontFamily": "Calibri", "fontSize": {"magnitude": 8.5, "unit": "PT"}, "bold": True, "foregroundColor": {"opaqueColor": {"rgbColor": COLOR_BLUE}}}
            }
        })

        # Headline
        requests_list.append({
            "createShape": {
                "objectId": title_id,
                "shapeType": "TEXT_BOX",
                "elementProperties": {
                    "pageObjectId": slide_id,
                    "size": {"width": {"magnitude": 600, "unit": "PT"}, "height": {"magnitude": 50, "unit": "PT"}},
                    "transform": {"scaleX": 1, "scaleY": 1, "translateX": 55, "translateY": 110, "unit": "PT"}
                }
            }
        })
        requests_list.append({
            "insertText": {"objectId": title_id, "text": slide_info["title"], "insertionIndex": 0}
        })
        requests_list.append({
            "updateTextStyle": {
                "objectId": title_id, "fields": "fontFamily,fontSize,bold,foregroundColor", "textRange": {"type": "ALL"},
                "style": {"fontFamily": "Calibri", "fontSize": {"magnitude": 18, "unit": "PT"}, "bold": True, "foregroundColor": {"opaqueColor": {"rgbColor": COLOR_DARK}}}
            }
        })

        # Bullets
        bullets_text = "\n".join([f"•   {b}" for b in slide_info.get("bullets", [])[:3]])
        requests_list.append({
            "createShape": {
                "objectId": body_id,
                "shapeType": "TEXT_BOX",
                "elementProperties": {
                    "pageObjectId": slide_id,
                    "size": {"width": {"magnitude": 600, "unit": "PT"}, "height": {"magnitude": 160, "unit": "PT"}},
                    "transform": {"scaleX": 1, "scaleY": 1, "translateX": 55, "translateY": 170, "unit": "PT"}
                }
            }
        })
        requests_list.append({
            "insertText": {"objectId": body_id, "text": bullets_text, "insertionIndex": 0}
        })
        requests_list.append({
            "updateTextStyle": {
                "objectId": body_id, "fields": "fontFamily,fontSize,foregroundColor", "textRange": {"type": "ALL"},
                "style": {"fontFamily": "Calibri", "fontSize": {"magnitude": 13, "unit": "PT"}, "foregroundColor": {"opaqueColor": {"rgbColor": COLOR_BODY}}}
            }
        })

        # Footer
        requests_list.append({
            "createShape": {
                "objectId": footer_id,
                "shapeType": "TEXT_BOX",
                "elementProperties": {
                    "pageObjectId": slide_id,
                    "size": {"width": {"magnitude": 600, "unit": "PT"}, "height": {"magnitude": 20, "unit": "PT"}},
                    "transform": {"scaleX": 1, "scaleY": 1, "translateX": 55, "translateY": 345, "unit": "PT"}
                }
            }
        })
        requests_list.append({
            "insertText": {"objectId": footer_id, "text": f"CONFIDENTIAL · PREPARED FOR EXECUTIVE REVIEW          {CONFIG.get('AGENCY_WEBSITE')}", "insertionIndex": 0}
        })
        requests_list.append({
            "updateTextStyle": {
                "objectId": footer_id, "fields": "fontFamily,fontSize,bold,foregroundColor", "textRange": {"type": "ALL"},
                "style": {"fontFamily": "Calibri", "fontSize": {"magnitude": 7.5, "unit": "PT"}, "bold": True, "foregroundColor": {"opaqueColor": {"rgbColor": COLOR_MUTED}}}
            }
        })

    # Execute all batch updates
    slides_service.presentations().batchUpdate(
        presentationId=pres_id,
        body={"requests": requests_list}
    ).execute()
    
    deck_url = f"https://docs.google.com/presentation/d/{pres_id}/edit"
    return deck_url

def save_records(records: list):

    """
    Saves new records directly to your Google Sheet (Prospecting Leads) via the service account,
    with an automatic fallback to the local CSV file.
    """
    if not records:
        return

    df = pd.DataFrame(records)
    creds_file = CONFIG.get("GOOGLE_SHEETS_CREDENTIALS_JSON", "")
    sheet_id = str(CONFIG.get("GOOGLE_SHEET_ID", "1GhaLCdHN9NGVQaNZGqp4ONHoCsEM9zCVyVapuWwkNFw")).strip()

    synced_to_sheets = False
    if GSPREAD_AVAILABLE and os.path.exists(creds_file):
        try:
            scope = [
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive",
            ]
            creds = ServiceAccountCredentials.from_json_keyfile_name(creds_file, scope)
            client = gspread.authorize(creds)

            # Open directly by key to prevent quota / search errors
            if sheet_id:
                spreadsheet = client.open_by_key(sheet_id)
            else:
                spreadsheet = client.open(CONFIG["GOOGLE_SHEET_NAME"])

            sheet = spreadsheet.sheet1

            # Check if header row exists; if empty, add columns first
            existing_values = sheet.get_all_values()
            if not existing_values:
                sheet.append_row(list(df.columns))

            # Convert NaN / None to empty strings and append rows
            clean_rows = df.fillna("").astype(str).values.tolist()
            sheet.append_rows(clean_rows)

            print(f"[GOOGLE SHEETS] Successfully synced {len(records)} record(s) to '{spreadsheet.title}'.")
            synced_to_sheets = True

        except Exception as e:
            print(f"[Google Sheets Fallback Triggered]: {e}")

    # Also log to local CSV as a backup guarantee
    csv_file = CONFIG.get("FALLBACK_LOCAL_CSV", "prospecting_leads.csv")
    file_exists = os.path.exists(csv_file)
    df.to_csv(csv_file, mode="a", header=not file_exists, index=False)
    if not synced_to_sheets:
        print(f"[LOCAL CSV] Saved {len(records)} record(s) to '{csv_file}'.")
def send_email(to_email: str, subject: str, body: str, attachment_path: str = None):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = CONFIG["SENDER_EMAIL"]
    msg["To"] = to_email
    msg.set_content(body)
    if attachment_path and os.path.exists(attachment_path):
        with open(attachment_path, "rb") as f:
            data = f.read()
            name = os.path.basename(attachment_path)
        if attachment_path.endswith(".pdf"):
            msg.add_attachment(data, maintype="application", subtype="pdf", filename=name)
        elif attachment_path.endswith(".mp4"):
            msg.add_attachment(data, maintype="video", subtype="mp4", filename=name)

    with smtplib.SMTP_SSL(CONFIG["SMTP_SERVER"], CONFIG["SMTP_PORT"]) as server:
        server.login(CONFIG["SENDER_EMAIL"], CONFIG["SENDER_PASSWORD"])
        server.send_message(msg)

# ==============================================================================
# 6. PIPELINE CONTROLLER
# ==============================================================================
def main():
    print("=" * 70)
    print("   B2B PROSPECT AUDIT & 10-SLIDE DECK ENGINE (ALLINONE.PY)")
    print("=" * 70)

    # 1. Output Format Selection
    print("\n[Step 1] Select Deliverable Output Format:")
    print("  [1] MP4 Video Presentation (12 Slides + Voiceover)")
    print("  [2] PDF Slide Deck (12 Visual Diagnostic & GTM Slides)")
    print("  [3] Data Only (Direct to Google Sheets / CSV)")
    print("  [4] Native Google Slides Deck (Saves to Drive/Docs)")
    print("  [5] Single-Page Executive Scorecard (Print-Ready PDF Report)")
    output_choice = input("Select Output [1-5, Default: 1]: ").strip() or "1"
    
    create_video = (output_choice == "1")
    create_pdf = (output_choice == "2")
    create_google_slides = (output_choice == "4")
    create_scorecard = (output_choice == "5")

    # 2. Intelligence Level Selection
    print("\n[Step 2] Select Prospect Intelligence Level:")
    print("  [1] FAST     - 1 competitor; minimal data collection")
    print("  [2] STANDARD - 3 competitors; deeper comparison")
    print("  [3] DEEP     - up to 5 competitors; expanded analysis")
    intelligence_choice = input("Select Intelligence [1/2/3, Default: 1]: ").strip() or "1"
    CONFIG["INTELLIGENCE_LEVEL"] = {"1": "FAST", "2": "STANDARD", "3": "DEEP"}.get(intelligence_choice, "FAST")
    print(f"  -> Intelligence level: {CONFIG['INTELLIGENCE_LEVEL']}")

    # 3. Voiceover Engine Selection
    if create_video:
        print("\n[Step 2] Select Voiceover Engine:")
        print("  [1] Google TTS (Free Preview)")
        print("  [2] ElevenLabs (Production Executive Voice)")
        voice_choice = input("Select Audio Engine [1/2, Default: 1]: ").strip() or "1"
        CONFIG["TTS_ENGINE"] = "elevenlabs" if voice_choice == "2" else "google"
        print(f"  -> Active Engine: {CONFIG['TTS_ENGINE'].upper()}")

    # 4. Discovery Mode Selection
    print("\n[Step 3] Select Prospect Mode:")
    print("  [1] Automated Batch Discovery (via Google Places)")
    print("  [2] Single Prospect by Website URL")
    run_mode = input("Select Mode [1/2, Default: 1]: ").strip() or "1"

    leads = []
    category, location = "", ""

    if run_mode == "2":
        single_url = input("\nEnter Prospect Website URL: ").strip()
        if not single_url.startswith("http"):
            single_url = "https://" + single_url
        domain = extract_clean_domain(single_url)
        name_guess = domain.split(".")[0].replace("-", " ").title()
        p_name = input(f"Enter Prospect Name [Default: '{name_guess}']: ").strip() or name_guess
        location = input("Enter City/Market (e.g. Estero FL, Denver CO): ").strip() or "Local Market"
        category = input("Enter Business Vertical (e.g. HVAC, Optometrist): ").strip() or "Business"
        leads = [{"name": p_name, "website": single_url, "address": location, "rating": 0, "review_count": 0, "editorial_summary": "None", "primary_type": category.lower(), "types": [], "phone": "Not Listed"}]
    else:
        category = input("\nEnter Target Vertical (e.g. Optometrist, HVAC): ").strip() or "Optometrist"
        location = input("Enter Target Market (e.g. Estero FL, Naples FL): ").strip() or "Estero FL"
        count_input = input("Number of Leads to Process [Default: 1, Max: 20]: ").strip() or "1"
        try:
            limit = max(1, min(int(count_input), 20))
        except ValueError:
            limit = 1
        print(f"\nSearching up to {limit} leads for '{category}' in '{location}'...")
        leads = find_businesses(category, location, limit=limit)

    if not leads:
        print("[FAIL] No prospects retrieved.")
        return

    records = []

    for lead in leads:
        name = lead["name"]
        website = lead["website"]
        clean_name = re.sub(r'[^a-zA-Z0-9]', '', name)
        print(f"\n>>> Processing: {name} ({website})")

        print("  [1/5] Scraping technical footprint & marketing stack...")
        footprint = scrape_site_footprint(website)

        print("  [2/5] Identifying executive decision-maker...")
        contact = find_decision_maker(website, footprint["email"])
        print(f"        Contact: {contact['name']} ({contact['title']}) | {contact['email']}")

        print("        Benchmarking local market competitor...")
        rival = find_benchmark_competitor(category, location, name)
        rival_fp = scrape_site_footprint_cached(rival.get("website", ""), "competitor")
        print(f"        Benchmark Rival: {rival['name']} ({rival.get('rating')} stars)")

        print(f"  [3/5] Building {CONFIG['INTELLIGENCE_LEVEL']} competitive/search intelligence...")
        intelligence = collect_competitive_intelligence(
            lead, footprint, category, location,
            primary_rival=rival, primary_rival_fp=rival_fp
        )
        strategy_packet = compact_strategy_packet(
            lead, footprint, rival, rival_fp, intelligence
        )
        print(f"        Opportunity Score: {intelligence['overall_opportunity_score']}/100")
        print(f"        Search Opportunity: {intelligence['search_opportunity_score']}/100")
        print(f"        Local Search: {intelligence['local_search']['score']}/100")
        print(f"        Recommended Services: {', '.join(intelligence['recommended_services'][:4])}")

        shot_path, logo_path = None, None
        if (create_video or create_pdf or create_google_slides or create_scorecard) and CONFIG.get("CAPTURE_SCREENSHOT", True):
            print("  [4/5] Capturing logo & viewport screenshot via Playwright...")
            pw_assets = capture_site_assets_playwright(website)
            shot_path = pw_assets["screenshot_path"]
            logo_path = pw_assets["logo_path"]

        print("  [5/5] Generating Scorecard via LLM...")
        audit = generate_audit(
            lead, footprint, contact,
            rival=rival, rival_fp=rival_fp,
            strategy_packet=strategy_packet
        )

        if audit.get("strategy"):
            print(f"        LLM Strategic Angle: {audit['strategy'].get('outreach_angle', 'N/A')}")

        # Asset Assembly
        generated_asset = "N/A (Data Only)"
        if create_video:
            out_video = str(CONFIG["OUTPUT_DIR"] / f"{clean_name}_audit_brief.mp4")
            print(f"        Rendering 12-slide MP4 video to: {out_video}")
            assemble_video(lead, footprint, contact, audit, rival, rival_fp, out_video, logo_path=logo_path, shot_path=shot_path)
            generated_asset = out_video
        elif create_pdf:
            out_pdf = str(CONFIG["OUTPUT_DIR"] / f"{clean_name}_audit_deck.pdf")
            print(f"        Rendering 12-slide PDF presentation to: {out_pdf}")
            assemble_pdf(lead, footprint, contact, audit, rival, rival_fp, out_pdf, logo_path=logo_path, shot_path=shot_path)
            generated_asset = out_pdf
        elif create_google_slides:
            print("        Updating Google Slides presentation...")
            generated_asset = assemble_pitch_google_slides(name, audit)
        elif create_scorecard:
            out_scorecard = str(CONFIG["OUTPUT_DIR"] / f"{clean_name}_diagnostic_scorecard.pdf")
            print(f"        Rendering Single-Page Executive Scorecard to: {out_scorecard}")
            render_single_page_scorecard(lead, footprint, contact, rival, rival_fp, audit, shot_path, out_scorecard)
            generated_asset = out_scorecard

        # Email Delivery Prompt
        email_recipient = contact["email"]
        delivery_status = "Skipped"
        if email_recipient != "Not Listed" and "@" in email_recipient:
            send_opt = input(f"Send outreach email to {email_recipient}? [y/n, Default: n]: ").strip().lower()
            if send_opt == "y":
                try:
                    send_email(email_recipient, audit["email_subject"], audit["email_body"], generated_asset if (create_video or create_pdf) else None)
                    delivery_status = "Sent"
                    print("        Outreach email sent.")
                except Exception as e:
                    delivery_status = f"Failed ({e})"
                    print(f"        Email error: {e}")

        # Compute cost tracking values for row logging
        p_tokens = TOKEN_STATS["prompt_tokens"]
        c_tokens = TOKEN_STATS["completion_tokens"]
        commercial_equiv = ((p_tokens / 1_000_000) * 0.40) + ((c_tokens / 1_000_000) * 1.20)

        # 13+ Column Extended Record
        current_record = {
            "Business Name": name,
            "Address": lead.get("address", location),
            "Phone": lead.get("phone", "Not Listed"),
            "Website": website,
            "Decision Maker": contact["name"],
            "Title": contact["title"],
            "Contact Email": email_recipient,
            "Editorial Summary": lead.get("editorial_summary", "None"),
            "Primary Vertical": lead.get("primary_type", category),
            "Competitor Benchmark": rival["name"] if rival else "None",
            "Competitor Reviews": f"{rival.get('rating', 0)}★ ({rival.get('review_count', 0)})" if rival else "N/A",
            "Competitor Speed": f"{rival_fp.get('load_speed_sec', 0)}s" if rival_fp else "N/A",
            "Competitor Gap Margin": audit.get("competitor_gap_margin", "N/A"),
            "Intelligence Level": intelligence.get("intelligence_level", "FAST"),
            "Overall Opportunity Score": intelligence.get("overall_opportunity_score", 0),
            "Search Opportunity Score": intelligence.get("search_opportunity_score", 0),
            "Competitive Opportunity Score": intelligence.get("competitive_opportunity_score", 0),
            "Local Search Opportunity Score": intelligence.get("local_search", {}).get("score", 0),
            "Conversion Opportunity Score": intelligence.get("conversion_opportunity_score", 0),
            "Technical Gap Score": intelligence.get("technical_gap_score", 0),
            "Top Keyword Opportunity": ", ".join(
                [x["keyword"] for x in intelligence.get("keyword_opportunities", {}).get("top_terms", [])[:3]]
            ),
            "Search Intent": intelligence.get("search_intent", {}).get("primary", ""),
            "Recommended Services": ", ".join(intelligence.get("recommended_services", [])[:5]),
            "Competitive Weaknesses": " | ".join(intelligence.get("competitive_comparison", {}).get("observed_gaps", [])[:4]),
            "Strategy Confidence": json.dumps(intelligence.get("confidence", {}), separators=(",", ":")),
            "SEO Score": audit["scores"].get("seo", 0),
            "Website Speed Score": audit["scores"].get("website_speed", 0),
            "Content Clarity Score": audit["scores"].get("content_clarity", 0),
            "Lead Conversion Score": audit["scores"].get("lead_conversion", 0),
            "Reputation Score": audit["scores"].get("reputation", 0),
            "Mobile Conversion Readiness": audit["scores"].get("mobile_conversion_readiness", 0),
            "Directory NAP Consistency": audit["scores"].get("directory_nap_consistency", 0),
            "Pipeline Leakage Index": audit["scores"].get("pipeline_leakage_index", 0),
            "Core Weakness": audit.get("core_weakness", ""),
            "Priority Quick Win": audit.get("quick_win", ""),
            "Proposed Solution": audit.get("solution", ""),
            "Has Lead Form": footprint.get("has_lead_form", False),
            "Has Click-to-Call": footprint.get("has_click_to_call", False),
            "Has SSL": footprint.get("has_ssl", False),
            "Has Schema JSON-LD": footprint.get("has_schema", False),
            "Has GA4": footprint.get("has_ga4", False),
            "Has GTM": footprint.get("has_gtm", False),
            "Has Meta Pixel": footprint.get("has_meta_pixel", False),
            "CMS / Framework": footprint.get("cms_framework", "Custom"),
            "Booking Embed": footprint.get("booking_platform", "None"),
            "Live Chat": footprint.get("chat_platform", "None"),
            "Images Missing Alt": f"{footprint.get('images_missing_alt', 0)}/{footprint.get('total_images', 0)}",
            "Total Tokens Used": TOKEN_STATS["total_tokens"],
            "Commercial Cost Benchmark": f"${commercial_equiv:.4f}",
            "Asset Path": generated_asset,
            "Email Status": delivery_status
        }
        records.append(current_record)

        # IMMEDIATELY write record to Google Sheet as soon as this lead finishes
        print("\n  [Syncing] Writing lead record to Google Sheets...")
        try:
            save_records(records)
        except Exception as err:
            print(f"  [Sync Warning] Failed immediate save: {err}")

    # Save reusable competitor intelligence so repeated competitors cost less next run
    save_intelligence_cache()
    print("\n[COMPLETE] Run finished successfully.")

    # Print Token and Run Cost Report
    print_usage_and_cost_summary(len(records))


if __name__ == "__main__":
    main()
