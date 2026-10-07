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
    "OUTPUT_DIR": Path(r"G:\My Drive\Elkins Revenue Consulting\AI Agent Scripts\ElkinsRev Prospect Videos"),
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

    # Built-in Fallback Synthesis
    r_name = rival["name"] if rival else "Local Benchmark Leader"
    r_rating = rival.get("rating", 4.8) if rival else 4.8
    r_reviews = rival.get("review_count", 150) if rival else 150

    return {
        "scores": {
            "seo": 68, "website_speed": max(20, int(100 - (target_fp.get("load_speed_sec", 2.0) * 18))),
            "content_clarity": 72, "lead_conversion": 52, "reputation": int(min(98, (target.get("rating", 4.0) * 20))),
            "mobile_conversion_readiness": 58, "directory_nap_consistency": 80, "pipeline_leakage_index": 65
        },
        "core_weakness": "Mobile booking friction and absent LocalBusiness schema",
        "quick_win": "Deploy sticky tap-to-call CTA bar and Google Tag Manager GA4 triggers",
        "solution": "3-Tier Paid Acquisition blueprint combined with friction-free mobile wireframe",
        "competitor_gap_margin": f"{r_name} holds {r_rating}★ ({r_reviews} reviews) with faster mobile load response",
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
# SINGLE-PAGE EXECUTIVE SCORECARD (OPTION 5)
# ==============================================================================
def render_single_page_scorecard(lead: dict, footprint: dict, contact: dict, rival: dict, rival_fp: dict, audit: dict, shot_path: str, out_pdf_path: str, phase1_data: dict | None = None):
    """
    Renders an executive-grade 8.5x11 in @ 300 DPI (2550 x 3300 px) single-page audit report.
    Updated with customer-friendly terminology, expanded checklist grid, and enlarged CTAs.
    """
    W, H = 2550, 3300
    img = Image.new("RGB", (W, H), color=(248, 250, 252))
    draw = ImageDraw.Draw(img)

    # -------------------------------------------------------------
    # 1. TYPOGRAPHY & FONT SETUP (Adjusted +4pt on key sections)
    # -------------------------------------------------------------
    f_brand_main = load_font(["arialbd.ttf", "segoeuib.ttf"], 52)
    f_brand_sub = load_font(["arialbd.ttf", "segoeuib.ttf"], 34)
    f_title = load_font(["arialbd.ttf", "segoeuib.ttf"], 54)
    f_meta = load_font(["arial.ttf", "segoeui.ttf"], 30)
    f_sec = load_font(["arialbd.ttf", "segoeuib.ttf"], 40)
    
    # +4 pt boost for Executive Summary and Section Headers
    f_exec_head = load_font(["arialbd.ttf", "segoeuib.ttf"], 36)    # Was 32
    f_exec_title = load_font(["arialbd.ttf", "segoeuib.ttf"], 36)   # Was 32
    f_exec_body = load_font(["arial.ttf", "segoeui.ttf"], 34)       # Was 30
    
    f_card_title = load_font(["arialbd.ttf", "segoeuib.ttf"], 28)
    f_score_num = load_font(["arialbd.ttf", "segoeuib.ttf"], 60)
    f_table_head = load_font(["arialbd.ttf", "segoeuib.ttf"], 30)
    f_table_body = load_font(["arial.ttf", "segoeui.ttf"], 27)
    f_table_body_b = load_font(["arialbd.ttf", "segoeuib.ttf"], 27)
    
    # Checklist typography
    f_check_sym = load_font(["arialbd.ttf", "segoeuib.ttf"], 28)
    f_check_label = load_font(["arialbd.ttf", "segoeuib.ttf"], 25)
    f_check_val = load_font(["arial.ttf", "segoeui.ttf"], 23)

    # CTA typography (Enlarged)
    f_cta_big = load_font(["arialbd.ttf", "segoeuib.ttf"], 40)
    f_cta_contact = load_font(["arialbd.ttf", "segoeuib.ttf"], 34)

    # Brand Colors matching elkinsrevenue.com
    COLOR_BRAND_DARK = (30, 36, 43)    # Charcoal brand color
    COLOR_COBALT = (37, 99, 235)       # Electric Cobalt Blue
    TEXT_DARK = (15, 23, 42)           # Solid Black/Charcoal for items
    TEXT_BODY = (51, 65, 85)
    TEXT_MUTED = (100, 116, 139)
    BORDER = (226, 232, 240)
    CARD_BG = (255, 255, 255)
    GREEN = (22, 163, 74)
    RED = (220, 38, 38)
    AMBER = (217, 119, 6)

    mx = 110
    y = 95

    # -------------------------------------------------------------
    # 2. HEADER & LOGO LOCKUP (elkinsrevenue.com palette)
    # -------------------------------------------------------------
    brand_main = "ELKINS & CO."
    draw.text((mx, y), brand_main, fill=COLOR_BRAND_DARK, font=f_brand_main)
    bbox_b = draw.textbbox((mx, y), brand_main, font=f_brand_main)
    
    draw.line([(bbox_b[2] + 25, y + 6), (bbox_b[2] + 25, y + 54)], fill=TEXT_MUTED, width=3)
    draw.text((bbox_b[2] + 45, y + 10), "REVENUE STRATEGIES", fill=COLOR_COBALT, font=f_brand_sub)

    # Eyebrow Pill
    pill_text = "EXECUTIVE DIGITAL AUDIT"
    pb = draw.textbbox((0, 0), pill_text, font=f_table_head)
    pw = pb[2] - pb[0] + 50
    draw.rounded_rectangle([W - mx - pw, y, W - mx, y + 60], radius=12, fill=(239, 246, 255), outline=COLOR_COBALT, width=2)
    draw.text((W - mx - pw + 25, y + 12), pill_text, fill=COLOR_COBALT, font=f_table_head)

    y += 90
    draw.line([(mx, y), (W - mx, y)], fill=BORDER, width=3)
    y += 40

    # -------------------------------------------------------------
    # 3. PROSPECT AUDIT BANNER (Audit Target + Same Row Meta)
    # -------------------------------------------------------------
    hero_h = 165
    draw.rounded_rectangle([mx, y, W - mx, y + hero_h], radius=18, fill=CARD_BG, outline=BORDER, width=2)
    
    company_name = lead.get('name', 'N/A')
    draw.text((mx + 45, y + 25), f"Digital Audit Prepared for {company_name}", fill=COLOR_BRAND_DARK, font=f_title)

    # Single Row: Web URL and Location
    web_url = lead.get('website', 'N/A')
    location_str = lead.get('address', 'Denver, CO')
    if "," in location_str:
        parts = [p.strip() for p in location_str.split(",")]
        location_display = f"{parts[-3]}, {parts[-2][:2].upper()}" if len(parts) >= 3 else location_str
    else:
        location_display = location_str

    combined_meta = f"Web: {web_url}   |   Location: {location_display}   |   Audited: {pd.Timestamp.now().strftime('%B %Y')}"
    draw.text((mx + 45, y + 95), combined_meta, fill=TEXT_BODY, font=f_meta)

    y += hero_h + 40

    # -------------------------------------------------------------
    # 4. SPLIT SECTION: SCREENSHOT MOCKUP vs EASY SUB-PILLARS
    # -------------------------------------------------------------
    split_h = 710
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
    draw.text((mx + 130, y + 14), web_url, fill=TEXT_MUTED, font=f_table_body)

    if shot_path and os.path.exists(shot_path):
        try:
            with Image.open(shot_path) as s_img:
                s_img = s_img.convert("RGB")
                shot_render_h = split_h - 58
                s_resized = s_img.resize((left_w - 6, shot_render_h), Image.Resampling.LANCZOS)
                img.paste(s_resized, (mx + 3, y + 55))
        except Exception:
            draw.text((mx + 340, y + 320), "[Live Website Viewport Active]", fill=TEXT_MUTED, font=f_sec)
    else:
        draw.text((mx + 340, y + 320), "[Live Website Viewport Active]", fill=TEXT_MUTED, font=f_sec)

    # Right: Sub-Pillars in Plain, Easy English
    scores = audit.get("scores", {})
    plain_pillars = [
        ("Ease of Booking & Calling (Mobile)", scores.get("mobile_conversion_readiness", scores.get("mobile", 55))),
        ("Website Loading Speed", scores.get("website_speed", scores.get("speed", 68))),
        ("Local Search & Map Accuracy", scores.get("directory_nap_consistency", 84)),
        ("Lead Retention & Customer Capture", scores.get("pipeline_leakage_index", 62))
    ]

    card_h = (split_h - (3 * 20)) // 4
    gy = y
    for label, val in plain_pillars:
        draw.rounded_rectangle([right_x, gy, right_x + right_w, gy + card_h], radius=16, fill=CARD_BG, outline=BORDER, width=2)
        score_c = GREEN if val >= 80 else (AMBER if val >= 60 else RED)

        draw.text((right_x + 30, gy + 22), label, fill=COLOR_BRAND_DARK, font=f_card_title)
        draw.text((right_x + right_w - 130, gy + 14), f"{val}", fill=score_c, font=f_score_num)

        bar_w = right_w - 60
        bar_y = gy + 88
        draw.rounded_rectangle([right_x + 30, bar_y, right_x + 30 + bar_w, bar_y + 14], radius=7, fill=(226, 232, 240))
        draw.rounded_rectangle([right_x + 30, bar_y, right_x + 30 + int(bar_w * (val / 100)), bar_y + 14], radius=7, fill=score_c)
        gy += card_h + 20

    y += split_h + 38

    # -------------------------------------------------------------
    # 5. EXPANDED CHECKLIST: 16 METRICS (Black titles, Green/Red checks)
    # -------------------------------------------------------------
    draw.text((mx, y), "Website Foundations & Customer Contact Check", fill=COLOR_BRAND_DARK, font=f_sec)
    y += 50

    tech_w = W - (2 * mx)
    tech_h = 280
    draw.rounded_rectangle([mx, y, mx + tech_w, y + tech_h], radius=16, fill=CARD_BG, outline=BORDER, width=2)

    # 16 Metrics across 4 columns (fills available horizontal space)
    checklist_data = [
        # Col 1: Customer Contact
        ("Mobile Tap-to-Call", footprint.get("has_click_to_call"), "Active", "Missing"),
        ("Online Quote / Form", footprint.get("has_lead_form"), "Found", "Missing"),
        ("Instant Chat / SMS", footprint.get("chat_platform", "None") not in ["None", "Not Detected", None], "Installed", "None"),
        ("Direct Booking Calendar", footprint.get("booking_platform", "None") not in ["None", "Not Detected", None], "Enabled", "None"),
        # Col 2: Speed & Mobile UX
        ("Fast Mobile Loading", (footprint.get("load_speed_sec", 4.0) or 4.0) < 2.5, "Fast", "Slow"),
        ("Smartphone Layout", footprint.get("is_mobile_responsive", True), "Optimized", "Not Mobile Ready"),
        ("Image Size Optimization", footprint.get("images_missing_alt", 0) <= 2, "Clean", f"{footprint.get('images_missing_alt', 3)} Unoptimized"),
        ("Page Title Hierarchy", footprint.get("heading_issue", "Clean Hierarchy") in ["Clean Hierarchy", "None"], "Standard", "Disorganized"),
        # Col 3: Trust & Discovery
        ("Secure Connection (SSL)", footprint.get("has_ssl", True), "Secure", "Unsecured"),
        ("Google Search Markup", footprint.get("has_schema", False), "Indexed", "Missing"),
        ("Page Summary Tags", footprint.get("has_meta_desc", True), "Complete", "Incomplete"),
        ("Privacy & Trust Policy", footprint.get("has_privacy_policy", True), "Published", "Missing"),
        # Col 4: Tracking & Visibility
        ("Website Visitor Analytics", footprint.get("has_ga4", False), "Tracking", "No Data"),
        ("Marketing Tag System", footprint.get("has_gtm", False), "Connected", "Unconnected"),
        ("Social Audience Tracking", footprint.get("has_meta_pixel", False), "Active", "Inactive"),
        ("Social Business Profiles", len(footprint.get("social_links", [])) > 0, "Connected", "Missing")
    ]

    col_w = tech_w // 4
    for i, (title_str, is_good, good_lbl, bad_lbl) in enumerate(checklist_data):
        c_col = i // 4
        c_row = i % 4
        ix = mx + 25 + (c_col * col_w)
        iy = y + 20 + (c_row * 60)

        check_sym = "✔" if is_good else "✘"
        sym_color = GREEN if is_good else RED
        val_str = good_lbl if is_good else bad_lbl

        draw.text((ix, iy), check_sym, fill=sym_color, font=f_check_sym)
        # Black title text
        draw.text((ix + 35, iy + 2), title_str, fill=TEXT_DARK, font=f_check_label)
        draw.text((ix + 35, iy + 30), val_str, fill=sym_color if not is_good else TEXT_BODY, font=f_check_val)

    y += tech_h + 38

    # -------------------------------------------------------------
    # 6. COMPETITOR COMPARISON (Updated terminology & 2 added metrics)
    # -------------------------------------------------------------
    draw.text((mx, y), "Competitor Comparison", fill=COLOR_BRAND_DARK, font=f_sec)
    y += 50

    bench_h = 300
    draw.rounded_rectangle([mx, y, mx + tech_w, y + bench_h], radius=16, fill=CARD_BG, outline=BORDER, width=2)

    col1_x = mx + 35
    col2_x = mx + 680
    col3_x = mx + 1300
    col4_x = mx + 1820

    # Header Row
    draw.text((col1_x, y + 16), "DIGITAL FACTOR", fill=TEXT_MUTED, font=f_table_head)
    draw.text((col2_x, y + 16), f"YOUR BUSINESS ({company_name[:18]})", fill=COLOR_BRAND_DARK, font=f_table_head)
    rival_label = rival.get('name', 'Top Local Competitor')[:20] if rival else 'Top Competitor'
    draw.text((col3_x, y + 16), f"RIVAL ({rival_label})", fill=COLOR_COBALT, font=f_table_head)
    draw.text((col4_x, y + 16), "HOW YOU COMPARE", fill=TEXT_MUTED, font=f_table_head)

    draw.line([(mx + 25, y + 58), (mx + tech_w - 25, y + 58)], fill=BORDER, width=2)

    t_stars = f"{lead.get('rating', 'N/A')}★ ({lead.get('review_count', 0)} reviews)"
    r_stars = f"{rival.get('rating', 4.8)}★ ({rival.get('review_count', 0)} reviews)" if rival else "4.8★ (High Volume)"
    t_speed = f"{footprint.get('load_speed_sec', 'N/A')}s"
    r_speed = f"{rival_fp.get('load_speed_sec', '1.2')}s" if rival_fp else "1.2s"

    comp_rows = [
        ("Performance Score", t_stars, r_stars, audit.get("competitor_gap_margin", "Rival holds higher buyer trust")[:36]),
        ("Home Page Responsiveness", t_speed, r_speed, "Speed delay causing customer bounce" if (footprint.get('load_speed_sec', 0) or 0) > 2.5 else "Responsive performance"),
        ("Customer Booking System", "Basic / Form" if footprint.get("has_lead_form") else "Missing Forms", "Optimized Inquiry Flow", "Lost leads to local alternative"),
        # 2 New Metrics
        ("Mobile Contact Capability", "Click-to-Call Active" if footprint.get("has_click_to_call") else "Missing Call Link", "Instant Call Ready", "Friction for mobile phone callers"),
        ("Local Map & Directory Footprint", f"{audit.get('scores', {}).get('directory_nap_consistency', 80)}% Alignment", "95% Alignment", "Competitor captures top map positions")
    ]

    for idx, (m_col, t_col, r_col, i_col) in enumerate(comp_rows):
        ry = y + 70 + (idx * 44)
        draw.text((col1_x, ry), m_col, fill=TEXT_BODY, font=f_table_body)
        draw.text((col2_x, ry), t_col, fill=COLOR_BRAND_DARK, font=f_table_body_b)
        draw.text((col3_x, ry), r_col, fill=COLOR_COBALT, font=f_table_body_b)
        draw.text((col4_x, ry), i_col, fill=RED if any(k in i_col.lower() for k in ["delay", "lost", "friction", "higher", "missing"]) else TEXT_BODY, font=f_table_body)

    y += bench_h + 38

    # -------------------------------------------------------------
    # 7. EXECUTIVE SUMMARY & REVENUE RECOVERY ACTIONS (+4 pt Bigger)
    # -------------------------------------------------------------
    box_w = (tech_w - 40) // 2
    box_h = 320

    # Summary Box (Weakness)
    draw.rounded_rectangle([mx, y, mx + box_w, y + box_h], radius=16, fill=(254, 242, 242), outline=(254, 202, 202), width=2)
    draw.text((mx + 35, y + 25), "EXECUTIVE SUMMARY: WHERE REVENUE IS LOST", fill=RED, font=f_exec_head)
    weakness_text = audit.get("core_weakness", "Mobile barriers and missing contact triggers divert potential clients to competitors.")
    draw.text((mx + 35, y + 80), weakness_text[:110], fill=COLOR_BRAND_DARK, font=f_exec_title)
    draw.text((mx + 35, y + 160), "• Mobile shoppers abandon due to missing 1-click calling.", fill=TEXT_BODY, font=f_exec_body)
    draw.text((mx + 35, y + 215), "• Search engine listings lack structured local business schema.", fill=TEXT_BODY, font=f_exec_body)
    draw.text((mx + 35, y + 270), "• Customer review volume lags behind top-ranking local rivals.", fill=TEXT_BODY, font=f_exec_body)

    # Actions Box (Quick Win)
    bx2 = mx + box_w + 40
    draw.rounded_rectangle([bx2, y, bx2 + box_w, y + box_h], radius=16, fill=(239, 246, 255), outline=(191, 219, 254), width=2)
    draw.text((bx2 + 35, y + 25), "REVENUE RECOVERY ACTIONS (IMMEDIATE LIFT)", fill=COLOR_COBALT, font=f_exec_head)
    quick_win_text = audit.get("quick_win", "Implement instant mobile calling, fast lead forms, and local map pack schema.")
    draw.text((bx2 + 35, y + 80), quick_win_text[:110], fill=COLOR_BRAND_DARK, font=f_exec_title)
    draw.text((bx2 + 35, y + 160), "• Activate direct tap-to-call buttons across all mobile pages.", fill=TEXT_BODY, font=f_exec_body)
    draw.text((bx2 + 35, y + 215), "• Configure LocalBusiness structured markup for Map Pack rankings.", fill=TEXT_BODY, font=f_exec_body)
    draw.text((bx2 + 35, y + 270), "• Turn on automated review capture to outpace local competition.", fill=TEXT_BODY, font=f_exec_body)

    # -------------------------------------------------------------
    # 8. AUTHORIZED DATA OPPORTUNITY — TURN MISSING DATA INTO CTA
    # -------------------------------------------------------------
    # The public-facing audit is intentionally useful on its own.
    # Authorized first-party access lets Elkins & Co. replace estimates
    # with the prospect's actual search, traffic, profile and ad data.
    access_y = y + box_h + 42
    access_h = 520
    draw.rounded_rectangle([mx, access_y, W - mx, access_y + access_h], radius=18, fill=(255, 255, 255), outline=BORDER, width=2)

    access_title = "WHAT WE CAN ASSESS WITH AUTHORIZED ACCOUNT ACCESS"
    draw.text((mx + 35, access_y + 22), access_title, fill=COLOR_BRAND_DARK, font=f_exec_head)
    access_sub = "This scorecard uses public information. With your permission, we can replace estimates with first-party performance data."
    draw.text((mx + 35, access_y + 70), access_sub, fill=TEXT_BODY, font=f_table_body)

    access_items = [
        ("GOOGLE SEARCH CONSOLE", "Actual search queries, clicks, impressions, CTR and average search position."),
        ("GOOGLE ANALYTICS 4", "Actual users, sessions, engagement and conversion activity — not website estimates."),
        ("GOOGLE BUSINESS PROFILE", "Actual calls, website clicks, direction requests and the searches finding the business."),
        ("GOOGLE ADS", "Actual ad impressions, clicks, spend and conversions so we can assess paid-search efficiency."),
    ]

    card_gap = 18
    inner_w = tech_w
    card_w = (inner_w - card_gap) // 2
    card_h = 170
    for i, (label, desc) in enumerate(access_items):
        c = i % 2
        r = i // 2
        cx = mx + (c * (card_w + card_gap))
        cy = access_y + 118 + (r * (card_h + 18))
        draw.rounded_rectangle([cx, cy, cx + card_w, cy + card_h], radius=14, fill=(239, 246, 255), outline=(191, 219, 254), width=2)
        draw.text((cx + 22, cy + 16), label, fill=COLOR_COBALT, font=f_card_title)

        # Simple wrapped description so the scorecard remains readable at 300 DPI.
        words = desc.split()
        lines = []
        current = ""
        for word in words:
            test = f"{current} {word}".strip()
            if draw.textbbox((0, 0), test, font=f_table_body)[2] <= card_w - 44:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        for line_idx, line in enumerate(lines[:3]):
            draw.text((cx + 22, cy + 58 + (line_idx * 30)), line, fill=TEXT_BODY, font=f_table_body)

    # Explicitly tell the prospect what the next step unlocks.
    next_step = "NEXT STEP: Give us authorized access to the relevant Google accounts and we can quantify where visibility, traffic, leads and ad dollars are being won or lost."
    draw.text((mx + 35, access_y + access_h - 48), next_step, fill=COLOR_BRAND_DARK, font=f_table_body_b)

    # -------------------------------------------------------------
    # 9. CENTERED & ENLARGED CALL TO ACTION & CONTACT INFO
    # -------------------------------------------------------------
    foot_h = 165
    foot_y = H - foot_h - 60
    draw.rounded_rectangle([mx, foot_y, W - mx, foot_y + foot_h], radius=18, fill=COLOR_BRAND_DARK)

    # Centered Main CTA Line
    cta_line = "LET US SHOW YOU HOW WE CAN HELP RECOVER LOST REVENUE"
    bbox_cta = draw.textbbox((0, 0), cta_line, font=f_cta_big)
    cta_w = bbox_cta[2] - bbox_cta[0]
    draw.text(((W - cta_w) // 2, foot_y + 30), cta_line, fill=(255, 255, 255), font=f_cta_big)

    # Centered Contact Info
    agency_web = CONFIG.get('AGENCY_WEBSITE', 'www.elkinsrevenue.com').lower()
    agency_phone = CONFIG.get('AGENCY_PHONE', '917-327-0636')
    agency_email = CONFIG.get('AGENCY_EMAIL', 'lorren@elkinsrevenue.com')
    contact_line = f"WEB: {agency_web}    |    PHONE: {agency_phone}    |    EMAIL: {agency_email}"
    
    bbox_cont = draw.textbbox((0, 0), contact_line, font=f_cta_contact)
    cont_w = bbox_cont[2] - bbox_cont[0]
    draw.text(((W - cont_w) // 2, foot_y + 95), contact_line, fill=COLOR_COBALT, font=f_cta_contact)

    # Save output to single-page PDF
    img.save(out_pdf_path, "PDF", resolution=300.0)
    print(f"  -> Updated Executive Scorecard PDF successfully created: {out_pdf_path}")
    return out_pdf_path
# ==============================================================================
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
    """Syncs lead audit records exclusively to Google Sheets without creating a CSV."""
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
        df = pd.DataFrame(records)
        headers = list(df.columns)

        if not sheet.get_all_values():
            sheet.append_row(headers)

        sheet.append_rows(df.astype(str).values.tolist())
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
            out_scorecard = str(CONFIG["OUTPUT_DIR"] / f"{clean_name}_diagnostic_scorecard.pdf")
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
