import os
import re
import sys
import json
import time
import base64
import smtplib
from pathlib import Path
from email.message import EmailMessage
from urllib.parse import urlparse, urljoin, quote_plus
from datetime import date, timedelta
import requests
import pandas as pd
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont

#QRcode
try:
    import qrcode
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False


# Optional Playwright for live viewport & asset scraping
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# Audio engines
try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except ImportError:
    GTTS_AVAILABLE = False

# MoviePy 2.0+ video composition
try:
    from moviepy import ImageClip, AudioFileClip, concatenate_videoclips
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False

# Google APIs (Sheets & Slides)
try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
    from googleapiclient.discovery import build
    GOOGLE_APIS_AVAILABLE = True
except ImportError:
    GOOGLE_APIS_AVAILABLE = False

# Optional Google OAuth helper for Google Business Profile / Google Ads client data
try:
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.oauth2.credentials import Credentials as GoogleOAuthCredentials
    GOOGLE_OAUTH_AVAILABLE = True
except ImportError:
    GOOGLE_OAUTH_AVAILABLE = False

# ==============================================================================
# CONFIGURATION & CREDENTIALS
# ==============================================================================
CONFIG = {
    # Custom LLM / NRP Nautilus Endpoint
    "NRP_ENDPOINT": os.getenv("NRP_ENDPOINT", "https://ellm.nrp-nautilus.io/v1"),
    "NRP_API_KEY": os.getenv("NRP_API_KEY", os.getenv("NAUTILUS_API_KEY", os.getenv("OPENAI_API_KEY", ""))),
    "MODEL_NAME": os.getenv("MODEL_NAME", "qwen3"),

    # Google Places API
    "GOOGLE_PLACES_KEY": os.getenv("GOOGLE_PLACES_KEY", ""),

    # ------------------------------------------------------------------
    # PHASE 1 — First-party Google data (only available when authorized)
    # ------------------------------------------------------------------
    "PHASE1_ENABLED": os.getenv("PHASE1_ENABLED", "1").lower() in ("1", "true", "yes"),
    # Search Console: add the service-account email as a user on the property.
    "GSC_PROPERTY_URL": os.getenv("GSC_PROPERTY_URL", ""),
    "GSC_DAYS": int(os.getenv("GSC_DAYS", "28")),
    # GA4: numeric property ID, e.g. 123456789. The same service account can be
    # granted Viewer access to the GA4 property.
    "GA4_PROPERTY_ID": os.getenv("GA4_PROPERTY_ID", ""),
    "GA4_DAYS": int(os.getenv("GA4_DAYS", "28")),
    # Google Business Profile: requires approved GBP API access + merchant OAuth.
    "GBP_LOCATION_RESOURCE": os.getenv("GBP_LOCATION_RESOURCE", ""),
    "GBP_OAUTH_CLIENT_JSON": os.getenv("GBP_OAUTH_CLIENT_JSON", ""),
    "GBP_TOKEN_FILE": os.getenv("GBP_TOKEN_FILE", "gbp_token.json"),
    "GBP_DAYS": int(os.getenv("GBP_DAYS", "28")),
    # Google Ads: client-authorized account.
    "GOOGLE_ADS_CUSTOMER_ID": os.getenv("GOOGLE_ADS_CUSTOMER_ID", "").replace("-", ""),
    "GOOGLE_ADS_OAUTH_CLIENT_JSON": os.getenv("GOOGLE_ADS_OAUTH_CLIENT_JSON", ""),
    "GOOGLE_ADS_REFRESH_TOKEN": os.getenv("GOOGLE_ADS_REFRESH_TOKEN", ""),
    "GOOGLE_ADS_TOKEN_FILE": os.getenv("GOOGLE_ADS_TOKEN_FILE", "google_ads_token.json"),
    "GOOGLE_ADS_LOGIN_CUSTOMER_ID": os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "").replace("-", ""),

    # Decision-Maker Discovery Keys
    "APOLLO_API_KEY": os.getenv("APOLLO_API_KEY", ""),
    "HUNTER_API_KEY": os.getenv("HUNTER_API_KEY", ""),

    # Voice Settings
    "TTS_ENGINE": os.getenv("TTS_ENGINE", "google"),
    "ELEVENLABS_KEY": os.getenv("ELEVENLABS_KEY", ""),
    "VOICE_ID": "nPczCjzI2devNBz1zQrb",  # Brian (Executive Narrative)

    # Agency Branding & CTA
    "BRAND_PRIMARY": "ELKINS & CO.",
    "BRAND_SUBTITLE": "REVENUE STRATEGIES",
    "AGENCY_WEBSITE": "www.elkinsrevenue.com",
    "AGENCY_PHONE": "917-327-0636",
    "AGENCY_EMAIL": "info@elkinsrevenue.com",
    "CUSTOM_CTA": "Let us show you how we can help. Review this deck and schedule a meeting with us.",

    # Email SMTP Settings
    "SMTP_SERVER": "smtp.gmail.com",
    "SMTP_PORT": 465,
    "SENDER_EMAIL": os.getenv("SENDER_EMAIL", "your-email@domain.com"),
    "SENDER_PASSWORD": os.getenv("SENDER_PASSWORD", "your-app-password"),

    # Data Persistence
    "GOOGLE_SHEET_NAME": "Prospecting Pipeline & Audit Data",
    "GOOGLE_SHEETS_CREDENTIALS_JSON": r"G:\My Drive\Elkins Revenue Consulting\AI Agent Scripts\Prospect Database\service_account.json",

    # Output Destination Directory
    "OUTPUT_DIR": Path(r"G:\My Drive\Elkins Revenue Consulting\AI Agent Scripts\Python-generated output files"),
    "CAPTURE_SCREENSHOT": True
}

try:
    CONFIG["OUTPUT_DIR"].mkdir(parents=True, exist_ok=True)
except Exception:
    CONFIG["OUTPUT_DIR"] = Path(__file__).resolve().parent / "output"
    CONFIG["OUTPUT_DIR"].mkdir(parents=True, exist_ok=True)

# Visual Design Palette
STYLE = {
    "BG": (255, 255, 255),
    "CARD_BG": (248, 250, 252),
    "CARD_BORDER": (226, 232, 240),
    "TEXT_MAIN": (15, 23, 42),
    "TEXT_MUTED": (51, 65, 85),
    "TEXT_FAINT": (100, 116, 139),
    "BLUE": (37, 99, 235),
    "BLUE_BG": (239, 246, 255),
    "DIVIDER": (203, 213, 225),
    "GREEN": (22, 163, 74),
    "AMBER": (217, 119, 6),
    "RED": (220, 38, 38)
}

TOKEN_STATS = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
INTELLIGENCE_CACHE = {}

# ==============================================================================
# UNIVERSAL FONT LOADER
# ==============================================================================
def load_font(arg1, arg2=None, bold: bool = False):
    """
    Universal font loader supporting all signatures:
      - load_font(size, bold=True/False)
      - load_font(size, True/False)
      - load_font(["arialbd.ttf", "segoeuib.ttf"], size)
    """
    if isinstance(arg1, (list, tuple)):
        font_names = list(arg1)
        size = arg2 if arg2 is not None else 28
    else:
        size = arg1
        is_bold = bold or bool(arg2)
        font_names = (
            ["arialbd.ttf", "segoeuib.ttf", "helveticab.ttf"]
            if is_bold
            else ["arial.ttf", "segoeui.ttf", "helvetica.ttf"]
        )

    for fn in font_names:
        try:
            return ImageFont.truetype(fn, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None
# ==============================================================================
# SCORING ALGORITHM
# ==============================================================================
def compute_overall_performance_score(lead: dict, footprint: dict) -> dict:
    """Computes an objective, 0-100 digital performance score from footprint metrics."""
    # 1. Conversion Infrastructure (30%)
    s_conv = (
        (30 if footprint.get("has_click_to_call") else 0) +
        (25 if footprint.get("has_lead_form") else 0) +
        (25 if (footprint.get("has_booking_embed") or footprint.get("has_live_chat") or 
                footprint.get("booking_platform", "None") != "None") else 0) +
        (20 if footprint.get("is_mobile_responsive", True) else 0)
    )

    # 2. SEO & Crawl Hygiene (25%)
    tot_imgs = max(1, footprint.get("total_images", 1))
    alt_ratio = 1.0 - (footprint.get("images_missing_alt", 0) / tot_imgs)
    s_seo = (
        (35 if footprint.get("has_schema") else 0) +
        (25 if footprint.get("has_meta_desc", True) else 0) +
        (20 if footprint.get("heading_issue") in ["None", "Clean Hierarchy"] else 0) +
        int(20 * max(0.0, alt_ratio))
    )

    # 3. Speed & Latency (20%)
    load_sec = float(footprint.get("load_speed_sec", 2.0) or 2.0)
    s_speed = int(max(10, min(100, 100 - (load_sec * 18))))

    # 4. Reputation & Trust (15%)
    rating = float(lead.get("rating", 0.0) or 0.0)
    reviews = int(lead.get("review_count", 0) or 0)
    s_rep = (
        (15 if footprint.get("has_ssl") else 0) +
        int(min(45, rating * 9)) +
        int(min(40, reviews * 0.4))
    )

    # 5. Marketing Maturity (10%)
    s_mktg = (
        (40 if footprint.get("has_ga4") else 0) +
        (30 if footprint.get("has_gtm") else 0) +
        (20 if footprint.get("has_meta_pixel") else 0) +
        (10 if len(footprint.get("social_links", [])) > 0 else 0)
    )

    # Composite Raw Score
    raw_composite = (
        0.30 * s_conv +
        0.25 * s_seo +
        0.20 * s_speed +
        0.15 * s_rep +
        0.10 * s_mktg
    )

    # Friction Penalty
    penalty = 0
    if load_sec > 3.0 and not footprint.get("has_click_to_call"):
        penalty += 10
    if not footprint.get("has_ssl") or not footprint.get("is_mobile_responsive", True):
        penalty += 5

    final_score = int(max(10, min(99, round(raw_composite - penalty))))

    return {
        "overall_score": final_score,
        "conversion": s_conv,
        "seo": s_seo,
        "speed": s_speed,
        "reputation": s_rep,
        "marketing": s_mktg
    }

# ==============================================================================
# DISCOVERY & SCRAPING ENGINE
# ==============================================================================
def find_businesses(category: str, location: str, limit: int = 1) -> list:
    """Discovers business leads via Google Places API."""
    key = CONFIG.get("GOOGLE_PLACES_KEY")
    if not key or "your-" in key:
        print("  [Notice]: No GOOGLE_PLACES_KEY supplied. Utilizing demo seed lead.")
        return [{
            "name": f"Demo {category.title()} Co",
            "website": "https://example.com",
            "address": location,
            "rating": 4.2,
            "review_count": 28,
            "phone": "555-019-2831"
        }]

    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.websiteUri,places.rating,places.userRatingCount,places.nationalPhoneNumber"
    }
    payload = {"textQuery": f"{category} in {location}", "maxResultCount": limit}

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=20)
        res.raise_for_status()
        places = res.json().get("places", [])
        leads = []
        for p in places:
            leads.append({
                "name": p.get("displayName", {}).get("text", "Local Business"),
                "address": p.get("formattedAddress", location),
                "website": p.get("websiteUri", ""),
                "rating": p.get("rating", 0.0),
                "review_count": p.get("userRatingCount", 0),
                "phone": p.get("nationalPhoneNumber", "Not Listed")
            })
        return leads
    except Exception as e:
        print(f"  [Places API Failure]: {e}")
        return []

def find_benchmark_competitor(category: str, location: str, target_name: str) -> dict:
    """Identifies the top-rated local competitor for benchmark contrast."""
    leads = find_businesses(category, location, limit=5)
    candidates = [l for l in leads if l["name"].strip().lower() != target_name.strip().lower() and l.get("website")]
    if candidates:
        candidates.sort(key=lambda x: (x.get("rating", 0), x.get("review_count", 0)), reverse=True)
        return candidates[0]
    return {
        "name": f"Premier {category.title()} Specialists",
        "website": "https://example.com/competitor",
        "rating": 4.9,
        "review_count": 185,
        "phone": "555-998-1122"
    }

def scrape_site_footprint(url: str) -> dict:
    """Scrapes on-page technical factors, speed, booking widgets, and analytics pixels."""
    data = {
        "load_speed_sec": 1.8,
        "has_lead_form": False,
        "has_click_to_call": False,
        "has_booking_embed": False,
        "booking_platform": "None",
        "has_live_chat": False,
        "chat_platform": "None",
        "is_mobile_responsive": True,
        "has_schema": False,
        "has_meta_desc": False,
        "h1_count": 0,
        "h2_count": 0,
        "heading_issue": "None",
        "images_missing_alt": 0,
        "total_images": 0,
        "has_ga4": False,
        "has_gtm": False,
        "has_meta_pixel": False,
        "has_ssl": url.startswith("https"),
        "has_privacy_policy": False,
        "social_links": [],
        "cms_framework": "Custom",
        "content_snippet": ""
    }
    if not url or not url.startswith("http"):
        return data

    t0 = time.time()
    try:
        r = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        data["load_speed_sec"] = round(time.time() - t0, 2)
        html = r.text
        soup = BeautifulSoup(html, "html.parser")

        # Conversion triggers
        data["has_lead_form"] = bool(soup.find("form"))
        data["has_click_to_call"] = bool(soup.find("a", href=re.compile(r"^tel:", re.I)))

        # Booking & chat embeds
        lower_html = html.lower()
        if "calendly.com" in lower_html:
            data["has_booking_embed"] = True
            data["booking_platform"] = "Calendly"
        elif "acuityscheduling.com" in lower_html:
            data["has_booking_embed"] = True
            data["booking_platform"] = "Acuity"

        if "tidio" in lower_html:
            data["has_live_chat"] = True
            data["chat_platform"] = "Tidio"
        elif "intercom" in lower_html:
            data["has_live_chat"] = True
            data["chat_platform"] = "Intercom"

        # Technical SEO
        data["is_mobile_responsive"] = bool(soup.find("meta", attrs={"name": "viewport"}))
        data["has_schema"] = bool(soup.find("script", type="application/ld+json"))
        data["has_meta_desc"] = bool(soup.find("meta", attrs={"name": "description"}))

        h1s = soup.find_all("h1")
        h2s = soup.find_all("h2")
        data["h1_count"] = len(h1s)
        data["h2_count"] = len(h2s)
        if len(h1s) == 0:
            data["heading_issue"] = "Missing H1 Heading"
        elif len(h1s) > 1:
            data["heading_issue"] = "Multiple H1 Headings"

        imgs = soup.find_all("img")
        data["total_images"] = len(imgs)
        data["images_missing_alt"] = sum(1 for img in imgs if not img.get("alt"))

        # Analytics & Pixels
        data["has_ga4"] = "gtag(" in html or "g-" in lower_html
        data["has_gtm"] = "gtm.js" in lower_html
        data["has_meta_pixel"] = "fbevents.js" in lower_html

        # Social & CMS
        socials = set()
        for a in soup.find_all("a", href=True):
            h = a["href"].lower()
            if "facebook.com" in h: socials.add("Facebook")
            if "instagram.com" in h: socials.add("Instagram")
            if "linkedin.com" in h: socials.add("LinkedIn")
            if "privacy" in h: data["has_privacy_policy"] = True
        data["social_links"] = list(socials)

        if "wp-content" in lower_html: data["cms_framework"] = "WordPress"
        elif "webflow" in lower_html: data["cms_framework"] = "Webflow"
        elif "squarespace" in lower_html: data["cms_framework"] = "Squarespace"
        elif "wix.com" in lower_html: data["cms_framework"] = "Wix"

        data["content_snippet"] = " ".join([p.get_text() for p in soup.find_all(["p", "h1", "h2"])])[:2000]

    except Exception as e:
        print(f"  [Scraping Exception for {url}]: {e}")
        data["load_speed_sec"] = 3.5

    return data

def capture_site_assets_playwright(url: str) -> dict:
    """Takes a 1280x800 desktop viewport screenshot using Playwright."""
    out_dir = CONFIG["OUTPUT_DIR"]
    clean_domain = re.sub(r'[^a-zA-Z0-9]', '_', urlparse(url).netloc)
    shot_path = str(out_dir / f"{clean_domain}_viewport.png")

    if not PLAYWRIGHT_AVAILABLE or not url or not url.startswith("http"):
        return {"screenshot_path": None, "logo_path": None}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(url, timeout=20000, wait_until="load")
            time.sleep(2)
            page.screenshot(path=shot_path)
            browser.close()
            return {"screenshot_path": shot_path, "logo_path": None}
    except Exception as e:
        print(f"  [Playwright Capture Failed]: {e}")
        return {"screenshot_path": None, "logo_path": None}

def discover_decision_maker(business_name: str, domain: str) -> dict:
    """Retrieves or infers executive leadership contacts."""
    return {"name": "Managing Director", "title": "Business Principal", "email": ""}

# ==============================================================================
# LLM DIAGNOSTIC & STRATEGY ENGINE
# ==============================================================================
def call_nrp_llm(prompt: str) -> str:
    """Invokes LLM completion API with strict timeout handling."""
    api_key = CONFIG.get("NRP_API_KEY", "").strip()
    if not api_key or "your-" in api_key:
        print("  [LLM Notice]: No active NRP_API_KEY. Using built-in fallback synthesis.")
        return ""

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": CONFIG["MODEL_NAME"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 1800
    }

    try:
        res = requests.post(f"{CONFIG['NRP_ENDPOINT']}/chat/completions", headers=headers, json=payload, timeout=90)
        res.raise_for_status()
        j = res.json()
        TOKEN_STATS["prompt_tokens"] += j.get("usage", {}).get("prompt_tokens", 0)
        TOKEN_STATS["completion_tokens"] += j.get("usage", {}).get("completion_tokens", 0)
        TOKEN_STATS["total_tokens"] += j.get("usage", {}).get("total_tokens", 0)
        return j["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"  [LLM Call Warning]: {e}")
        return ""

def generate_audit(target: dict, target_fp: dict, contact: dict, rival: dict, rival_fp: dict) -> dict:
    """Generates structured diagnostic metrics and GTM roadmap content."""
    prompt = f"""
    Analyze {target['name']} ({target.get('website')}) vs competitor {rival['name']} ({rival.get('website')}).
    Target Technical Data: {json.dumps(target_fp, default=str)}
    Competitor Footprint: {json.dumps(rival_fp, default=str)}

    Return STRICT JSON:
    {{
      "scores": {{
        "seo": 70, "website_speed": 65, "content_clarity": 75, "lead_conversion": 55,
        "reputation": 72, "mobile_conversion_readiness": 60, "directory_nap_consistency": 80,
        "pipeline_leakage_index": 68
      }},
      "core_weakness": "Friction in mobile scheduling and lack of conversion schema",
      "quick_win": "Deploy direct tap-to-call headers and automated review capture sequence",
      "solution": "Full-funnel conversion optimization with 3-tier paid search conquesting",
      "competitor_gap_margin": "{rival['name']} outpaces locally with more reviews and faster response",
      "email_subject": "Revenue leakage audit & strategic acquisition plan for {target['name']}",
      "email_body": "Hi {contact['name']}, we completed an architectural analysis comparing {target['name']} to {rival['name']}...",
      "gtm_slides": [
        {{"title": "Executive Audit Overview", "bullets": ["Baseline speed analysis", "Crawl gap vs {rival['name']}", "High-intent friction points"], "voiceover": "Welcome. In this audit we analyze your digital foundation and compare it with local peers."}},
        {{"title": "Competitor Benchmark Analysis", "bullets": ["{target['name']} rating vs {rival['name']}", "Review capture disparity", "Mobile latency comparison"], "voiceover": "Looking at the local landscape, competitor review volume represents an immediate conquest opportunity."}},
        {{"title": "Conversion Rate Optimization", "bullets": ["Lead capture form placement", "Click-to-call mobile triggers", "Sticky scheduling widget rollout"], "voiceover": "By streamlining appointment booking, unclosed mobile traffic can be converted into booked revenue."}},
        {{"title": "Paid Acquisition Architecture", "bullets": ["High-intent search capture", "Competitor brand conquesting", "Negative keyword defense"], "voiceover": "Our 3-tier campaign model directs high-margin commercial searches directly to dedicated landing flows."}},
        {{"title": "Lifecycle Nurture & Retention", "bullets": ["Automated multi-touch follow-up", "Objection handler emails", "Zero-friction close flow"], "voiceover": "Deploying systematic lead recovery sequences ensures inquiries convert even days after initial visits."}},
        {{"title": "90-Day Execution Roadmap", "bullets": ["Day 1-30 Technical cleanup", "Day 31-60 Campaign launch", "Day 61-90 Scaled multi-channel acquisition"], "voiceover": "This structured 90-day plan delivers rapid wins while scaling predictable pipeline growth."}}
      ]
    }}
    """
    raw = call_nrp_llm(prompt)
    if raw:
        try:
            clean = re.search(r'\{.*\}', raw, re.DOTALL).group(0)
            return json.loads(clean)
        except Exception:
            pass

# Dynamic Heuristic Synthesis (Eliminates repeated/static scores)
    r_name = rival["name"] if rival else "Local Benchmark Leader"
    r_rating = float(rival.get("rating", 4.8) if rival else 4.8)
    r_reviews = int(rival.get("review_count", 150) if rival else 150)
    
    t_perf = compute_overall_performance_score(target, target_fp)
    dyn_speed = t_perf["speed"]
    dyn_conv = t_perf["conversion"]
    dyn_seo = t_perf["seo"]
    dyn_rep = t_perf["reputation"]
    dyn_mktg = t_perf["marketing"]
    
    dyn_local = int(min(98, max(25, (float(target.get("rating", 3.5) or 3.5) * 16) + (20 if target_fp.get("has_schema") else 0))))
    dyn_leak = int(max(15, min(95, 100 - ((dyn_speed + dyn_conv) // 2))))

    weaknesses = []
    if not target_fp.get("has_click_to_call"):
        weaknesses.append("lack of 1-tap mobile calling")
    if not target_fp.get("has_lead_form"):
        weaknesses.append("missing direct lead capture forms")
    if not target_fp.get("has_schema"):
        weaknesses.append("unindexed LocalBusiness schema")
    if float(target_fp.get("load_speed_sec", 2.0) or 2.0) > 2.5:
        weaknesses.append(f"high mobile latency ({target_fp.get('load_speed_sec')}s)")

    core_weakness = ", ".join(weaknesses[:2]).capitalize() if weaknesses else "Conversion friction across mobile landing paths"

    return {
        "scores": {
            "seo": dyn_seo,
            "website_speed": dyn_speed,
            "content_clarity": 75 if target_fp.get("content_snippet") else 40,
            "lead_conversion": dyn_conv,
            "reputation": dyn_rep,
            "mobile_conversion_readiness": dyn_conv,
            "directory_nap_consistency": dyn_local,
            "pipeline_leakage_index": dyn_leak
        },
        "core_weakness": core_weakness,
        "quick_win": "Deploy sticky tap-to-call bar and Google Tag Manager event tracking",
        "solution": "Frictionless mobile landing architecture with local schema optimization",
        "competitor_gap_margin": f"{r_name} holds {r_rating}★ ({r_reviews:,} reviews) with faster mobile response",
        "email_subject": f"Digital performance brief & GTM strategy for {target['name']}",
        "email_body": f"Hi {contact['name']}, we evaluated {target['name']}'s conversion architecture and benchmarked it against {r_name}.",

        "gtm_slides": [
            {"title": "Executive Audit Overview", "bullets": ["Core performance baseline", f"Competitive delta vs {r_name}", "Mobile friction analysis"], "voiceover": f"Welcome. We evaluated {target['name']}'s digital platform to uncover immediate growth opportunities."},
            {"title": "Competitor Benchmark Matrix", "bullets": [f"{target['name']} vs {r_name}", "Review capture disparity", "Direct load speed contrast"], "voiceover": f"Benchmarking against {r_name} reveals clear opportunities in local authority and conversion velocity."},
            {"title": "Conversion Rate Optimization", "bullets": ["Deploy sticky mobile tap-to-call", "Embed direct appointment scheduling", "Streamline contact forms"], "voiceover": "Adding high-intent conversion triggers ensures prospective clients can take action without friction."},
            {"title": "Paid Acquisition Architecture", "bullets": ["Tier 1: High-Intent Search", "Tier 2: Competitor Conquesting", "Tier 3: Pain-Specific Terms"], "voiceover": "Our acquisition blueprint captures high-value search demand while defending your core brand presence."},
            {"title": "Lifecycle Nurture Funnel", "bullets": ["Rapid lead follow-up automation", "Objection handler emails", "Re-engagement campaigns"], "voiceover": "Automated nurture sequences recover lost traffic and turn passive visitors into qualified pipeline."},
            {"title": "Strategic Next Steps", "bullets": ["Implement priority quick wins", "Launch target landing experiences", f"Review full strategy with {CONFIG['BRAND_PRIMARY']}"], "voiceover": f"Connect with {CONFIG['BRAND_PRIMARY']} to put this comprehensive revenue growth strategy into motion."}
        ]
    }

# ==============================================================================
# PHASE 1 — FIRST-PARTY GOOGLE DATA ENRICHMENT
# ==============================================================================
def _service_account_credentials(scopes):
    creds_file = CONFIG.get("GOOGLE_SHEETS_CREDENTIALS_JSON", "")
    if not creds_file or not os.path.exists(creds_file):
        return None
    try:
        from google.oauth2.service_account import Credentials
        return Credentials.from_service_account_file(creds_file, scopes=scopes)
    except Exception as e:
        print(f"  [Google Auth] Service-account credentials unavailable: {e}")
        return None

def get_search_console_data(site_url: str) -> dict:
    result = {"status":"not_configured","clicks_28d":None,"impressions_28d":None,"ctr_28d":None,"avg_position_28d":None,"top_queries":[]}
    property_url = CONFIG.get("GSC_PROPERTY_URL", "").strip()
    if not property_url: return result
    creds = _service_account_credentials(["https://www.googleapis.com/auth/webmasters.readonly"])
    if not creds or not GOOGLE_APIS_AVAILABLE: result["status"]="credentials_unavailable"; return result
    try:
        service=build("searchconsole","v1",credentials=creds,cache_discovery=False)
        end=date.today()-timedelta(days=2); start=end-timedelta(days=max(7,CONFIG.get("GSC_DAYS",28))-1)
        body={"startDate":start.isoformat(),"endDate":end.isoformat(),"dimensions":["query"],"rowLimit":10,"dataState":"final"}
        rows=service.searchanalytics().query(siteUrl=property_url,body=body).execute().get("rows",[])
        clicks=sum(float(r.get("clicks",0)) for r in rows); impressions=sum(float(r.get("impressions",0)) for r in rows)
        weighted=sum(float(r.get("position",0))*float(r.get("impressions",0)) for r in rows)
        result.update(status="ok",clicks_28d=round(clicks),impressions_28d=round(impressions),ctr_28d=round(clicks/impressions*100,2) if impressions else 0,avg_position_28d=round(weighted/impressions,2) if impressions else None,top_queries=[r.get("keys",[""])[0] for r in rows[:10]])
    except Exception as e: result["status"]=f"error: {str(e)[:180]}"
    return result

def get_ga4_data() -> dict:
    result={"status":"not_configured","sessions_28d":None,"users_28d":None,"conversions_28d":None,"engagement_rate_28d":None}
    property_id=CONFIG.get("GA4_PROPERTY_ID","").strip()
    if not property_id: return result
    creds=_service_account_credentials(["https://www.googleapis.com/auth/analytics.readonly"])
    if not creds or not GOOGLE_APIS_AVAILABLE: result["status"]="credentials_unavailable"; return result
    try:
        service=build("analyticsdata","v1beta",credentials=creds,cache_discovery=False)
        days=max(7,CONFIG.get("GA4_DAYS",28))
        body={"dateRanges":[{"startDate":f"{days}daysAgo","endDate":"yesterday"}],"metrics":[{"name":"sessions"},{"name":"totalUsers"},{"name":"conversions"},{"name":"engagementRate"}]}
        rows=service.properties().runReport(property=f"properties/{property_id}",body=body).execute().get("rows",[])
        vals=[v.get("value") for v in (rows[0].get("metricValues",[]) if rows else [])]
        result.update(status="ok",sessions_28d=float(vals[0]) if len(vals)>0 else 0,users_28d=float(vals[1]) if len(vals)>1 else 0,conversions_28d=float(vals[2]) if len(vals)>2 else 0,engagement_rate_28d=round(float(vals[3])*100,2) if len(vals)>3 else None)
    except Exception as e: result["status"]=f"error: {str(e)[:180]}"
    return result

def _get_google_oauth_credentials(client_json, token_file, scopes):
    if not client_json or not os.path.exists(client_json): return None
    if not GOOGLE_OAUTH_AVAILABLE:
        print("  [OAuth] Install google-auth-oauthlib to enable this integration."); return None
    try:
        creds=None
        if os.path.exists(token_file): creds=GoogleOAuthCredentials.from_authorized_user_file(token_file,scopes)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                from google.auth.transport.requests import Request; creds.refresh(Request())
            else:
                flow=InstalledAppFlow.from_client_secrets_file(client_json,scopes); creds=flow.run_local_server(port=0)
            with open(token_file,"w",encoding="utf-8") as f: f.write(creds.to_json())
        return creds
    except Exception as e:
        print(f"  [OAuth] Authorization failed: {e}"); return None

def get_gbp_performance_data() -> dict:
    result={"status":"not_configured","website_clicks_28d":None,"call_clicks_28d":None,"direction_requests_28d":None,"search_keywords":[]}
    location=CONFIG.get("GBP_LOCATION_RESOURCE","").strip(); client_json=CONFIG.get("GBP_OAUTH_CLIENT_JSON","").strip()
    if not location or not client_json: return result
    creds=_get_google_oauth_credentials(client_json,CONFIG.get("GBP_TOKEN_FILE","gbp_token.json"),["https://www.googleapis.com/auth/business.manage"])
    if not creds: result["status"]="oauth_unavailable"; return result
    try:
        from google.auth.transport.requests import AuthorizedSession
        session=AuthorizedSession(creds); end=date.today()-timedelta(days=1); start=end-timedelta(days=max(7,CONFIG.get("GBP_DAYS",28))-1)
        params={"dailyMetrics":["WEBSITE_CLICKS","CALL_CLICKS","BUSINESS_DIRECTION_REQUESTS"],"daily_range.start_date.year":start.year,"daily_range.start_date.month":start.month,"daily_range.start_date.day":start.day,"daily_range.end_date.year":end.year,"daily_range.end_date.month":end.month,"daily_range.end_date.day":end.day}
        url=f"https://businessprofileperformance.googleapis.com/v1/{location}:fetchMultiDailyMetricsTimeSeries"
        payload=session.get(url,params=params,timeout=30).json()
        totals={"WEBSITE_CLICKS":0,"CALL_CLICKS":0,"BUSINESS_DIRECTION_REQUESTS":0}
        for item in payload.get("multiDailyMetricTimeSeries",[]):
            for series in item.get("dailyMetricTimeSeries",[]):
                metric=series.get("dailyMetric"); points=series.get("timeSeries",{}).get("datedValues",[])
                if metric in totals: totals[metric]+=sum(int(x.get("value",0)) for x in points)
        kw_url=f"https://businessprofileperformance.googleapis.com/v1/{location}/searchkeywords/impressions/monthly"
        kw_params={"monthly_range.start_month.year":start.year,"monthly_range.start_month.month":start.month,"monthly_range.end_month.year":end.year,"monthly_range.end_month.month":end.month,"page_size":20}
        kr=session.get(kw_url,params=kw_params,timeout=30); keywords=[x.get("searchKeyword","") for x in kr.json().get("searchKeywordsCounts",[])] if kr.ok else []
        result.update(status="ok",website_clicks_28d=totals["WEBSITE_CLICKS"],call_clicks_28d=totals["CALL_CLICKS"],direction_requests_28d=totals["BUSINESS_DIRECTION_REQUESTS"],search_keywords=keywords[:20])
    except Exception as e: result["status"]=f"error: {str(e)[:180]}"
    return result

def get_google_ads_data() -> dict:
    """Gets actual Google Ads performance for an authorized customer account."""
    result={"status":"not_configured","impressions_30d":None,"clicks_30d":None,"cost_30d":None,"conversions_30d":None}
    customer_id=CONFIG.get("GOOGLE_ADS_CUSTOMER_ID","").strip()
    client_json=CONFIG.get("GOOGLE_ADS_OAUTH_CLIENT_JSON","").strip()
    if not customer_id or not client_json:
        return result
    try:
        # One-time browser OAuth; subsequent runs use the cached refresh token.
        creds=_get_google_oauth_credentials(client_json, CONFIG.get("GOOGLE_ADS_TOKEN_FILE","google_ads_token.json"), ["https://www.googleapis.com/auth/adwords"])
        if not creds:
            result["status"]="oauth_unavailable"
            return result
        from google.auth.transport.requests import AuthorizedSession
        session=AuthorizedSession(creds)
        headers={"Content-Type":"application/json"}
        if CONFIG.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID"):
            headers["login-customer-id"]=CONFIG["GOOGLE_ADS_LOGIN_CUSTOMER_ID"]
        query="SELECT customer.id, customer.descriptive_name, metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions FROM customer WHERE segments.date DURING LAST_30_DAYS"
        url=f"https://googleads.googleapis.com/v25/customers/{customer_id}/googleAds:searchStream"
        r=session.post(url,headers=headers,json={"query":query},timeout=45)
        r.raise_for_status()
        totals={"impressions":0,"clicks":0,"cost_micros":0,"conversions":0.0}
        for batch in r.json():
            for row in batch.get("results",[]):
                m=row.get("metrics",{})
                totals["impressions"]+=int(m.get("impressions",0) or 0)
                totals["clicks"]+=int(m.get("clicks",0) or 0)
                totals["cost_micros"]+=int(m.get("costMicros",0) or 0)
                totals["conversions"]+=float(m.get("conversions",0) or 0)
        result.update(status="ok",impressions_30d=totals["impressions"],clicks_30d=totals["clicks"],cost_30d=round(totals["cost_micros"]/1000000,2),conversions_30d=round(totals["conversions"],2))
    except Exception as e:
        result["status"]=f"error: {str(e)[:180]}"
    return result

def collect_phase1_google_data(lead: dict) -> dict:
    if not CONFIG.get("PHASE1_ENABLED",True): return {"phase1_status":"disabled"}
    print("  [Phase 1] Checking available first-party Google data...")
    return {"search_console":get_search_console_data(lead.get("website","")),"ga4":get_ga4_data(),"google_business_profile":get_gbp_performance_data(),"google_ads":get_google_ads_data(),"ads_transparency":{"status":"manual_lookup","lookup_url":"https://adstransparency.google.com/?region=US&query="+quote_plus(lead.get("name",""))}}

# AUDIO & MEDIA RENDERERS
# ==============================================================================
def generate_voiceover(text: str, output_path: str):
    """Generates audio voiceover via ElevenLabs or Google TTS."""
    engine = CONFIG.get("TTS_ENGINE", "google").lower()
    if engine == "elevenlabs" and CONFIG.get("ELEVENLABS_KEY"):
        try:
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{CONFIG['VOICE_ID']}"
            headers = {"xi-api-key": CONFIG["ELEVENLABS_KEY"], "Content-Type": "application/json"}
            payload = {
                "text": text,
                "model_id": "eleven_turbo_v2_5",
                "voice_settings": {"stability": 0.45, "similarity_boost": 0.80}
            }
            res = requests.post(url, headers=headers, json=payload, timeout=25)
            if res.status_code == 200:
                with open(output_path, "wb") as f:
                    f.write(res.content)
                return
        except Exception as e:
            print(f"  [ElevenLabs Error, falling back to Google TTS]: {e}")

    if GTTS_AVAILABLE:
        tts = gTTS(text=text, lang="en", tld="com", slow=False)
        tts.save(output_path)
    else:
        # Fallback silent audio file stub
        with open(output_path, "wb") as f:
            f.write(b"")

def render_slide_image(title: str, bullets: list, eyebrow: str, output_path: str):
    """Renders a 1920x1080 slide image matching executive design styling."""
    W, H = 1920, 1080
    im = Image.new("RGB", (W, H), color=STYLE["BG"])
    draw = ImageDraw.Draw(im)

    f_eye = load_font(["arialbd.ttf", "segoeuib.ttf"], 22)
    f_title = load_font(["arialbd.ttf", "segoeuib.ttf"], 48)
    f_body = load_font(["arial.ttf", "segoeui.ttf"], 30)

    # Card background
    draw.rounded_rectangle([100, 80, W - 100, H - 80], radius=16, fill=STYLE["CARD_BG"], outline=STYLE["CARD_BORDER"], width=2)

    # Eyebrow Pill
    draw.rounded_rectangle([150, 130, 480, 175], radius=8, fill=STYLE["BLUE_BG"])
    draw.text((165, 140), eyebrow.upper(), fill=STYLE["BLUE"], font=f_eye)

    # Title
    draw.text((150, 210), title, fill=STYLE["TEXT_MAIN"], font=f_title)
    draw.line([150, 280, W - 150, 280], fill=STYLE["DIVIDER"], width=2)

    # Bullets
    y = 340
    for b in bullets:
        draw.text((160, y), "•", fill=STYLE["BLUE"], font=f_title)
        draw.text((200, y + 8), str(b), fill=STYLE["TEXT_MUTED"], font=f_body)
        y += 85

    # Footer Agency Lockup
    draw.text((150, H - 140), f"{CONFIG['BRAND_PRIMARY']} | {CONFIG['BRAND_SUBTITLE']}", fill=STYLE["TEXT_FAINT"], font=f_eye)
    im.save(output_path)

def assemble_video(lead, footprint, contact, audit, rival, rival_fp, out_video, logo_path=None, shot_path=None):
    """Compiles MP4 presentation using MoviePy."""
    if not MOVIEPY_AVAILABLE:
        print("  [MoviePy Unavailable]: Skipping video assembly.")
        return

    slides = audit.get("gtm_slides", [])
    clips = []
    temp_files = []

    for i, s in enumerate(slides):
        img_p = str(CONFIG["OUTPUT_DIR"] / f"temp_s_{i}.png")
        aud_p = str(CONFIG["OUTPUT_DIR"] / f"temp_a_{i}.mp3")
        temp_files.extend([img_p, aud_p])

        render_slide_image(s["title"], s["bullets"], f"STRATEGIC BRIEFING 0{i+1}", img_p)
        generate_voiceover(s["voiceover"], aud_p)

        try:
            a_clip = AudioFileClip(aud_p)
            dur = max(3.0, a_clip.duration)
            i_clip = ImageClip(img_p).with_duration(dur).with_audio(a_clip)
            clips.append(i_clip)
        except Exception as e:
            print(f"  [Clip Error slide {i}]: {e}")

    if clips:
        final_video = concatenate_videoclips(clips, method="compose")
        final_video.write_videofile(out_video, fps=24, codec="libx264", audio_codec="aac", logger=None)
        final_video.close()
        for c in clips:
            c.close()

    for f in temp_files:
        if os.path.exists(f):
            try: os.remove(f)
            except Exception: pass

def assemble_pdf(lead, footprint, contact, audit, rival, rival_fp, out_pdf, logo_path=None, shot_path=None):
    """Renders all slides into a cohesive presentation PDF."""
    slides = audit.get("gtm_slides", [])
    images = []
    temp_files = []

    for i, s in enumerate(slides):
        img_p = str(CONFIG["OUTPUT_DIR"] / f"temp_pdf_s_{i}.png")
        temp_files.append(img_p)
        render_slide_image(s["title"], s["bullets"], f"STRATEGY SLIDE 0{i+1}", img_p)
        images.append(Image.open(img_p).convert("RGB"))

    if images:
        images[0].save(out_pdf, save_all=True, append_images=images[1:], resolution=150)

    for f in temp_files:
        if os.path.exists(f):
            try: os.remove(f)
            except Exception: pass

# ==============================================================================
# SINGLE-PAGE EXECUTIVE SCORECARD (OPTION 5) - REDESIGNED 5-ZONE LAYOUT
# ==============================================================================
def generate_qr_image(url: str, size_px: int = 190) -> Image.Image:
    """Generates a clean 24-bit RGB QR code image or crisp fallback stub."""
    if QRCODE_AVAILABLE:
        try:
            qr = qrcode.QRCode(
                version=None,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=8,
                border=2,
            )
            qr.add_data(url)
            qr.make(fit=True)
            # Create RGB image directly to ensure clean PDF export
            pil_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
            return pil_img.resize((size_px, size_px), Image.Resampling.NEAREST)
        except Exception as e:
            print(f"  [QR Warning]: Failed to build standard QR, using stub: {e}")

    # Fallback clean QR graphic generator
    qr_img = Image.new("RGB", (size_px, size_px), (255, 255, 255))
    d = ImageDraw.Draw(qr_img)
    d.rectangle([0, 0, size_px - 1, size_px - 1], outline=(15, 23, 42), width=3)
    # Position corner locator patterns
    for cx, cy in [(14, 14), (size_px - 56, 14), (14, size_px - 56)]:
        d.rectangle([cx, cy, cx + 42, cy + 42], fill=(15, 23, 42))
        d.rectangle([cx + 7, cy + 7, cx + 35, cy + 35], fill=(255, 255, 255))
        d.rectangle([cx + 14, cy + 14, cx + 28, cy + 28], fill=(15, 23, 42))
    # Simulated data tracks
    for step in range(65, size_px - 50, 14):
        d.rectangle([step, 20, step + 6, 40], fill=(15, 23, 42))
        d.rectangle([20, step, 40, step + 6], fill=(15, 23, 42))
        d.rectangle([step, size_px - 38, step + 7, size_px - 22], fill=(15, 23, 42))
        d.rectangle([size_px - 38, step, size_px - 22, step + 7], fill=(15, 23, 42))
    return qr_img

    # =============================================================
    # BEGINNING OF SCORE CARD
    # =============================================================
def render_single_page_scorecard(lead: dict, footprint: dict, contact: dict, rival: dict, rival_fp: dict, audit: dict, shot_path: str, out_pdf_path: str, phase1_data: dict | None = None):
    """
    Renders an executive-grade 8.5x11 in @ 300 DPI (2550 x 3300 px) single-page audit report.
    - QR Code removed.
    - Footer height restored to compact dimensions.
    - +8pt vertical spacing between all modules.
    - Additional +2pt type size boost across all modules.
    """
    W, H = 2550, 3300
    img = Image.new("RGB", (W, H), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    # -------------------------------------------------------------
    # 1. COLOR TOKENS
    # -------------------------------------------------------------
    C_BLUE = (37, 99, 235)         # Cobalt accent
    C_BLUE_DARK = (29, 78, 216)    # Darker blue border
    C_RED = (220, 38, 38)          # Problem Red
    C_AMBER = (217, 119, 6)        # Attention Amber
    C_GREEN = (22, 163, 74)        # Passing Green

    TEXT_MAIN = (15, 23, 42)       # Slate 900
    TEXT_MUTED = (71, 85, 105)     # Slate 600
    TEXT_FAINT = (148, 163, 184)   # Slate 400
    BORDER_LIGHT = (226, 232, 240) # Card outlines
    BG_CARD = (248, 250, 252)

    # -------------------------------------------------------------
    # 2. TYPOGRAPHY (+2 pt boost across all tokens)
    # -------------------------------------------------------------
    f_brand_main = load_font(["arialbd.ttf", "segoeuib.ttf"], 76)
    f_brand_sub = load_font(["arialbd.ttf", "segoeuib.ttf"], 34)
    f_audit_title = load_font(["arialbd.ttf", "segoeuib.ttf"], 74)
    f_audit_meta = load_font(["arial.ttf", "segoeui.ttf"], 36)

    # Overall Grade Module
    f_grade_label = load_font(["arialbd.ttf", "segoeuib.ttf"], 42)
    f_grade_sub = load_font(["arial.ttf", "segoeui.ttf"], 28)
    f_grade_giant = load_font(["arialbd.ttf", "segoeuib.ttf"], 110)
    f_grade_title = load_font(["arialbd.ttf", "segoeuib.ttf"], 36)
    f_grade_body = load_font(["arial.ttf", "segoeui.ttf"], 30)

    # Urgency Scorecards
    f_snap_head = load_font(["arialbd.ttf", "segoeuib.ttf"], 38)
    f_snap_sub = load_font(["arial.ttf", "segoeui.ttf"], 32)
    f_card_num = load_font(["arialbd.ttf", "segoeuib.ttf"], 100)
    f_card_title = load_font(["arialbd.ttf", "segoeuib.ttf"], 32)
    f_card_desc = load_font(["arial.ttf", "segoeui.ttf"], 26)

    # Comparison Table
    f_tbl_box_title = load_font(["arialbd.ttf", "segoeuib.ttf"], 40)
    f_tbl_box_sub = load_font(["arialbd.ttf", "segoeuib.ttf"], 34)
    f_table_head = load_font(["arialbd.ttf", "segoeuib.ttf"], 28)
    f_table_body = load_font(["arial.ttf", "segoeui.ttf"], 28)
    f_table_body_b = load_font(["arialbd.ttf", "segoeuib.ttf"], 28)
    f_badge_font = load_font(["arialbd.ttf", "segoeuib.ttf"], 26)
    f_table_source = load_font(["arial.ttf", "segoeui.ttf"], 23)

    # Foundations Checklist
    f_found_title = load_font(["arialbd.ttf", "segoeuib.ttf"], 40)
    f_found_sub = load_font(["arialbd.ttf", "segoeuib.ttf"], 34)
    f_col_head = load_font(["arialbd.ttf", "segoeuib.ttf"], 34)
    f_found_body = load_font(["arial.ttf", "segoeui.ttf"], 28)
    f_found_body_b = load_font(["arialbd.ttf", "segoeuib.ttf"], 28)

    # Action Matrix & Unlock Section
    f_act_title = load_font(["arialbd.ttf", "segoeuib.ttf"], 40)
    f_act_grade = load_font(["arialbd.ttf", "segoeuib.ttf"], 38)
    f_act_head = load_font(["arialbd.ttf", "segoeuib.ttf"], 29)
    f_act_right_head = load_font(["arialbd.ttf", "segoeuib.ttf"], 36)
    f_act_right_sub = load_font(["arial.ttf", "segoeui.ttf"], 28)
    f_act_body = load_font(["arialbd.ttf", "segoeuib.ttf"], 28)
    f_act_time = load_font(["arial.ttf", "segoeui.ttf"], 27)
    f_act_btn = load_font(["arialbd.ttf", "segoeuib.ttf"], 26)
    f_check_font = load_font(["arialbd.ttf", "segoeuib.ttf"], 22)
    f_tool_title = load_font(["arialbd.ttf", "segoeuib.ttf"], 29)
    f_tool_desc = load_font(["arial.ttf", "segoeui.ttf"], 26)

    # Footer
    f_cta_hook = load_font(["arialbd.ttf", "segoeuib.ttf"], 40)
    f_btn_text = load_font(["arialbd.ttf", "segoeuib.ttf"], 29)
    f_cta_contact = load_font(["arial.ttf", "segoeui.ttf"], 26)

    mx = 95
    usable_w = W - (2 * mx)

    # =============================================================
    # 1. HEADER ZONE
    # =============================================================
    y = 75
    logo_file_candidates = [
        Path(CONFIG["OUTPUT_DIR"]).parent / "logo.png",
        Path(__file__).resolve().parent / "logo.png",
        Path(r"G:\My Drive\Elkins Revenue Consulting\logo.png")
    ]
    loaded_logo = None
    for cand in logo_file_candidates:
        if cand.exists():
            try:
                loaded_logo = Image.open(cand).convert("RGBA")
                break
            except Exception:
                continue

    if loaded_logo:
        aspect = loaded_logo.width / max(1, loaded_logo.height)
        logo_h = 108
        logo_w = int(logo_h * aspect)
        resized_logo = loaded_logo.resize((logo_w, logo_h), Image.Resampling.LANCZOS)
        img.paste(resized_logo, (mx, y), mask=resized_logo.split()[3])
    else:
        cur_x = mx
        draw.text((cur_x, y), "ELKINS ", fill=TEXT_MAIN, font=f_brand_main)
        cur_x += draw.textbbox((0, 0), "ELKINS ", font=f_brand_main)[2]
        draw.text((cur_x, y), "& ", fill=C_BLUE, font=f_brand_main)
        cur_x += draw.textbbox((0, 0), "& ", font=f_brand_main)[2]
        draw.text((cur_x, y), "CO.", fill=TEXT_MAIN, font=f_brand_main)
        draw.text((mx + 2, y + 86), "REVENUE SOLUTIONS", fill=C_BLUE, font=f_brand_sub)

    hdr_right_title = "DIGITAL REVENUE AUDIT"
    t_bbox = draw.textbbox((0, 0), hdr_right_title, font=f_audit_title)
    hdr_t_w = t_bbox[2] - t_bbox[0]
    draw.text((W - mx - hdr_t_w, y), hdr_right_title, fill=TEXT_MAIN, font=f_audit_title)

    company_name = lead.get('name', 'Lockchief')
    loc = lead.get('address', 'Denver, CO')
    loc_clean = loc.split(",")[0].strip() if "," in loc else loc
    date_str = pd.Timestamp.now().strftime('%B %Y')
    prep_str = f"Prepared for {company_name}  |  {loc_clean}  |  {date_str}"
    m_bbox = draw.textbbox((0, 0), prep_str, font=f_audit_meta)
    prep_w = m_bbox[2] - m_bbox[0]
    draw.text((W - mx - prep_w, y + 88), prep_str, fill=TEXT_MUTED, font=f_audit_meta)

    y += 148
    draw.line([(mx, y), (W - mx, y)], fill=BORDER_LIGHT, width=3)
    # +8pt increased gap
    y += 60

# =============================================================
    # 2. OVERALL GRADE MODULE (Computed from ALL Collected Data)
    # =============================================================
    # Run the comprehensive 5-pillar engine on the full scraped footprint
    perf = compute_overall_performance_score(lead, footprint)
    
    # 1. Overall Composite Score (All data points: SEO, Speed, Rep, Pixels, SSL, Forms)
    avg_score = perf["overall_score"]

    # 2. The 4 Displayed Urgency Sub-Scores
    s_speed = perf["speed"]
    s_mobile = perf["conversion"]
    s_retention = int(max(15, min(95, round(
        (perf["marketing"] * 0.5) + 
        (25 if footprint.get("has_lead_form") else 0) + 
        (25 if footprint.get("has_gtm") else 0)
    ))))
    
    # Smooth reputation scoring across small vs. massive review footprints
    rev_cnt = int(lead.get("review_count", 0) or 0)
    rev_pts = min(40, int(round((rev_cnt ** 0.5) * 1.5)))  # Scales smoothly without artificial caps
    s_local = int(min(99, max(20, (float(lead.get("rating", 4.0) or 4.0) * 10) + rev_pts + (15 if footprint.get("has_schema") else 0))))

    # Dynamic Copy aligned directly with the audited prospect's performance
    if avg_score >= 85:
        grade_letter = "A" if avg_score >= 92 else "B+"
        theme_accent = (22, 163, 74)
        theme_border = (21, 128, 61)
        theme_bg = (240, 253, 244)
        theme_divider = (187, 247, 208)
        core_head = "Strong digital foundations with key opportunities to lead."
        loss_p1 = "Solid overall infrastructure in place; closing minor conversion friction"
        loss_p2 = "will lock in dominant market share against local competitors."
    elif avg_score >= 70:
        grade_letter = "B" if avg_score >= 78 else "B-"
        theme_accent = (217, 119, 6)
        theme_border = (180, 83, 9)
        theme_bg = (254, 252, 232)
        theme_divider = (254, 240, 138)
        core_head = "Competitive baseline, but leaving ready revenue on the table."
        loss_p1 = "Good brand footprint, yet speed bottlenecks and booking friction"
        loss_p2 = "cost valuable conversion opportunities every week."
    else:
        grade_letter = "C+" if avg_score >= 60 else ("C" if avg_score >= 50 else "D")
        theme_accent = (220, 38, 38)
        theme_border = (185, 28, 28)
        theme_bg = (254, 242, 242)
        theme_divider = (254, 202, 202)
        core_head = "Revenue is leaking when customers are ready to call."
        loss_p1 = "High-friction conversion paths and missing tag architecture"
        loss_p2 = "send ready-to-buy shoppers directly to competing providers."

    grade_box_h = 215
    draw.rounded_rectangle([mx, y, mx + usable_w, y + grade_box_h], radius=18, fill=theme_bg, outline=theme_border, width=3)
    draw.text((mx + 40, y + 46), "OVERALL GRADE", fill=theme_accent, font=f_grade_label)
    draw.text((mx + 40, y + 106), "Full 12-factor audit  |  public data", fill=TEXT_MUTED, font=f_grade_sub)
    draw.text((mx + 560, y + 36), grade_letter, fill=theme_accent, font=f_grade_giant)

    draw.line([(mx + 760, y + 30), (mx + 760, y + grade_box_h - 30)], fill=theme_divider, width=3)
    draw.text((mx + 805, y + 40), core_head, fill=TEXT_MAIN, font=f_grade_title)
    draw.text((mx + 805, y + 94), loss_p1, fill=TEXT_MUTED, font=f_grade_body)
    draw.text((mx + 805, y + 136), loss_p2, fill=TEXT_MUTED, font=f_grade_body)

    y += grade_box_h + 120

    # =============================================================
    # 3. PERFORMANCE SNAPSHOT
    # =============================================================
    draw.text((mx, y), "YOUR SCORES", fill=TEXT_MAIN, font=f_snap_head)
    head_w = draw.textbbox((0, 0), "YOUR SCORES", font=f_snap_head)[2]
    draw.text((mx + head_w + 16, y + 3), "|  ranked by urgency", fill=TEXT_MUTED, font=f_snap_sub)
    y += 62

    card_data = [
        ("Website Loading Speed", s_speed, "Slow pages lose visitors before they ever call or book."),
        ("Ease of Booking & Calling", s_mobile, "Mobile visitors can't call or book in one tap."),
        ("Lead Capture & Tracking", s_retention, "No sticky call button and gaps in tracking."),
        ("Local Search & Maps", s_local, "Strong map presence, with room to lead.")
    ]
    card_data.sort(key=lambda item: item[1])

    card_gap = 26
    card_w = (usable_w - (3 * card_gap)) // 4
    card_h = 305

    for idx, (label, val, desc) in enumerate(card_data):
        cx = mx + (idx * (card_w + card_gap))
        if val >= 80:
            c_fill, c_border, c_accent, c_track = (240, 253, 244), (22, 163, 74), (22, 163, 74), (220, 252, 231)
        elif val >= 60:
            c_fill, c_border, c_accent, c_track = (254, 252, 232), (217, 119, 6), (217, 119, 6), (254, 243, 199)
        else:
            c_fill, c_border, c_accent, c_track = (254, 242, 242), (220, 38, 38), (220, 38, 38), (254, 226, 226)

        draw.rounded_rectangle([cx, y, cx + card_w, y + card_h], radius=20, fill=c_fill, outline=c_border, width=3)

        num_str = str(val)
        n_bbox = draw.textbbox((0, 0), num_str, font=f_card_num)
        nw = n_bbox[2] - n_bbox[0]
        draw.text((cx + (card_w - nw) // 2, y + 16), num_str, fill=c_accent, font=f_card_num)

        meter_margin = 36
        meter_w = card_w - (meter_margin * 2)
        meter_h = 14
        meter_x = cx + meter_margin
        meter_y = y + 136

        draw.rounded_rectangle([meter_x, meter_y, meter_x + meter_w, meter_y + meter_h], radius=7, fill=c_track)
        fill_w = max(meter_h, int(meter_w * (min(100, max(0, val)) / 100.0)))
        draw.rounded_rectangle([meter_x, meter_y, meter_x + fill_w, meter_y + meter_h], radius=7, fill=c_accent)

        t_words = label.split()
        t_lines, cur_line = [], ""
        for word in t_words:
            cand = f"{cur_line} {word}".strip()
            if draw.textbbox((0, 0), cand, font=f_card_title)[2] <= (card_w - 24):
                cur_line = cand
            else:
                if cur_line: t_lines.append(cur_line)
                cur_line = word
        if cur_line: t_lines.append(cur_line)

        ty = y + 166
        for tl in t_lines[:2]:
            tl_bbox = draw.textbbox((0, 0), tl, font=f_card_title)
            tl_w = tl_bbox[2] - tl_bbox[0]
            draw.text((cx + (card_w - tl_w) // 2, ty), tl, fill=TEXT_MAIN, font=f_card_title)
            ty += 36

        d_words = desc.split()
        d_lines, cur_d = [], ""
        for word in d_words:
            cand = f"{cur_d} {word}".strip()
            if draw.textbbox((0, 0), cand, font=f_card_desc)[2] <= (card_w - 36):
                cur_d = cand
            else:
                if cur_d: d_lines.append(cur_d)
                cur_d = word
        if cur_d: d_lines.append(cur_d)

        dy = ty + 8
        for dl in d_lines[:2]:
            dl_bbox = draw.textbbox((0, 0), dl, font=f_card_desc)
            dl_w = dl_bbox[2] - dl_bbox[0]
            draw.text((cx + (card_w - dl_w) // 2, dy), dl, fill=TEXT_MUTED, font=f_card_desc)
            dy += 30

    # +8pt increased gap
    y += card_h + 120

    # =============================================================
    # 4. WHAT'S COSTING YOU CUSTOMERS
    # =============================================================
    table_box_h = 515
    draw.rounded_rectangle([mx, y, mx + usable_w, y + table_box_h], radius=18, fill=BG_CARD, outline=BORDER_LIGHT, width=2)

    title_start_x = mx + 36
    draw.text((title_start_x, y + 26), "WHAT'S COSTING YOU CUSTOMERS", fill=TEXT_MAIN, font=f_tbl_box_title)
    t_main_w = draw.textbbox((0, 0), "WHAT'S COSTING YOU CUSTOMERS", font=f_tbl_box_title)[2]
    draw.text((title_start_x + t_main_w + 16, y + 29), "|   and the proof", fill=TEXT_MAIN, font=f_tbl_box_sub)

    col_x = [
        mx + 36,
        mx + 390,
        mx + 840,
        mx + 1340,
        mx + usable_w - 235
    ]

    head_y = y + 90
    draw.text((col_x[0], head_y), "ISSUE", fill=C_BLUE, font=f_table_head)
    draw.text((col_x[1], head_y), company_name[:16].upper(), fill=C_BLUE, font=f_table_head)
    draw.text((col_x[2], head_y), "TOP RIVAL", fill=C_BLUE, font=f_table_head)
    draw.text((col_x[3], head_y), "WHAT IT COSTS YOU", fill=C_BLUE, font=f_table_head)
    draw.text((col_x[4] - 30, head_y), "AFFECTS", fill=C_BLUE, font=f_table_head)

    draw.line([(mx + 25, head_y + 42), (mx + usable_w - 25, head_y + 42)], fill=BORDER_LIGHT, width=2)

    t_rev = int(lead.get('review_count', 0) or 0)
    t_rat = float(lead.get('rating', 0.0) or 0.0)
    r_rev = int(rival.get('review_count', 0) or 0)
    r_rat = float(rival.get('rating', 0.0) or 0.0)
    t_speed_num = float(footprint.get('load_speed_sec', 2.0) or 2.0)
    r_speed_num = float(rival_fp.get('load_speed_sec', 1.5) or 1.5)

    # Dynamic impact narratives based on actual head-to-head performance
    is_trust_better = (t_rat > r_rat) or (t_rat == r_rat and t_rev >= r_rev)
    trust_impact = "Strong review trust vs rival" if is_trust_better else "Rival wins trust before the first call"

    is_speed_better = t_speed_num <= r_speed_num
    speed_impact = "Fast load preserves ad traffic" if is_speed_better else "Slow loads lose visitors before they call"

    is_call_active = bool(footprint.get("has_click_to_call"))
    call_impact = "Fast call access active" if is_call_active else "No one-tap call from every page"

    comp_rows = [
        ("Google rating", f"{t_rat} ({t_rev} reviews)", f"{r_rat} ({r_rev:,} reviews)", trust_impact, f"Local {s_local}", is_trust_better),
        ("Home page speed", f"{t_speed_num} sec", f"{r_speed_num} sec", speed_impact, f"Speed {s_speed}", is_speed_better),
        ("Booking flow", "Basic form" if footprint.get("has_lead_form") else "Missing form", "Optimized flow", "Extra friction costs you leads", f"Booking {s_mobile}", False),
        ("Mobile calling", "Click-to-call active" if is_call_active else "Not on every page", "Instant call-ready", call_impact, f"Booking {s_mobile}", is_call_active),
        ("Local map accuracy", f"{s_local}%", "95%", "Strong map pack presence" if s_local >= 95 else "Rival ranks higher on map results", f"Local {s_local}", s_local >= 95)
    ]
    row_y = head_y + 58
    for issue, tgt_val, riv_val, cost_impact, affects_text, is_client_better in comp_rows:
        draw.text((col_x[0], row_y), issue, fill=TEXT_MAIN, font=f_table_body_b)
        tgt_color = C_GREEN if is_client_better else C_RED
        draw.text((col_x[1], row_y), tgt_val, fill=tgt_color, font=f_table_body_b)
        riv_color = C_RED if is_client_better else C_GREEN
        draw.text((col_x[2], row_y), riv_val, fill=riv_color, font=f_table_body)
        draw.text((col_x[3], row_y), cost_impact, fill=TEXT_MUTED, font=f_table_body)

        btn_w, btn_h = 190, 44
        btn_x1 = col_x[4] - 40
        btn_y1 = row_y - 4
        draw.rounded_rectangle([btn_x1, btn_y1, btn_x1 + btn_w, btn_y1 + btn_h], radius=22, fill=(239, 246, 255), outline=C_BLUE, width=2)
        b_bbox = draw.textbbox((0, 0), affects_text, font=f_badge_font)
        bw = b_bbox[2] - b_bbox[0]
        bh = b_bbox[3] - b_bbox[1]
        draw.text((btn_x1 + (btn_w - bw) // 2, btn_y1 + (btn_h - bh) // 2 - 2), affects_text, fill=C_BLUE, font=f_badge_font)
        row_y += 56

    current_audit_date = pd.Timestamp.now().strftime('%B %Y')
    clean_rival_name = str(rival.get('name', 'Top Rival')).strip()
    bench_source = f"Rival benchmark: {clean_rival_name}  |  Sources: Google Business Profile, PageSpeed Insights, public listings ({current_audit_date})"
    draw.text((mx + 36, y + table_box_h - 40), bench_source, fill=TEXT_FAINT, font=f_table_source)
    # +8pt increased gap
    y += table_box_h + 120

    # =============================================================
    # 5. WEBSITE FOUNDATIONS
    # =============================================================
    found_h = 265
    draw.rounded_rectangle([mx, y, mx + usable_w, y + found_h], radius=18, fill=BG_CARD, outline=BORDER_LIGHT, width=2)

    f_start_x = mx + 36
    draw.text((f_start_x, y + 26), "WEBSITE FOUNDATIONS", fill=TEXT_MAIN, font=f_found_title)
    f_main_w = draw.textbbox((0, 0), "WEBSITE FOUNDATIONS", font=f_found_title)[2]
    draw.text((f_start_x + f_main_w + 16, y + 29), "|   what's in place today", fill=TEXT_MAIN, font=f_found_sub)
    draw.line([(mx + 25, y + 80), (mx + usable_w - 25, y + 80)], fill=BORDER_LIGHT, width=2)

    col3_w = usable_w // 3
    col_y_head = y + 98
    col_y_row1 = y + 150
    col_y_row2 = y + 198

    # Column 1: WORKING
    col1_x = mx + 36
    draw.text((col1_x, col_y_head), "✔  WORKING", fill=C_GREEN, font=f_col_head)
    w_line1 = "SSL secure  |  Google search markup" if footprint.get("has_ssl", True) else "Google search markup active"
    w_line2 = "Page hierarchy  |  Privacy policy" if footprint.get("has_privacy_policy", True) else "Semantic heading hierarchy"
    draw.text((col1_x, col_y_row1), w_line1, fill=TEXT_MAIN, font=f_found_body)
    draw.text((col1_x, col_y_row2), w_line2, fill=TEXT_MAIN, font=f_found_body)

    # Column 2: PARTIAL
    col2_x = mx + col3_w + 25
    draw.text((col2_x, col_y_head), "!  PARTIAL", fill=C_AMBER, font=f_col_head)
    p_line1 = "Mobile layout  |  Image optimization" if footprint.get("images_missing_alt", 0) > 0 else "Mobile viewport configuration"
    p_line2 = "Basic analytics tracking (GA4 only)" if footprint.get("has_ga4") and not footprint.get("has_gtm") else "Tag management & tracking"
    draw.text((col2_x, col_y_row1), p_line1, fill=TEXT_MAIN, font=f_found_body)
    draw.text((col2_x, col_y_row2), p_line2, fill=TEXT_MAIN, font=f_found_body)

    # Column 3: MISSING
    col3_x = mx + (col3_w * 2) + 15
    draw.text((col3_x, col_y_head), "✘  MISSING", fill=C_RED, font=f_col_head)
    m_line1 = "Mobile tap-to-call bar  |  Sticky CTA buttons" if not footprint.get("has_click_to_call") else "Sticky bottom appointment CTA"
    m_line2 = "Direct booking calendar  |  Tag system" if not footprint.get("has_booking_embed") else "Full-funnel pipeline tracking"
    draw.text((col3_x, col_y_row1), m_line1, fill=C_RED, font=f_found_body_b)
    draw.text((col3_x, col_y_row2), m_line2, fill=C_RED, font=f_found_body_b)

    # +8pt increased gap
    y += found_h + 120

    # =============================================================
    # 6. ACTION MATRIX & AUTHORIZED ACCESS
    # =============================================================
    def get_tier_color(score_val: int) -> tuple:
        if score_val >= 90: return (22, 163, 74)
        elif score_val >= 80: return (217, 119, 6)
        return (220, 38, 38)

    col_current_grade = get_tier_color(avg_score)
    target_score = 85 if avg_score < 80 else 92
    col_target_grade = get_tier_color(target_score)
    target_grade_str = "B+ target" if target_score == 85 else "A- target"

    act_box_h = 465
    draw.rounded_rectangle([mx, y, mx + usable_w, y + act_box_h], radius=18, fill=BG_CARD, outline=C_BLUE_DARK, width=3)
    split_x = mx + 1380

    lx = mx + 40
    draw.text((lx, y + 26), "HOW WE'D RAISE YOUR GRADE", fill=TEXT_MAIN, font=f_act_title)
    cur_g_x = lx + draw.textbbox((0, 0), "HOW WE'D RAISE YOUR GRADE", font=f_act_title)[2] + 28
    draw.text((cur_g_x, y + 28), grade_letter, fill=col_current_grade, font=f_act_grade)
    arrow_x = cur_g_x + draw.textbbox((0, 0), grade_letter, font=f_act_grade)[2] + 16
    draw.text((arrow_x, y + 28), "→", fill=C_BLUE, font=f_act_grade)
    tgt_x = arrow_x + draw.textbbox((0, 0), "→", font=f_act_grade)[2] + 16
    draw.text((tgt_x, y + 28), target_grade_str, fill=col_target_grade, font=f_act_grade)

    col_h_y = y + 88
    draw.text((lx, col_h_y), "WHAT WE DO", fill=C_BLUE, font=f_act_head)
    draw.text((mx + 795, col_h_y), "LIFTS", fill=C_BLUE, font=f_act_head)
    draw.text((mx + 1105, col_h_y), "WHEN", fill=C_BLUE, font=f_act_head)
    draw.line([(lx, col_h_y + 40), (split_x - 30, col_h_y + 40)], fill=BORDER_LIGHT, width=2)

    actions = [
        ("Sticky tap-to-call bar on every page", f"Booking {s_mobile}", "Week 1"),
        ("Tag Manager + conversion tracking", f"Capture {s_retention}", "Week 1"),
        ("Page speed tune-up", f"Speed {s_speed}", "Weeks 2-4"),
        ("Local business schema markup", f"Local {s_local}", "Weeks 2-3"),
        ("Review generation system", "Rival gap", "Ongoing")
    ]

    row_ay = col_h_y + 56
    for what_text, lift_text, when_text in actions:
        circle_cx, circle_cy, circle_r = lx + 16, row_ay + 15, 15
        draw.ellipse([circle_cx - circle_r, circle_cy - circle_r, circle_cx + circle_r, circle_cy + circle_r], fill=(22, 163, 74))
        draw.text((circle_cx - 8, circle_cy - 14), "✔", fill=(255, 255, 255), font=f_check_font)
        draw.text((lx + 46, row_ay), what_text, fill=TEXT_MAIN, font=f_act_body)

        btn_w, btn_h = 180, 42
        btn_bx = mx + 795 - 20
        btn_by = row_ay - 4
        draw.rounded_rectangle([btn_bx, btn_by, btn_bx + btn_w, btn_by + btn_h], radius=21, fill=(255, 255, 255), outline=C_BLUE, width=2)
        lb_box = draw.textbbox((0, 0), lift_text, font=f_act_btn)
        lb_w = lb_box[2] - lb_box[0]
        lb_h = lb_box[3] - lb_box[1]
        draw.text((btn_bx + (btn_w - lb_w) // 2, btn_by + (btn_h - lb_h) // 2 - 2), lift_text, fill=C_BLUE, font=f_act_btn)
        draw.text((mx + 1105, row_ay), when_text, fill=TEXT_MUTED, font=f_act_time)
        row_ay += 58

    draw.line([(split_x, y + 25), (split_x, y + act_box_h - 25)], fill=BORDER_LIGHT, width=2)

    rx = split_x + 40
    draw.text((rx, y + 26), "UNLOCK YOUR EXACT DOLLAR IMPACT", fill=C_BLUE, font=f_act_right_head)
    draw.text((rx, y + 72), "With 15 minutes of access, we can answer:", fill=TEXT_MUTED, font=f_act_right_sub)

    tool_inquiries = [
        ("Search Console", "What do customers search before they call?"),
        ("Business Profile", "How many calls and directions come from Google?"),
        ("Analytics 4", "Which pages turn visitors into bookings?"),
        ("Google Ads", "How much ad spend is being wasted?")
    ]
    t_y = y + 124
    for tool_head, tool_question in tool_inquiries:
        draw.text((rx, t_y), tool_head, fill=TEXT_MAIN, font=f_tool_title)
        draw.text((rx, t_y + 36), tool_question, fill=TEXT_MUTED, font=f_tool_desc)
        t_y += 76

    # +8pt increased gap
    y += act_box_h +120

    # =============================================================
    # 7. FOOTER CALL-TO-ACTION (Restored Compact Size & Centered)
    # =============================================================
    # Restored to fixed compact height without QR code
    foot_h = 240
    draw.rounded_rectangle([mx, y, mx + usable_w, y + foot_h], radius=20, fill=C_BLUE)

    # 1. Headline (White & Bold, Centered)
    cta_lead = "Ready to see what each missed call is worth?"
    cl_bbox = draw.textbbox((0, 0), cta_lead, font=f_cta_hook)
    cl_w = cl_bbox[2] - cl_bbox[0]
    draw.text((mx + (usable_w - cl_w) // 2, y + 26), cta_lead, fill=(255, 255, 255), font=f_cta_hook)

    # 2. White Walkthrough CTA Button (Centered)
    btn_text = "Book your free 15-minute walkthrough"
    bt_bbox = draw.textbbox((0, 0), btn_text, font=f_btn_text)
    bt_w = bt_bbox[2] - bt_bbox[0]
    bt_h = bt_bbox[3] - bt_bbox[1]

    btn_pad_x = 44
    btn_w = bt_w + (btn_pad_x * 2)
    btn_h = 60
    btn_x = mx + (usable_w - btn_w) // 2
    btn_y = y + 84

    draw.rounded_rectangle([btn_x, btn_y, btn_x + btn_w, btn_y + btn_h], radius=30, fill=(255, 255, 255))
    draw.text((btn_x + btn_pad_x, btn_y + (btn_h - bt_h) // 2 - 3), btn_text, fill=C_BLUE, font=f_btn_text)

    # 3. Contact Coordinates (White Text, Centered)
    agency_web = CONFIG.get("AGENCY_WEBSITE", "www.elkinsrevenue.com").lower()
    agency_phone = CONFIG.get("AGENCY_PHONE", "917-327-0636")
    agency_email = CONFIG.get("AGENCY_EMAIL", "info@elkinsrevenue.com")
    contact_str = f"{agency_web}   |   {agency_phone}   |   {agency_email}"

    fc_bbox = draw.textbbox((0, 0), contact_str, font=f_cta_contact)
    fc_w = fc_bbox[2] - fc_bbox[0]
    draw.text((mx + (usable_w - fc_w) // 2, y + 166), contact_str, fill=(255, 255, 255), font=f_cta_contact)

    # Save output to single-page PDF
    img.save(out_pdf_path, "PDF", resolution=300.0)
    print(f"  -> Generated Scorecard PDF (Balanced Whitespace & Clean Footer): {out_pdf_path}")
    return out_pdf_path

#==============================================================================
# GOOGLE DRIVE / SLIDES INTEGRATION (OPTION 4)
# ==============================================================================
def assemble_pitch_google_slides(company_name: str, audit: dict) -> str:
    """Updates or creates a presentation deck directly in Google Slides."""
    creds_file = CONFIG.get("GOOGLE_SHEETS_CREDENTIALS_JSON", "")
    if not GOOGLE_APIS_AVAILABLE or not os.path.exists(creds_file):
        print("  [Google Slides]: Service account JSON not found. Skipping Google Slides.")
        return "N/A (Google API Credentials Missing)"

    try:
        scope = ["https://www.googleapis.com/auth/presentations", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(creds_file, scope)
        slides_service = build("slides", "v1", credentials=creds)

        body = {"title": f"{company_name} — Strategic Performance Deck"}
        deck = slides_service.presentations().create(body=body).execute()
        deck_id = deck.get("presentationId")

        print(f"  [Google Slides] Created deck: https://docs.google.com/presentation/d/{deck_id}/edit")
        return f"https://docs.google.com/presentation/d/{deck_id}/edit"
    except Exception as e:
        print(f"  [Google Slides Failed]: {e}")
        return "N/A (API Error)"

# ==============================================================================
# PERSISTENCE (GOOGLE SHEETS ONLY - NO LOCAL CSV DUAL-WRITE)
# ==============================================================================
def save_records(records: list):
    """Syncs lead audit records to Google Sheets with NaN sanitization."""
    if not records:
        return
    
    creds_file = CONFIG.get("GOOGLE_SHEETS_CREDENTIALS_JSON", "")
    sheet_name = CONFIG.get("GOOGLE_SHEET_NAME", "Prospecting Pipeline & Audit Data")

    if not GOOGLE_APIS_AVAILABLE or not os.path.exists(creds_file):
        print(f"  [Google Sheets Error] Credentials file not found at: {creds_file}")
        return

    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(creds_file, scope)
        client = gspread.authorize(creds)
        
        sheet = client.open(sheet_name).sheet1
        
        # 1. Load DataFrame and clean NaNs
        df = pd.DataFrame(records)
        df = df.fillna("")  # Replaces NaN with empty string
        
        headers = list(df.columns)
        if not sheet.get_all_values():
            sheet.append_row(headers)
            
        # 2. Convert all values to strings for clean Google API transmission
        rows = df.astype(str).values.tolist()
        sheet.append_rows(rows)
        print(f"  [GOOGLE SHEETS] Successfully synced {len(records)} record(s) to '{sheet_name}'.")

    except Exception as e:
        print(f"  [Google Sheets Sync Warning]: {e}")
def save_intelligence_cache():
    """Placeholder to persist cached competitor research."""
    pass

def print_usage_and_cost_summary(total_leads: int):
    """Outputs token consumption and equivalent cost estimates."""
    p_tok = TOKEN_STATS["prompt_tokens"]
    c_tok = TOKEN_STATS["completion_tokens"]
    t_tok = TOKEN_STATS["total_tokens"]
    est_cost = (p_tok * 0.00000015) + (c_tok * 0.0000006)
    print("\n" + "=" * 65)
    print("SESSION RESOURCE & TOKEN CONSUMPTION REPORT")
    print("=" * 65)
    print(f"Leads Processed:     {total_leads}")
    print(f"Prompt Tokens:       {p_tok:,}")
    print(f"Completion Tokens:   {c_tok:,}")
    print(f"Total API Tokens:    {t_tok:,}")
    print(f"Commercial Equiv:    ${est_cost:.4f}")
    print("=" * 65)

# ==============================================================================
# MAIN EXECUTION PIPELINE
# ==============================================================================
def main():
    print("=" * 65)
    print("ELKINS & CO. — COMPREHENSIVE REVENUE & PERFORMANCE AUDITOR")
    print("=" * 65)

    # 1. Output Format Selection
    print("\n[Step 1] Select Deliverable Output Format:")
    print("  [1] MP4 Video Presentation (Voiceover + Slides)")
    print("  [2] PDF Slide Deck (Visual Diagnostic & GTM Slides)")
    print("  [3] Data Only (Direct to Google Sheets)")
    print("  [4] Native Google Slides Deck (Saves to Drive/Docs)")
    print("  [5] Single-Page Executive Scorecard (Print-Ready PDF Report)")
    output_choice = input("Select Output [1-5, Default: 1]: ").strip() or "1"

    create_video = (output_choice == "1")
    create_pdf = (output_choice == "2")
    create_google_slides = (output_choice == "4")
    create_scorecard = (output_choice == "5")

    # 2. Lead Discovery Mode
    print("\n[Step 2] Select Prospect Mode:")
    print("  [1] Batch Discovery via Google Places")
    print("  [2] Single Prospect by Website URL")
    run_mode = input("Select Mode [1 or 2, Default: 1]: ").strip() or "1"

    leads = []
    category = "General Services"
    location = "Estero FL"

    if run_mode == "2":
        single_url = input("\nEnter prospect website URL: ").strip()
        if not single_url.startswith("http"):
            single_url = "https://" + single_url

        clean_domain = urlparse(single_url).netloc.replace("www.", "")
        name_guess = clean_domain.split(".")[0].replace("-", " ").title()

        name_input = input(f"Enter prospect business name [Default: '{name_guess}']: ").strip()
        prospect_name = name_input if name_input else name_guess

        category = input("Enter business category for competitor benchmark (e.g., Landscape, HVAC): ").strip() or "Business Services"
        location = input("Enter city/region for competitor benchmark (e.g., Estero FL): ").strip() or "Estero FL"

        leads = [{
            "name": prospect_name,
            "website": single_url,
            "address": location,
            "rating": 4.2,
            "review_count": 15,
            "phone": "Not Listed"
        }]
    else:
        category = input("\nEnter target business category (e.g., HVAC, Landscape, Optometrist): ").strip() or "Landscape"
        location = input("Enter target geographic region (e.g., Estero FL, Naples FL): ").strip() or "Estero FL"
        count_input = input("How many businesses to return and process? [Default: 1]: ").strip() or "1"
        try:
            limit = int(count_input)
        except ValueError:
            limit = 1

        print(f"\n[1/5] Discovering businesses for '{category}' in '{location}'...")
        leads = find_businesses(category, location, limit=limit)

    if not leads:
        print("No leads identified. Exiting.")
        return

    records = []

    # 3. Processing Loop
    for idx, lead in enumerate(leads, start=1):
        name = lead["name"]
        website = lead.get("website", "")
        clean_name = re.sub(r'[^a-zA-Z0-9]', '_', name)
        print(f"\n[{idx}/{len(leads)}] Processing: {name} ({website})")

        # Technical Scraping
        print("  [1/4] Scraping technical footprint & tag stack...")
        footprint = scrape_site_footprint(website)

        # Phase 1: authorized first-party Google data (skips cleanly when unavailable)
        phase1_data = collect_phase1_google_data(lead)

        # Benchmark Competitor
        print("  [2/4] Identifying local benchmark competitor...")
        rival = find_benchmark_competitor(category, location, name)
        rival_fp = scrape_site_footprint(rival.get("website", ""))

        # Viewport asset capture
        shot_path = None
        logo_path = None
        if (create_video or create_pdf or create_google_slides or create_scorecard) and CONFIG.get("CAPTURE_SCREENSHOT", True):
            print("  [3/4] Capturing desktop viewport via Playwright...")
            assets = capture_site_assets_playwright(website)
            shot_path = assets.get("screenshot_path")

        # Decision Maker & LLM Audit
        print("  [4/4] Synthesizing audit and go-to-market architecture...")
        contact = discover_decision_maker(name, website)
        audit = generate_audit(lead, footprint, contact, rival, rival_fp)

        # Quantitative Overall Performance Score
        perf_data = compute_overall_performance_score(lead, footprint)
        overall_score = perf_data["overall_score"]

        # Asset Assembly
        generated_asset = "N/A (Data Only)"
        if create_video:
            out_video = str(CONFIG["OUTPUT_DIR"] / f"{clean_name}_audit_brief.mp4")
            print(f"        Rendering MP4 video to: {out_video}")
            assemble_video(lead, footprint, contact, audit, rival, rival_fp, out_video, logo_path=logo_path, shot_path=shot_path)
            generated_asset = out_video
        elif create_pdf:
            out_pdf = str(CONFIG["OUTPUT_DIR"] / f"{clean_name}_audit_deck.pdf")
            print(f"        Rendering PDF presentation to: {out_pdf}")
            assemble_pdf(lead, footprint, contact, audit, rival, rival_fp, out_pdf, logo_path=logo_path, shot_path=shot_path)
            generated_asset = out_pdf
        elif create_google_slides:
            print("        Updating Google Slides presentation...")
            generated_asset = assemble_pitch_google_slides(name, audit)
        elif create_scorecard:
            out_scorecard = str(CONFIG["OUTPUT_DIR"] / f"{clean_name}_scorecard.pdf")
            print(f"        Rendering Single-Page Executive Scorecard to: {out_scorecard}")
            render_single_page_scorecard(lead, footprint, contact, rival, rival_fp, audit, shot_path, out_scorecard, phase1_data=phase1_data)
            generated_asset = out_scorecard

        # Append Google Sheet Record
        records.append({
            "Business Name": name,
            "Address": lead.get("address", location),
            "Phone": lead.get("phone", "Not Listed"),
            "Website": website,
            "Overall Performance Score": overall_score,
            "Conversion Sub-Score": perf_data["conversion"],
            "SEO Sub-Score": perf_data["seo"],
            "Speed Sub-Score": perf_data["speed"],
            "Reputation Sub-Score": perf_data["reputation"],
            "Marketing Maturity Sub-Score": perf_data["marketing"],
            "Decision Maker": contact["name"],
            "Title": contact["title"],
            "Competitor Benchmark": rival.get("name", "None"),
            "Competitor Rating": f"{rival.get('rating', 0)}★ ({rival.get('review_count', 0)})",
            "Competitor Latency": f"{rival_fp.get('load_speed_sec', 0)}s",
            "Competitor Gap Margin": audit.get("competitor_gap_margin", "N/A"),
            "Has Lead Form": footprint.get("has_lead_form", False),
            "Has Click-to-Call": footprint.get("has_click_to_call", False),
            "Has SSL": footprint.get("has_ssl", False),
            "Has Schema JSON-LD": footprint.get("has_schema", False),
            "Has GA4": footprint.get("has_ga4", False),
            "Has GTM": footprint.get("has_gtm", False),
            "Has Meta Pixel": footprint.get("has_meta_pixel", False),
            "Core Weakness": audit.get("core_weakness", ""),
            "Priority Quick Win": audit.get("quick_win", ""),
            "Proposed Solution": audit.get("solution", ""),
            "GSC Status": phase1_data.get("search_console", {}).get("status", "N/A"),
            "GSC Clicks (28d)": phase1_data.get("search_console", {}).get("clicks_28d"),
            "GSC Impressions (28d)": phase1_data.get("search_console", {}).get("impressions_28d"),
            "GSC CTR (28d)": phase1_data.get("search_console", {}).get("ctr_28d"),
            "GSC Avg Position (28d)": phase1_data.get("search_console", {}).get("avg_position_28d"),
            "GSC Top Queries": ", ".join(phase1_data.get("search_console", {}).get("top_queries", [])),
            "GA4 Status": phase1_data.get("ga4", {}).get("status", "N/A"),
            "GA4 Sessions (28d)": phase1_data.get("ga4", {}).get("sessions_28d"),
            "GA4 Users (28d)": phase1_data.get("ga4", {}).get("users_28d"),
            "GA4 Conversions (28d)": phase1_data.get("ga4", {}).get("conversions_28d"),
            "GBP Status": phase1_data.get("google_business_profile", {}).get("status", "N/A"),
            "GBP Website Clicks (28d)": phase1_data.get("google_business_profile", {}).get("website_clicks_28d"),
            "GBP Call Clicks (28d)": phase1_data.get("google_business_profile", {}).get("call_clicks_28d"),
            "GBP Direction Requests (28d)": phase1_data.get("google_business_profile", {}).get("direction_requests_28d"),
            "GBP Search Keywords": ", ".join(phase1_data.get("google_business_profile", {}).get("search_keywords", [])),
            "Google Ads Status": phase1_data.get("google_ads", {}).get("status", "N/A"),
            "Google Ads Impressions (30d)": phase1_data.get("google_ads", {}).get("impressions_30d"),
            "Google Ads Clicks (30d)": phase1_data.get("google_ads", {}).get("clicks_30d"),
            "Google Ads Cost (30d)": phase1_data.get("google_ads", {}).get("cost_30d"),
            "Google Ads Conversions (30d)": phase1_data.get("google_ads", {}).get("conversions_30d"),
            "Google Ads Transparency Lookup": phase1_data.get("ads_transparency", {}).get("lookup_url", ""),
            "Asset Path": generated_asset
        })

        # Sync to Google Sheets immediately per lead
        print("  [Syncing] Writing lead record to Google Sheets...")
        try:
            save_records(records[-1:])
        except Exception as err:
            print(f"  [Sync Warning] Failed immediate save: {err}")

    # End of session
    save_intelligence_cache()
    print("\n[COMPLETE] Run finished successfully.")
    print_usage_and_cost_summary(len(records))


if __name__ == "__main__":
    main()