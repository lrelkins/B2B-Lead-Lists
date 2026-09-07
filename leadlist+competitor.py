import os
import re
import json
import time
import smtplib
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

# Optional: Google Sheets & Slides API
try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
    from googleapiclient.discovery import build
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
    
    # Google Places API
    "GOOGLE_PLACES_KEY": os.getenv("GOOGLE_PLACES_KEY"),

    # Executive Email & Decision-Maker Discovery Keys
    "APOLLO_API_KEY": os.getenv("APOLLO_API_KEY"),
    "HUNTER_API_KEY": os.getenv("HUNTER_API_KEY"),
    
    # TTS Settings: "google" (free preview) or "elevenlabs" (final production)
    "TTS_ENGINE": os.getenv("TTS_ENGINE", "google"),
    "ELEVENLABS_KEY": os.getenv("ELEVENLABS_KEY", "your-elevenlabs-key"),
    "VOICE_ID": "nPczCjzI2devNBz1zQrb",  # Brian (Executive Narrative)

    # Brand Identity & Contact Assets
    "BRAND_PRIMARY": "ELKINS & CO.",
    "BRAND_SUBTITLE": "REVENUE STRATEGIES",
    "AGENCY_NAME": "ELKINS & CO · REVENUE STRATEGIES",
    "AGENCY_PHONE": "917-327-0636",
    "AGENCY_EMAIL": "lorren@elkinsrevenue.com",
    "AGENCY_WEBSITE": "www.elkinsrevenue.com",
      
    # Email SMTP Settings
    "SMTP_SERVER": "smtp.gmail.com",
    "SMTP_PORT": 465,
    "SENDER_EMAIL": "your-email@domain.com",
    "SENDER_PASSWORD": "your-app-password",

    # Google Sheets & Slides Integration
    "GOOGLE_SHEET_NAME": "Prospecting Pipeline & Audit Data",
    "GOOGLE_SHEETS_CREDENTIALS_JSON": r"G:\My Drive\Elkins Revenue Consulting\AI Agent Scripts\Prospect Database\service_account.json",
    "GOOGLE_DRIVE_FOLDER_ID": "1r7k12ng7-AG2yRm4yDUxCwXOdtSlvlv6",
    "GOOGLE_SLIDES_PRESENTATION_ID": "1QtdJgcxAbQrtU4uo1OIEuJCCb87dy3CnB-yN6RuysDs",
    "FALLBACK_LOCAL_CSV": "prospecting_leads.csv",

    # Output Destination Directory for Rendered Assets
    "OUTPUT_DIR": Path(r"G:\My Drive\Elkins Revenue Consulting\AI Agent Scripts\ElkinsRev Prospect Videos")
}

try:
    CONFIG["OUTPUT_DIR"].mkdir(parents=True, exist_ok=True)
except Exception:
    CONFIG["OUTPUT_DIR"] = Path(__file__).resolve().parent / "output"
    CONFIG["OUTPUT_DIR"].mkdir(parents=True, exist_ok=True)

# Visual Design Palette: Clean Executive White & Dark Slate
STYLE = {
    "BG": (255, 255, 255),               # Pure White Canvas
    "CARD_BG": (248, 250, 252),          # Soft Gray Card Surface (#F8FAFC)
    "CARD_BORDER": (226, 232, 240),      # Subtle Border (#E2E8F0)
    "TEXT_MAIN": (15, 23, 42),           # Near Black / Dark Charcoal (#0F172A)
    "TEXT_MUTED": (51, 65, 85),          # Slate Body Text (#334155)
    "TEXT_FAINT": (100, 116, 139),       # Subtext Gray (#64748B)
    "ACCENT_BLUE": (37, 99, 235),        # Vibrant Primary Blue (#2563EB)
    "PILL_BG": (239, 246, 255),          # Light Blue Eyebrow Background (#EFF6FF)
    "DIVIDER": (203, 213, 225)           # Divider Rule (#CBD5E1)
}

# ==============================================================================
# 1. DISCOVERY, ENRICHMENT & SCRAPING ENGINE
# ==============================================================================
def find_businesses(category: str, location: str, limit: int = 1) -> list:
    """Discovers targets via Google Places API (New Text Search)."""
    api_key = CONFIG.get("GOOGLE_PLACES_KEY")
    if not api_key or api_key == "your-places-api-key":
        print("\n[CONFIG ERROR] Missing Google Places API Key in environment or CONFIG.")
        return []

    clamped_limit = max(1, min(limit, 20))
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.displayName,places.websiteUri,places.formattedAddress,places.rating,places.userRatingCount"
    }
    payload = {"textQuery": f"{category} in {location}", "maxResultCount": clamped_limit}

    try:
        res = requests.post(url, headers=headers, json=payload)
        if res.status_code != 200:
            print(f"\n[Google Places API Error {res.status_code}]: {res.text}")
            return []

        data = res.json()
        if "places" not in data or len(data["places"]) == 0:
            print(f"\n[INFO] No places returned by Google for query: '{category} in {location}'.")
            return []

        leads = []
        for place in data.get("places", []):
            leads.append({
                "name": place.get("displayName", {}).get("text", "Unknown"),
                "website": place.get("websiteUri", ""),
                "address": place.get("formattedAddress", ""),
                "rating": place.get("rating", 0),
                "review_count": place.get("userRatingCount", 0)
            })
        return leads

    except Exception as e:
        print(f"\n[Network Error during Places API call]: {e}")
        return []

def find_benchmark_competitor(category: str, location: str, prospect_name: str) -> dict:
    """Finds top competitor in the target region to serve as market benchmark."""
    peers = find_businesses(category, location, limit=5)
    candidates = [p for p in peers if p["name"].strip().lower() != prospect_name.strip().lower()]
    if candidates:
        return sorted(candidates, key=lambda x: (x.get("review_count", 0), x.get("rating", 0.0)), reverse=True)[0]
    return {
        "name": "Local Top Competitor",
        "website": "",
        "address": location,
        "rating": 4.8,
        "review_count": 185
    }

def extract_clean_domain(website_url: str) -> str:
    """Normalizes URLs to bare domain strings."""
    if not website_url:
        return ""
    parsed = urlparse(website_url)
    domain = parsed.netloc or parsed.path
    if domain.startswith("www."):
        domain = domain[4:]
    return domain.split("/")[0].strip().lower()

def query_apollo_decision_maker(domain: str) -> dict:
    """Queries Apollo.io API to identify executive decision maker."""
    api_key = CONFIG.get("APOLLO_API_KEY")
    if not api_key or not domain:
        return None

    endpoint = "https://api.apollo.io/v1/mixed_people/api_search"
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "X-Api-Key": api_key
    }
    payload = {
        "q_organization_domains_list": [domain],
        "person_titles": ["Owner", "Founder", "Co-Founder", "CEO", "President", "Managing Partner", "General Manager"],
        "page": 1,
        "per_page": 1
    }

    try:
        res = requests.post(endpoint, json=payload, headers=headers, timeout=10)
        if res.status_code == 200:
            people = res.json().get("people", [])
            if people:
                p = people[0]
                full_name = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
                return {
                    "name": full_name or "Business Leader",
                    "title": p.get("title", "Executive"),
                    "email": p.get("email")
                }
    except Exception as e:
        print(f"    [APOLLO LOOKUP ERROR]: {e}")
    return None

def query_hunter_decision_maker(domain: str) -> dict:
    """Queries Hunter.io Domain Search API as secondary enrichment fallback."""
    api_key = CONFIG.get("HUNTER_API_KEY")
    if not api_key or not domain:
        return None

    url = f"https://api.hunter.io/v2/domain-search?domain={domain}&seniority=executive&api_key={api_key}"
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            emails = res.json().get("data", {}).get("emails", [])
            if emails:
                top = emails[0]
                full_name = f"{top.get('first_name', '')} {top.get('last_name', '')}".strip()
                return {
                    "name": full_name or "Business Leader",
                    "title": top.get("position", "Owner"),
                    "email": top.get("value")
                }
    except Exception as e:
        print(f"    [HUNTER LOOKUP ERROR]: {e}")
    return None

def find_decision_maker(website_url: str, fallback_scraped_email: str) -> dict:
    """Cascading decision maker finder: Apollo -> Hunter -> Direct Scrape fallback."""
    domain = extract_clean_domain(website_url)

    apollo_result = query_apollo_decision_maker(domain)
    if apollo_result:
        raw_email = apollo_result.get("email")
        if raw_email and "email_not_unlocked" not in raw_email and "@" in raw_email:
            print(f"    [ENRICHMENT: APOLLO] Unlocked email: {raw_email}")
            return {
                "name": apollo_result["name"],
                "title": apollo_result["title"],
                "email": raw_email,
                "source": "Apollo.io (Enriched)"
            }
        else:
            print(f"    [ENRICHMENT: APOLLO] Found {apollo_result['name']} (Email locked -> Falling back)")
            email = fallback_scraped_email if fallback_scraped_email != "Not Listed" else None
            return {
                "name": apollo_result["name"],
                "title": apollo_result["title"],
                "email": email or "Not Listed",
                "source": "Apollo.io (Name Only)"
            }

    hunter_result = query_hunter_decision_maker(domain)
    if hunter_result:
        raw_email = hunter_result.get("email")
        if raw_email and "@" in raw_email:
            print(f"    [ENRICHMENT: HUNTER] Unlocked email: {raw_email}")
            return {
                "name": hunter_result["name"],
                "title": hunter_result["title"],
                "email": raw_email,
                "source": "Hunter.io (Enriched)"
            }
        else:
            email = fallback_scraped_email if fallback_scraped_email != "Not Listed" else None
            return {
                "name": hunter_result["name"],
                "title": hunter_result["title"],
                "email": email or "Not Listed",
                "source": "Hunter.io (Name Only)"
            }

    return {
        "name": "Leadership",
        "title": "Owner / Executive",
        "email": fallback_scraped_email,
        "source": "Direct Scrape" if fallback_scraped_email != "Not Listed" else "Unresolved"
    }

def capture_site_assets_playwright(website_url: str, screenshot_path: str = "prospect_homepage.png", logo_path: str = "prospect_logo_temp.png") -> dict:
    """Captures 1920x1080 viewport using anti-detection and logo fallback."""
    result = {"screenshot_path": None, "logo_path": None}
    if not website_url:
        return result

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--no-sandbox"
                ]
            )
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                locale="en-US",
                timezone_id="America/New_York"
            )
            page = context.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

            response = page.goto(website_url, timeout=25000, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)

            status = response.status if response else 0
            page_title = page.title().lower()

            if status != 403 and "403 forbidden" not in page_title and "access denied" not in page_title:
                page.screenshot(path=screenshot_path, full_page=False)
                result["screenshot_path"] = screenshot_path

                logo_selectors = [
                    'header img[src*="logo" i]', 'nav img[src*="logo" i]',
                    'a[class*="brand" i] img', 'a[class*="logo" i] img',
                    'img[alt*="logo" i]', 'img[src*="logo" i]'
                ]
                for sel in logo_selectors:
                    el = page.locator(sel).first
                    if el.count() > 0 and el.is_visible():
                        box = el.bounding_box()
                        if box and box["width"] > 20 and box["height"] > 10:
                            el.screenshot(path=logo_path)
                            result["logo_path"] = logo_path
                            break
            browser.close()
    except Exception as e:
        print(f"    [PLAYWRIGHT WARNING] Stealth browsing failed: {e}")

    if not result["logo_path"] or not os.path.exists(logo_path):
        try:
            domain = urlparse(website_url).netloc or website_url
            clean_domain = domain.replace("www.", "")
            fallback_url = f"https://t2.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL&url=https://{clean_domain}&size=128"
            r = requests.get(fallback_url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200 and len(r.content) > 600:
                with open(logo_path, "wb") as f:
                    f.write(r.content)
                result["logo_path"] = logo_path
        except Exception:
            pass

    return result

def scrape_site_footprint(website_url: str) -> dict:
    """Scrapes homepage HTML for emails, social links, logo, and technical SEO signals."""
    details = {
        "email": "Not Listed",
        "social_links": [],
        "load_speed_sec": 0.0,
        "content_snippet": "",
        "missing_elements": [],
        "has_lead_form": False,
        "has_click_to_call": False,
        "has_schema": False,
        "has_meta_desc": False,
        "is_mobile_responsive": False,
        "logo_img_path": "prospect_logo_temp.png"
    }
    if not website_url:
        return details

    try:
        start_time = requests.compat.time.time()
        resp = requests.get(website_url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        load_time = round(requests.compat.time.time() - start_time, 2)
        details["load_speed_sec"] = load_time

        soup = BeautifulSoup(resp.text, "html.parser")

        emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', resp.text)
        valid_emails = [e for e in emails if not e.endswith(('.png', '.jpg', '.webp', '.svg'))]
        if valid_emails:
            details["email"] = valid_emails[0]

        for link in soup.find_all("a", href=True):
            href = link["href"].lower()
            for platform in ["facebook.com", "instagram.com", "linkedin.com", "youtube.com", "tiktok.com"]:
                if platform in href and href not in details["social_links"]:
                    details["social_links"].append(href)

        has_form = bool(soup.find_all("form"))
        details["has_lead_form"] = has_form
        if not has_form:
            details["missing_elements"].append("No Direct Lead Capture Form")

        has_tel = bool(soup.find("a", href=re.compile(r"^tel:")))
        details["has_click_to_call"] = has_tel
        if not has_tel:
            details["missing_elements"].append("No Tap-to-Call Link")

        if not soup.find_all("h1"):
            details["missing_elements"].append("Missing H1 Header")

        meta_desc = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
        has_desc = bool(meta_desc and meta_desc.get("content", "").strip())
        details["has_meta_desc"] = has_desc
        if not has_desc:
            details["missing_elements"].append("Missing Meta Description")

        schema_tags = soup.find_all("script", type="application/ld+json")
        has_schema = any("schema.org" in tag.text.lower() for tag in schema_tags)
        details["has_schema"] = has_schema
        if not has_schema:
            details["missing_elements"].append("Missing Structured Schema (JSON-LD)")

        viewport = soup.find("meta", attrs={"name": re.compile(r"^viewport$", re.I)})
        details["is_mobile_responsive"] = bool(viewport)
        if not viewport:
            details["missing_elements"].append("Missing Mobile Viewport Tag")

        body_text = ' '.join([p.get_text() for p in soup.find_all(['p', 'h1', 'h2'])])
        details["content_snippet"] = body_text[:1500]

        logo_url = None
        icon_tag = soup.find("link", rel=lambda x: x and ("icon" in x.lower() or "apple-touch-icon" in x.lower()))
        if icon_tag and icon_tag.get("href"):
            logo_url = urljoin(website_url, icon_tag["href"])
        else:
            img_tag = soup.find("img", src=lambda x: x and any(k in x.lower() for k in ["logo", "brand", "header"]))
            if img_tag and img_tag.get("src"):
                logo_url = urljoin(website_url, img_tag["src"])

        if logo_url:
            r_img = requests.get(logo_url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
            if r_img.status_code == 200 and len(r_img.content) > 500:
                with open(details["logo_img_path"], "wb") as f:
                    f.write(r_img.content)

    except Exception:
        details["missing_elements"].append("Website Inaccessible/Slow")

    return details

# ==============================================================================
# 2. AUDIT & OUTREACH COMPOSITION (NRP CLUSTER WITH COMPETITOR AUDIT)
# ==============================================================================
def call_nrp_llm(prompt: str) -> str:
    """Sends prompt to your custom NRP Nautilus vLLM endpoint."""
    headers = {
        "Authorization": f"Bearer {CONFIG['NRP_API_KEY']}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": CONFIG["MODEL_NAME"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2
    }
    res = requests.post(f"{CONFIG['NRP_ENDPOINT']}/chat/completions", headers=headers, json=payload)
    res.raise_for_status()
    return res.json()["choices"][0]["message"]["content"]

def audit_and_compose(lead: dict, footprint: dict, contact: dict, rival: dict, rival_fp: dict) -> dict:
    """Evaluates the primary target against its rival and drafts comparison copy."""
    audit_prompt = f"""
    Analyze {lead['name']} and compare it against its key local competitor {rival['name']}. Address findings directly to {contact['name']} ({contact['title']}). Return a strict JSON object.

    TARGET COMPANY:
    - Name: {lead['name']}
    - Website: {lead['website']}
    - Reviews: {lead.get('rating', 0)} stars ({lead.get('review_count', 0)} reviews)
    - Page Speed: {footprint['load_speed_sec']}s
    - Has Form: {footprint.get('has_lead_form', False)} | Has Call: {footprint.get('has_click_to_call', False)} | Has Schema: {footprint.get('has_schema', False)}
    - UX Flags: {footprint['missing_elements']}

    BENCHMARK COMPETITOR:
    - Name: {rival['name']}
    - Reviews: {rival.get('rating', 0)} stars ({rival.get('review_count', 0)} reviews)
    - Page Speed: {rival_fp.get('load_speed_sec', 1.5)}s
    - Has Form: {rival_fp.get('has_lead_form', False)} | Has Call: {rival_fp.get('has_click_to_call', False)} | Has Schema: {rival_fp.get('has_schema', False)}

    CRITICAL RULES:
    1. 'intro_voiceover' MUST start with:
       "We compared your business to one of your local competitors, {rival['name']}. This brief report highlights some of the key differences."
    2. 'intro_bullets' must be 3 concise bullets (max 10-12 words each) summarizing the scope.
    3. 'competitor_slide' is a dedicated slide comparing {lead['name']} vs {rival['name']}, highlighting specific gaps where {rival['name']} captures market share.
    4. 'video_script' must have 4 core diagnostic body slides (each with 'eyebrow', 'slide_title', 3 'bullets', and ~15s 'voiceover').

    Required JSON format:
    {{
      "scores": {{
         "seo": <1-100>,
         "social_media": <1-100>,
         "website_speed": <1-100>,
         "content_clarity": <1-100>,
         "lead_conversion": <1-100>,
         "reputation": <1-100>
      }},
      "core_weakness": "<diagnostic bottleneck>",
      "quick_win": "<immediate high-impact fix>",
      "solution": "<targeted strategic revenue solution>",
      "email_subject": "<custom subject referencing bottleneck or rival>",
      "email_body": "<under 120 words addressed to {contact['name']}, referencing {rival['name']} comparison, proposing quick win, and referencing brief>",
      "intro_voiceover": "We compared your business to one of your local competitors, {rival['name']}. This brief report highlights some of the key differences. <spoken narrative outlining findings and recovery roadmap>",
      "intro_bullets": [
         "Audited page speed, lead flow, search visibility & mobile UX",
         "Identified competitive leakage points favoring {rival['name']}",
         "Delivering immediate friction-free strategic recovery roadmap"
      ],
      "competitor_slide": {{
         "eyebrow": "02 / LOCAL MARKET BENCHMARK",
         "slide_title": "Competitive Head-to-Head Analysis",
         "target_label": "{lead['name']}",
         "target_stats": [
            "Google: {lead.get('rating', 0)}★ ({lead.get('review_count', 0)} reviews)",
            "Page Load: {footprint['load_speed_sec']}s",
            "Lead Capture: {'Active Form' if footprint.get('has_lead_form') else 'No Direct Form'}"
         ],
         "rival_label": "{rival['name']}",
         "rival_stats": [
            "Google: {rival.get('rating', 0)}★ ({rival.get('review_count', 0)} reviews)",
            "Page Load: {rival_fp.get('load_speed_sec', 1.5)}s",
            "Lead Capture: {'Active Form' if rival_fp.get('has_lead_form') else 'No Direct Form'}"
         ],
         "bullets": [
            "<bullet 1 contrasting prospect gap against competitor>",
            "<bullet 2 showing high-intent mobile search leakage to competitor>",
            "<bullet 3 actionable strategic opportunity to leapfrog them>"
         ],
         "voiceover": "<15 seconds narrative contrasting {lead['name']} with {rival['name']} and explaining how demand leaks>"
      }},
      "video_script": [
         {{
           "eyebrow": "01 / KEY FINDING",
           "slide_title": "What Could be Holding You Back",
           "bullets": ["<bullet 1>", "<bullet 2>", "<bullet 3>"],
           "voiceover": "<15s narrative>"
         }},
         {{
           "eyebrow": "03 / PIPELINE IMPACT",
           "slide_title": "Lead Leakage",
           "bullets": ["<bullet 1>", "<bullet 2>", "<bullet 3>"],
           "voiceover": "<15s narrative>"
         }},
         {{
           "eyebrow": "04 / A FEW FIXES",
           "slide_title": "High-ROI Impact",
           "bullets": ["<bullet 1>", "<bullet 2>", "<bullet 3>"],
           "voiceover": "<15s narrative>"
         }},
         {{
           "eyebrow": "05 / RECOMMENDATIONS",
           "slide_title": "Next Steps",
           "bullets": ["<bullet 1>", "<bullet 2>", "<bullet 3>"],
           "voiceover": "<12s narrative>"
         }}
      ],
      "outro_voiceover": "To review the complete diagnostic dataset or explore turnkey implementation, connect with our leadership team at elkinsrevenue.com."
    }}
    Return ONLY pure, valid JSON.
    """
    raw_response = call_nrp_llm(audit_prompt)
    clean_json = re.search(r'\{.*\}', raw_response, re.DOTALL).group(0)
    return json.loads(clean_json)

# ==============================================================================
# 3. SLIDE DECK RENDERER (Clean Light Mode with Competitor Card)
# ==============================================================================
def load_font(font_name_list, size):
    for name in font_name_list:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()

def draw_agency_brand(draw, img, content_x, header_y):
    font_main = load_font(["arialbd.ttf", "segoeuib.ttf", "helvetica.ttf"], 30)
    font_sub = load_font(["arialbd.ttf", "segoeuib.ttf", "helvetica.ttf"], 20)

    primary_text = CONFIG.get("BRAND_PRIMARY", "ELKINS & CO.")
    draw.text((content_x, header_y), primary_text, fill=STYLE["TEXT_MAIN"], font=font_main)
    bbox_main = draw.textbbox((content_x, header_y), primary_text, font=font_main)
    main_w = bbox_main[2] - bbox_main[0]

    divider_x = content_x + main_w + 20
    draw.line([(divider_x, header_y + 4), (divider_x, header_y + 32)], fill=STYLE["DIVIDER"], width=2)

    sub_text = CONFIG.get("BRAND_SUBTITLE", "REVENUE STRATEGIES")
    draw.text((divider_x + 20, header_y + 7), sub_text, fill=STYLE["ACCENT_BLUE"], font=font_sub)

def create_title_slide(lead_name: str, contact_name: str, bullets: list, output_path: str, prospect_logo_path: str):
    """Renders executive white intro slide personalized to the decision maker."""
    W, H = 1920, 1080
    img = Image.new("RGB", (W, H), color=STYLE["BG"])
    draw = ImageDraw.Draw(img)

    margin_x, margin_y = 100, 70
    draw.rounded_rectangle([margin_x, margin_y, W - margin_x, H - margin_y], radius=24, fill=STYLE["CARD_BG"], outline=STYLE["CARD_BORDER"], width=2)

    content_x = margin_x + 100
    header_y = margin_y + 60
    draw_agency_brand(draw, img, content_x, header_y)

    font_pill = load_font(["arialbd.ttf", "segoeuib.ttf"], 22)
    font_title = load_font(["arialbd.ttf", "segoeuib.ttf"], 66)
    font_sub = load_font(["arial.ttf", "segoeui.ttf"], 34)
    font_bullet = load_font(["arial.ttf", "segoeui.ttf"], 38)
    font_badge = load_font(["arialbd.ttf", "segoeuib.ttf"], 32)

    # Executive Briefing Pill
    pill_y = header_y + 90
    pill_text = "CONFIDENTIAL BRIEFING"
    bbox_pill = draw.textbbox((0, 0), pill_text, font=font_pill)
    text_w = bbox_pill[2] - bbox_pill[0]
    
    pill_padding_x = 60
    pill_w = text_w + (pill_padding_x * 2)
    pill_h = 52
    
    draw.rounded_rectangle([content_x, pill_y, content_x + pill_w, pill_y + pill_h], radius=12, fill=STYLE["PILL_BG"], outline=STYLE["ACCENT_BLUE"], width=1)
    draw.text((content_x + pill_padding_x, pill_y + 13), pill_text, fill=STYLE["ACCENT_BLUE"], font=font_pill)

    # Prospect Logo or PROSPECT AUDIT Badge
    logo_y = pill_y + pill_h + 30
    placed_prospect_logo = False
    if prospect_logo_path and os.path.exists(prospect_logo_path):
        try:
            p_logo = Image.open(prospect_logo_path).convert("RGBA")
            p_logo.thumbnail((260, 80), Image.Resampling.LANCZOS)
            img.paste(p_logo, (content_x, logo_y), p_logo)
            placed_prospect_logo = True
        except Exception:
            pass

    if not placed_prospect_logo:
        badge_text = "PROSPECT AUDIT"
        bbox_badge = draw.textbbox((0, 0), badge_text, font=font_badge)
        badge_text_w = bbox_badge[2] - bbox_badge[0]
        badge_text_h = bbox_badge[3] - bbox_badge[1]
        
        badge_pad_x = 44
        badge_pad_y = 14
        badge_w = badge_text_w + (badge_pad_x * 2)
        badge_h = badge_text_h + (badge_pad_y * 2)
        
        draw.rounded_rectangle(
            [content_x, logo_y, content_x + badge_w, logo_y + badge_h],
            radius=10,
            fill=STYLE["CARD_BORDER"],
            outline=STYLE["DIVIDER"],
            width=1
        )
        draw.text((content_x + badge_pad_x, logo_y + badge_pad_y), badge_text, fill=STYLE["TEXT_FAINT"], font=font_badge)

    # Title & Subtitle (Personalized)
    title_y = logo_y + 90
    draw.text((content_x, title_y), "Digital Diagnostic & Revenue Roadmap", fill=STYLE["TEXT_MAIN"], font=font_title)
    draw.line((content_x, title_y + 85, content_x + 280, title_y + 85), fill=STYLE["ACCENT_BLUE"], width=6)

    sub_y = title_y + 105
    target_display = f"{contact_name} & Leadership at: {lead_name}" if contact_name not in ["Leadership", "Business Leader"] else f"Leadership at: {lead_name}"
    draw.text((content_x, sub_y), f"Prepared Exclusively for: {target_display}", fill=STYLE["TEXT_MUTED"], font=font_sub)

    # Render Scope Summary Bullets
    bullet_y = sub_y + 70
    fallback_bullets = [
        "Audited website performance, lead flow & search visibility",
        "Pinpointed key leakage points reducing buyer conversions",
        "Proposing immediate high-ROI strategic implementation plan"
    ]
    render_bullets = bullets if bullets and len(bullets) >= 3 else fallback_bullets

    for b in render_bullets[:3]:
        draw.ellipse([content_x + 4, bullet_y + 12, content_x + 20, bullet_y + 28], fill=STYLE["ACCENT_BLUE"])
        draw.text((content_x + 40, bullet_y), b, fill=STYLE["TEXT_MAIN"], font=font_bullet)
        bullet_y += 58

    img.save(output_path)

def draw_standard_footer(draw, W, H, margin_x, margin_y, content_x, content_max_w):
    """Renders standard footer with Elkins & Co | REVENUE STRATEGIES centered."""
    footer_y = H - margin_y - 60
    draw.line((content_x, footer_y - 18, content_max_w, footer_y - 18), fill=STYLE["CARD_BORDER"], width=1)
    
    font_footer = load_font(["arial.ttf", "segoeui.ttf"], 20)
    font_brand_main = load_font(["arialbd.ttf", "segoeuib.ttf"], 20)
    font_brand_sub = load_font(["arial.ttf", "segoeui.ttf"], 18)

    draw.text((content_x, footer_y), "CONFIDENTIAL", fill=STYLE["TEXT_FAINT"], font=font_footer)

    primary_text = CONFIG.get("BRAND_PRIMARY", "ELKINS & CO.")
    sub_text = CONFIG.get("BRAND_SUBTITLE", "REVENUE STRATEGIES")
    
    bbox_p = draw.textbbox((0, 0), primary_text, font=font_brand_main)
    w_p = bbox_p[2] - bbox_p[0]
    bbox_s = draw.textbbox((0, 0), sub_text, font=font_brand_sub)
    w_s = bbox_s[2] - bbox_s[0]
    
    divider_pad = 14
    total_center_w = w_p + (divider_pad * 2) + 2 + w_s
    center_x = (W - total_center_w) // 2

    draw.text((center_x, footer_y), primary_text, fill=STYLE["TEXT_MAIN"], font=font_brand_main)
    div_x = center_x + w_p + divider_pad
    draw.line([(div_x, footer_y + 2), (div_x, footer_y + 20)], fill=STYLE["DIVIDER"], width=2)
    draw.text((div_x + divider_pad, footer_y + 1), sub_text, fill=STYLE["ACCENT_BLUE"], font=font_brand_sub)

    site_url = CONFIG.get("AGENCY_WEBSITE", "WWW.ELKINSREVENUE.COM").upper()
    bbox_site = draw.textbbox((0, 0), site_url, font=font_footer)
    site_w = bbox_site[2] - bbox_site[0]
    draw.text((content_max_w - site_w, footer_y), site_url, fill=STYLE["ACCENT_BLUE"], font=font_footer)

def create_homepage_slide(screenshot_path: str, business_name: str, output_path: str):
    """Renders the captured above-the-fold homepage with guaranteed footer clearance."""
    W, H = 1920, 1080
    img = Image.new("RGB", (W, H), color=STYLE["BG"])
    draw = ImageDraw.Draw(img)

    margin_x, margin_y = 100, 70
    draw.rounded_rectangle([margin_x, margin_y, W - margin_x, H - margin_y], radius=24, fill=STYLE["CARD_BG"], outline=STYLE["CARD_BORDER"], width=2)

    content_x = margin_x + 100
    content_max_w = W - margin_x - 100

    font_pill = load_font(["arialbd.ttf", "segoeuib.ttf"], 22)
    font_title = load_font(["arialbd.ttf", "segoeuib.ttf"], 50)

    pill_y = margin_y + 55
    pill_text = "CURRENT DIGITAL ASSET · HOMEPAGE BASELINE"
    bbox_pill = draw.textbbox((0, 0), pill_text, font=font_pill)
    text_w = bbox_pill[2] - bbox_pill[0]
    pill_w = text_w + 60
    draw.rounded_rectangle([content_x, pill_y, content_x + pill_w, pill_y + 44], radius=10, fill=STYLE["PILL_BG"], outline=STYLE["ACCENT_BLUE"], width=1)
    draw.text((content_x + 30, pill_y + 10), pill_text, fill=STYLE["ACCENT_BLUE"], font=font_pill)

    title_y = pill_y + 60
    draw.text((content_x, title_y), f"Live Capture: {business_name}", fill=STYLE["TEXT_MAIN"], font=font_title)
    draw.line((content_x, title_y + 68, content_x + 220, title_y + 68), fill=STYLE["ACCENT_BLUE"], width=5)

    shot_y = title_y + 90
    bar_h = 28
    shot_w, shot_h = 1380, 500

    if screenshot_path and os.path.exists(screenshot_path):
        try:
            with Image.open(screenshot_path) as shot:
                shot_thumb = shot.resize((shot_w, shot_h), Image.Resampling.LANCZOS)
                draw.rounded_rectangle([content_x, shot_y, content_x + shot_w, shot_y + shot_h + bar_h], radius=12, fill=STYLE["BG"], outline=STYLE["CARD_BORDER"], width=2)
                draw.rectangle([content_x, shot_y + bar_h, content_x + shot_w, shot_y + bar_h + 2], fill=STYLE["DIVIDER"])

                for idx, c in enumerate([(239, 68, 68), (245, 158, 11), (34, 197, 94)]):
                    draw.ellipse([content_x + 16 + (idx * 20), shot_y + 8, content_x + 28 + (idx * 20), shot_y + 20], fill=c)

                img.paste(shot_thumb, (content_x, shot_y + bar_h))
        except Exception as e:
            print(f"    [SLIDE ERROR] Could not paste homepage screenshot: {e}")

    draw_standard_footer(draw, W, H, margin_x, margin_y, content_x, content_max_w)
    img.save(output_path)

def create_competitor_slide(comp_data: dict, output_path: str):
    """Renders head-to-head competitor comparison slide with adjusted header/footer."""
    W, H = 1920, 1080
    img = Image.new("RGB", (W, H), color=STYLE["BG"])
    draw = ImageDraw.Draw(img)

    margin_x, margin_y = 100, 70
    draw.rounded_rectangle([margin_x, margin_y, W - margin_x, H - margin_y], radius=24, fill=STYLE["CARD_BG"], outline=STYLE["CARD_BORDER"], width=2)

    content_x = margin_x + 100
    content_max_w = W - margin_x - 100

    font_pill = load_font(["arialbd.ttf", "segoeuib.ttf"], 22)
    font_title = load_font(["arialbd.ttf", "segoeuib.ttf"], 58)
    font_col_header = load_font(["arialbd.ttf", "segoeuib.ttf"], 28)
    font_stat = load_font(["arial.ttf", "segoeui.ttf"], 24)
    font_bullet = load_font(["arial.ttf", "segoeui.ttf"], 36)

    eyebrow = comp_data.get("eyebrow", "02 / LOCAL BENCHMARK").upper()
    pill_y = margin_y + 55
    bbox = draw.textbbox((0, 0), eyebrow, font=font_pill)
    pw = (bbox[2] - bbox[0]) + 80
    draw.rounded_rectangle([content_x, pill_y, content_x + pw, pill_y + 46], radius=10, fill=STYLE["PILL_BG"], outline=STYLE["ACCENT_BLUE"], width=1)
    draw.text((content_x + 40, pill_y + 11), eyebrow, fill=STYLE["ACCENT_BLUE"], font=font_pill)

    title_y = pill_y + 68
    draw.text((content_x, title_y), comp_data.get("slide_title", "Competitive Head-to-Head Analysis"), fill=STYLE["TEXT_MAIN"], font=font_title)
    draw.line((content_x, title_y + 78, content_x + 240, title_y + 78), fill=STYLE["ACCENT_BLUE"], width=6)

    card_y = title_y + 110
    total_w = content_max_w - content_x
    half_w = (total_w - 40) // 2
    card_h = 175

    draw.rounded_rectangle([content_x, card_y, content_x + half_w, card_y + card_h], radius=14, fill=STYLE["BG"], outline=STYLE["CARD_BORDER"], width=2)
    t_name = comp_data.get("target_label", "Your Business")[:34]
    draw.text((content_x + 30, card_y + 20), f"TARGET: {t_name}", fill=STYLE["TEXT_MAIN"], font=font_col_header)
    stat_y = card_y + 64
    for stat in comp_data.get("target_stats", [])[:3]:
        draw.text((content_x + 30, stat_y), f"• {stat}", fill=STYLE["TEXT_MUTED"], font=font_stat)
        stat_y += 30

    rival_x = content_x + half_w + 40
    draw.rounded_rectangle([rival_x, card_y, rival_x + half_w, card_y + card_h], radius=14, fill=STYLE["BG"], outline=STYLE["ACCENT_BLUE"], width=2)
    r_name = comp_data.get("rival_label", "Top Rival")[:34]
    draw.text((rival_x + 30, card_y + 20), f"BENCHMARK: {r_name}", fill=STYLE["ACCENT_BLUE"], font=font_col_header)
    r_stat_y = card_y + 64
    for stat in comp_data.get("rival_stats", [])[:3]:
        draw.text((rival_x + 30, r_stat_y), f"• {stat}", fill=STYLE["TEXT_MUTED"], font=font_stat)
        r_stat_y += 30

    bullet_y = card_y + card_h + 45
    for b in comp_data.get("bullets", [])[:3]:
        draw.ellipse([content_x + 4, bullet_y + 14, content_x + 20, bullet_y + 30], fill=STYLE["ACCENT_BLUE"])
        draw.text((content_x + 40, bullet_y), b, fill=STYLE["TEXT_MUTED"], font=font_bullet)
        bullet_y += 54

    draw_standard_footer(draw, W, H, margin_x, margin_y, content_x, content_max_w)
    img.save(output_path)

def create_body_slide(eyebrow: str, title: str, bullets: list, output_path: str):
    """Renders executive diagnostic body slides with top-aligned eyebrow and centered footer brand."""
    W, H = 1920, 1080
    img = Image.new("RGB", (W, H), color=STYLE["BG"])
    draw = ImageDraw.Draw(img)

    margin_x, margin_y = 100, 70
    draw.rounded_rectangle([margin_x, margin_y, W - margin_x, H - margin_y], radius=24, fill=STYLE["CARD_BG"], outline=STYLE["CARD_BORDER"], width=2)

    font_pill = load_font(["arialbd.ttf", "segoeuib.ttf"], 22)
    font_title = load_font(["arialbd.ttf", "segoeuib.ttf"], 68)
    font_bullet = load_font(["arial.ttf", "segoeui.ttf"], 40)

    content_x = margin_x + 100
    content_max_w = W - margin_x - 100

    pill_y = margin_y + 55
    pill_text = eyebrow.upper()
    bbox = draw.textbbox((0, 0), pill_text, font=font_pill)
    text_w = bbox[2] - bbox[0]
    pill_w = text_w + 80
    draw.rounded_rectangle([content_x, pill_y, content_x + pill_w, pill_y + 48], radius=10, fill=STYLE["PILL_BG"], outline=STYLE["ACCENT_BLUE"], width=1)
    draw.text((content_x + 40, pill_y + 12), pill_text, fill=STYLE["ACCENT_BLUE"], font=font_pill)

    title_y = pill_y + 75
    draw.text((content_x, title_y), title, fill=STYLE["TEXT_MAIN"], font=font_title)
    draw.line((content_x, title_y + 92, content_x + 240, title_y + 92), fill=STYLE["ACCENT_BLUE"], width=6)

    bullet_y = title_y + 140
    for b in bullets[:4]:
        draw.ellipse([content_x + 4, bullet_y + 16, content_x + 22, bullet_y + 34], fill=STYLE["ACCENT_BLUE"])
        words = b.split()
        lines, current_line = [], []
        for w in words:
            if len(" ".join(current_line + [w])) < 60:
                current_line.append(w)
            else:
                lines.append(" ".join(current_line))
                current_line = [w]
        lines.append(" ".join(current_line))

        for line in lines:
            draw.text((content_x + 46, bullet_y), line, fill=STYLE["TEXT_MUTED"], font=font_bullet)
            bullet_y += 54
        bullet_y += 24

    draw_standard_footer(draw, W, H, margin_x, margin_y, content_x, content_max_w)
    img.save(output_path)

def create_outro_slide(output_path: str):
    W, H = 1920, 1080
    img = Image.new("RGB", (W, H), color=STYLE["BG"])
    draw = ImageDraw.Draw(img)

    margin_x, margin_y = 100, 70
    draw.rounded_rectangle([margin_x, margin_y, W - margin_x, H - margin_y], radius=24, fill=STYLE["CARD_BG"], outline=STYLE["CARD_BORDER"], width=2)

    font_title = load_font(["arialbd.ttf", "segoeuib.ttf"], 70)
    font_sub = load_font(["arial.ttf", "segoeui.ttf"], 38)
    font_contact_title = load_font(["arialbd.ttf", "segoeuib.ttf"], 32)
    font_contact_val = load_font(["arial.ttf", "segoeui.ttf"], 34)

    content_x = margin_x + 100
    header_y = margin_y + 60
    draw_agency_brand(draw, img, content_x, header_y)

    title_y = header_y + 130
    draw.text((content_x, title_y), "Ready to Boost Digital Performance?", fill=STYLE["TEXT_MAIN"], font=font_title)
    draw.line((content_x, title_y + 95, content_x + 280, title_y + 95), fill=STYLE["ACCENT_BLUE"], width=6)
    
    sub_y = title_y + 125
    draw.text((content_x, sub_y), "Let's discuss these findings and develop a plan.", fill=STYLE["TEXT_MUTED"], font=font_sub)

    box_y = sub_y + 90
    box_w = W - (content_x * 2)
    draw.rounded_rectangle([content_x, box_y, content_x + box_w, box_y + 175], radius=16, fill=STYLE["BG"], outline=STYLE["CARD_BORDER"], width=2)

    col_w = box_w // 3
    draw.text((content_x + 40, box_y + 35), "VISIT US ONLINE", fill=STYLE["TEXT_FAINT"], font=font_contact_title)
    draw.text((content_x + 40, box_y + 88), CONFIG["AGENCY_WEBSITE"], fill=STYLE["ACCENT_BLUE"], font=font_contact_val)

    draw.text((content_x + col_w + 40, box_y + 35), "DIRECT INQUIRIES", fill=STYLE["TEXT_FAINT"], font=font_contact_title)
    draw.text((content_x + col_w + 40, box_y + 88), CONFIG["AGENCY_PHONE"], fill=STYLE["TEXT_MAIN"], font=font_contact_val)

    draw.text((content_x + (col_w * 2) + 40, box_y + 35), "EMAIL OUR TEAM", fill=STYLE["TEXT_FAINT"], font=font_contact_title)
    draw.text((content_x + (col_w * 2) + 40, box_y + 88), CONFIG["AGENCY_EMAIL"], fill=STYLE["TEXT_MAIN"], font=font_contact_val)

    img.save(output_path)

# ==============================================================================
# 4. AUDIO, VIDEO, PDF & GOOGLE SLIDES ENGINE
# ==============================================================================
def generate_tts_google(text: str, output_audio_path: str):
    tts = gTTS(text=text, lang="en", tld="com", slow=False)
    tts.save(output_audio_path)

def generate_voiceover(text: str, output_audio_path: str):
    engine = CONFIG.get("TTS_ENGINE", "google").lower()

    if engine == "elevenlabs":
        api_key = os.getenv("ELEVENLABS_KEY") or CONFIG.get("ELEVENLABS_KEY")
        if not api_key or "your-" in api_key:
            print("    [VOICE] ElevenLabs key missing/invalid -> Falling back to Google TTS (Free)")
            generate_tts_google(text, output_audio_path)
            return

        print("    [VOICE] Rendering with ElevenLabs...")
        voice_id = CONFIG.get("VOICE_ID", "nPczCjzI2devNBz1zQrb")
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json"
        }
        payload = {
            "text": text,
            "model_id": "eleven_turbo_v2_5",
            "voice_settings": {
                "stability": 0.45,
                "similarity_boost": 0.80,
                "style": 0.20,
                "use_speaker_boost": True
            }
        }
        res = requests.post(url, headers=headers, json=payload)
        if res.status_code != 200:
            print(f"    [VOICE WARNING] ElevenLabs error {res.status_code}: Falling back to Google TTS.")
            generate_tts_google(text, output_audio_path)
            return

        with open(output_audio_path, "wb") as f:
            f.write(res.content)
    else:
        print("    [VOICE] Rendering with Google TTS (Free)...")
        generate_tts_google(text, output_audio_path)

def assemble_pitch_video(company_name: str, contact_name: str, audit_data: dict, prospect_logo_path: str, homepage_shot_path: str, output_video_path: str) -> str:
    """Builds complete executive video presentation including competitor slide."""
    clips = []
    temp_files = []

    # 1. Title Slide
    intro_img = "slide_intro.png"
    intro_audio = "audio_intro.mp3"
    temp_files.extend([intro_img, intro_audio])
    create_title_slide(company_name, contact_name, audit_data.get("intro_bullets", []), intro_img, prospect_logo_path)
    generate_voiceover(audit_data.get("intro_voiceover", ""), intro_audio)
    a_clip = AudioFileClip(intro_audio)
    clips.append(ImageClip(intro_img).with_duration(a_clip.duration).with_audio(a_clip))

    # 2. Homepage Capture Slide
    if homepage_shot_path and os.path.exists(homepage_shot_path):
        home_img = "slide_homepage.png"
        home_audio = "audio_homepage.mp3"
        temp_files.extend([home_img, home_audio])
        create_homepage_slide(homepage_shot_path, company_name, home_img)
        home_vo = f"Here is the current above-the-fold landing experience for {company_name}, analyzed for load speed, conversion friction, and inquiry retention."
        generate_voiceover(home_vo, home_audio)
        a_clip_home = AudioFileClip(home_audio)
        clips.append(ImageClip(home_img).with_duration(a_clip_home.duration).with_audio(a_clip_home))

    # 3. Competitor Comparison Slide
    if "competitor_slide" in audit_data:
        comp_img = "slide_competitor.png"
        comp_audio = "audio_competitor.mp3"
        temp_files.extend([comp_img, comp_audio])
        create_competitor_slide(audit_data["competitor_slide"], comp_img)
        generate_voiceover(audit_data["competitor_slide"].get("voiceover", ""), comp_audio)
        a_clip_comp = AudioFileClip(comp_audio)
        clips.append(ImageClip(comp_img).with_duration(a_clip_comp.duration).with_audio(a_clip_comp))

    # 4. Diagnostic Body Slides
    for i, slide in enumerate(audit_data.get("video_script", [])):
        s_img = f"slide_{i}.png"
        s_audio = f"audio_{i}.mp3"
        temp_files.extend([s_img, s_audio])
        create_body_slide(
            eyebrow=slide.get("eyebrow", f"0{i+1} / STRATEGIC BRIEF"),
            title=slide["slide_title"],
            bullets=slide.get("bullets", []),
            output_path=s_img
        )
        generate_voiceover(slide["voiceover"], s_audio)
        a_clip = AudioFileClip(s_audio)
        clips.append(ImageClip(s_img).with_duration(a_clip.duration).with_audio(a_clip))

    # 5. Outro Slide
    outro_img = "slide_outro.png"
    outro_audio = "audio_outro.mp3"
    temp_files.extend([outro_img, outro_audio])
    create_outro_slide(outro_img)
    generate_voiceover(audit_data.get("outro_voiceover", f"Visit {CONFIG['AGENCY_WEBSITE']} to connect with our strategic team."), outro_audio)
    a_clip = AudioFileClip(outro_audio)
    clips.append(ImageClip(outro_img).with_duration(a_clip.duration).with_audio(a_clip))

    # Stitch Video
    final_video = concatenate_videoclips(clips, method="compose")
    final_video.write_videofile(output_video_path, fps=24, codec="libx264", audio_codec="aac", logger=None)

    for f in temp_files + [prospect_logo_path, homepage_shot_path]:
        if f and os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                pass

    return output_video_path

def assemble_pitch_pdf(company_name: str, contact_name: str, audit_data: dict, prospect_logo_path: str, homepage_shot_path: str, output_pdf_path: str) -> str:
    """Renders high-res slides including competitor card and saves as PDF deck."""
    slide_images = []
    temp_files = []

    # 1. Title Slide
    intro_img = "slide_intro.png"
    temp_files.append(intro_img)
    create_title_slide(company_name, contact_name, audit_data.get("intro_bullets", []), intro_img, prospect_logo_path)
    slide_images.append(Image.open(intro_img).convert("RGB"))

    # 2. Homepage Capture Slide
    if homepage_shot_path and os.path.exists(homepage_shot_path):
        home_img = "slide_homepage.png"
        temp_files.append(home_img)
        create_homepage_slide(homepage_shot_path, company_name, home_img)
        slide_images.append(Image.open(home_img).convert("RGB"))

    # 3. Competitor Comparison Slide
    if "competitor_slide" in audit_data:
        comp_img = "slide_competitor.png"
        temp_files.append(comp_img)
        create_competitor_slide(audit_data["competitor_slide"], comp_img)
        slide_images.append(Image.open(comp_img).convert("RGB"))

    # 4. Diagnostic Body Slides
    for i, slide in enumerate(audit_data.get("video_script", [])):
        s_img = f"slide_{i}.png"
        temp_files.append(s_img)
        create_body_slide(
            eyebrow=slide.get("eyebrow", f"0{i+1} / STRATEGIC BRIEF"),
            title=slide["slide_title"],
            bullets=slide.get("bullets", []),
            output_path=s_img
        )
        slide_images.append(Image.open(s_img).convert("RGB"))

    # 5. Outro Slide
    outro_img = "slide_outro.png"
    temp_files.append(outro_img)
    create_outro_slide(outro_img)
    slide_images.append(Image.open(outro_img).convert("RGB"))

    if slide_images:
        first_page = slide_images[0]
        remaining_pages = slide_images[1:]
        first_page.save(
            output_pdf_path,
            save_all=True,
            append_images=remaining_pages,
            resolution=100.0
        )
        print(f"  -> Generated presentation PDF deck: {output_pdf_path}")

    for f in temp_files + [prospect_logo_path, homepage_shot_path]:
        if f and os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                pass

    return output_pdf_path

def assemble_pitch_google_slides(company_name: str, target: dict, rival: dict, audit: dict) -> str:
    """Populates the shared Google Slide deck with custom audit slides using the service account."""
    creds_file = CONFIG.get("GOOGLE_SHEETS_CREDENTIALS_JSON", "")
    pres_id = CONFIG.get("GOOGLE_SLIDES_PRESENTATION_ID", "").strip()

    if not os.path.exists(creds_file) or not pres_id:
        print("    [GOOGLE SLIDES ERROR] Credentials file or GOOGLE_SLIDES_PRESENTATION_ID missing.")
        return "N/A (Missing Setup)"

    scope = [
        "https://www.googleapis.com/auth/presentations",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(creds_file, scope)
    slides_service = build("slides", "v1", credentials=creds)

    curr_pres = slides_service.presentations().get(presentationId=pres_id).execute()
    existing_slides = curr_pres.get("slides", [])
    old_slide_ids = [s["objectId"] for s in existing_slides]

    requests_list = []

    # Slide 1: Intro / Benchmark
    ts = int(time.time())
    s1_id = f"intro_{ts}"
    t1_id = f"title_{ts}"
    b1_id = f"body_{ts}"
    intro_body = (
        f"• Audited page speed, lead flow, search visibility, mobile compatibility\n"
        f"• Identified competitive leakage points favoring {rival.get('name', 'Competitor')}\n"
        f"• Proposing immediate friction-free strategic roadmap to recover revenue"
    )
    requests_list.extend([
        {"createSlide": {"objectId": s1_id, "insertionIndex": len(old_slide_ids)}},
        {
            "createShape": {
                "objectId": t1_id,
                "shapeType": "TEXT_BOX",
                "elementProperties": {
                    "pageObjectId": s1_id,
                    "size": {"width": {"magnitude": 600, "unit": "PT"}, "height": {"magnitude": 60, "unit": "PT"}},
                    "transform": {"scaleX": 1, "scaleY": 1, "translateX": 50, "translateY": 50, "unit": "PT"}
                }
            }
        },
        {"insertText": {"objectId": t1_id, "text": f"Performance Review: {company_name}"}},
        {
            "createShape": {
                "objectId": b1_id,
                "shapeType": "TEXT_BOX",
                "elementProperties": {
                    "pageObjectId": s1_id,
                    "size": {"width": {"magnitude": 600, "unit": "PT"}, "height": {"magnitude": 250, "unit": "PT"}},
                    "transform": {"scaleX": 1, "scaleY": 1, "translateX": 50, "translateY": 130, "unit": "PT"}
                }
            }
        },
        {"insertText": {"objectId": b1_id, "text": intro_body}}
    ])

    # Slide 2: Head-to-Head Comparison
    if "competitor_slide" in audit:
        c_slide = audit["competitor_slide"]
        cs_id = f"comp_{ts}"
        ct_id = f"ctitle_{ts}"
        cb_id = f"cbody_{ts}"
        comp_body = (
            f"Target ({target.get('name', 'Your Business')}): {target.get('rating', 0)}★ ({target.get('review_count', 0)} reviews)\n"
            f"Benchmark ({rival.get('name', 'Competitor')}): {rival.get('rating', 0)}★ ({rival.get('review_count', 0)} reviews)\n\n"
            + "\n".join([f"• {b}" for b in c_slide.get("bullets", [])])
        )
        requests_list.extend([
            {"createSlide": {"objectId": cs_id, "insertionIndex": len(old_slide_ids) + 1}},
            {
                "createShape": {
                    "objectId": ct_id,
                    "shapeType": "TEXT_BOX",
                    "elementProperties": {
                        "pageObjectId": cs_id,
                        "size": {"width": {"magnitude": 600, "unit": "PT"}, "height": {"magnitude": 60, "unit": "PT"}},
                        "transform": {"scaleX": 1, "scaleY": 1, "translateX": 50, "translateY": 50, "unit": "PT"}
                    }
                }
            },
            {"insertText": {"objectId": ct_id, "text": c_slide.get("slide_title", "Market Benchmark Analysis")}},
            {
                "createShape": {
                    "objectId": cb_id,
                    "shapeType": "TEXT_BOX",
                    "elementProperties": {
                        "pageObjectId": cs_id,
                        "size": {"width": {"magnitude": 600, "unit": "PT"}, "height": {"magnitude": 250, "unit": "PT"}},
                        "transform": {"scaleX": 1, "scaleY": 1, "translateX": 50, "translateY": 120, "unit": "PT"}
                    }
                }
            },
            {"insertText": {"objectId": cb_id, "text": comp_body}}
        ])

    # Slide 3-6: Diagnostic Body Slides
    start_idx = len(old_slide_ids) + (2 if "competitor_slide" in audit else 1)
    for i, slide in enumerate(audit.get("video_script", [])):
        slide_page_id = f"diag_{i}_{ts}"
        title_box_id = f"dtitle_{i}_{ts}"
        body_box_id = f"dbody_{i}_{ts}"
        bullet_text = "\n".join([f"• {b}" for b in slide.get("bullets", [])])

        requests_list.extend([
            {"createSlide": {"objectId": slide_page_id, "insertionIndex": start_idx + i}},
            {
                "createShape": {
                    "objectId": title_box_id,
                    "shapeType": "TEXT_BOX",
                    "elementProperties": {
                        "pageObjectId": slide_page_id,
                        "size": {"width": {"magnitude": 600, "unit": "PT"}, "height": {"magnitude": 50, "unit": "PT"}},
                        "transform": {"scaleX": 1, "scaleY": 1, "translateX": 50, "translateY": 50, "unit": "PT"}
                    }
                }
            },
            {"insertText": {"objectId": title_box_id, "text": f"{slide.get('eyebrow', 'FINDING')} — {slide.get('slide_title', '')}"}},
            {
                "createShape": {
                    "objectId": body_box_id,
                    "shapeType": "TEXT_BOX",
                    "elementProperties": {
                        "pageObjectId": slide_page_id,
                        "size": {"width": {"magnitude": 600, "unit": "PT"}, "height": {"magnitude": 250, "unit": "PT"}},
                        "transform": {"scaleX": 1, "scaleY": 1, "translateX": 50, "translateY": 120, "unit": "PT"}
                    }
                }
            },
            {"insertText": {"objectId": body_box_id, "text": bullet_text}}
        ])

    # Outro Slide
    s_out_id = f"outro_{ts}"
    t_out_id = f"otitle_{ts}"
    b_out_id = f"obody_{ts}"
    outro_text = (
        f"Ready to boost digital performance?\n\n"
        f"Agency: {CONFIG.get('AGENCY_NAME', 'ELKINS & CO')}\n"
        f"Website: {CONFIG.get('AGENCY_WEBSITE', 'www.elkinsrevenue.com')}\n"
        f"Phone: {CONFIG.get('AGENCY_PHONE', '')}\n"
        f"Email: {CONFIG.get('AGENCY_EMAIL', '')}"
    )
    requests_list.extend([
        {"createSlide": {"objectId": s_out_id, "insertionIndex": start_idx + len(audit.get("video_script", []))}},
        {
            "createShape": {
                "objectId": t_out_id,
                "shapeType": "TEXT_BOX",
                "elementProperties": {
                    "pageObjectId": s_out_id,
                    "size": {"width": {"magnitude": 600, "unit": "PT"}, "height": {"magnitude": 50, "unit": "PT"}},
                    "transform": {"scaleX": 1, "scaleY": 1, "translateX": 50, "translateY": 50, "unit": "PT"}
                }
            }
        },
        {"insertText": {"objectId": t_out_id, "text": "Strategic Next Steps"}},
        {
            "createShape": {
                "objectId": b_out_id,
                "shapeType": "TEXT_BOX",
                "elementProperties": {
                    "pageObjectId": s_out_id,
                    "size": {"width": {"magnitude": 600, "unit": "PT"}, "height": {"magnitude": 250, "unit": "PT"}},
                    "transform": {"scaleX": 1, "scaleY": 1, "translateX": 50, "translateY": 120, "unit": "PT"}
                }
            }
        },
        {"insertText": {"objectId": b_out_id, "text": outro_text}}
    ])

    for old_id in old_slide_ids:
        requests_list.append({"deleteObject": {"objectId": old_id}})

    slides_service.presentations().batchUpdate(presentationId=pres_id, body={"requests": requests_list}).execute()

    deck_url = f"https://docs.google.com/presentation/d/{pres_id}/edit"
    print(f"    -> Successfully updated Google Slide Deck: {deck_url}")
    return deck_url

# ==============================================================================
# 5. DATA PERSISTENCE: GOOGLE SHEETS & LOCAL CSV
# ==============================================================================
def save_records_to_google_sheet(records: list):
    """Appends records to Google Sheets if credentials exist; falls back to local CSV."""
    if not records:
        return

    df = pd.DataFrame(records)
    creds_file = CONFIG.get("GOOGLE_SHEETS_CREDENTIALS_JSON", "")

    print("\n--- GOOGLE SHEETS DIAGNOSTIC ---")
    print(f"1. GSPREAD_AVAILABLE: {GSPREAD_AVAILABLE}")
    print(f"2. Creds File Path:   {repr(creds_file)}")
    print(f"3. File Exists Check: {os.path.exists(creds_file) if creds_file else False}")
    print("--------------------------------\n")

    if not GSPREAD_AVAILABLE:
        print("[DIAGNOSTIC REASON] gspread or oauth2client failed to import.")
    elif not os.path.exists(creds_file):
        print(f"[DIAGNOSTIC REASON] Python cannot find the file at: {creds_file}")

    if GSPREAD_AVAILABLE and os.path.exists(creds_file):
        try:
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_name(creds_file, scope)
            client = gspread.authorize(creds)
            
            sheet_name = CONFIG["GOOGLE_SHEET_NAME"]
            try:
                sheet = client.open(sheet_name).sheet1
            except gspread.SpreadsheetNotFound:
                spreadsheet = client.create(sheet_name)
                sheet = spreadsheet.sheet1
            
            first_row = sheet.row_values(1)
            headers = list(df.columns)
            clean_df = df.astype(str)
            data_rows = clean_df.values.tolist()
            
            if not any(cell.strip() for cell in first_row):
                sheet.update(range_name='1:1', values=[headers])
                sheet.append_rows(data_rows)
                print(f"\n[GOOGLE SHEETS] Created new headers and appended {len(records)} record(s) to '{sheet_name}'.")
            else:
                sheet.append_rows(data_rows)
                print(f"\n[GOOGLE SHEETS] Successfully appended {len(records)} record(s) to '{sheet_name}'.")
            return

        except Exception as e:
            print(f"\n[GOOGLE SHEETS ERROR] Failed communicating with Google Sheets: {e}")
            print("Falling back to local CSV append...")

    csv_file = CONFIG["FALLBACK_LOCAL_CSV"]
    file_exists = os.path.exists(csv_file)
    df.to_csv(csv_file, mode="a", header=not file_exists, index=False)
    print(f"\n[LOCAL CSV] Saved {len(records)} record(s) to '{csv_file}'.")

# ==============================================================================
# 6. EMAIL TRANSMISSION
# ==============================================================================
def send_prospect_email(to_email: str, subject: str, body: str, attachment_path: str):
    """Sends the outreach email with the MP4 video or PDF deck attached."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = CONFIG["SENDER_EMAIL"]
    msg["To"] = to_email
    msg.set_content(body)
    
    if attachment_path and os.path.exists(attachment_path):
        with open(attachment_path, "rb") as f:
            file_data = f.read()
            file_name = os.path.basename(attachment_path)
        
        if attachment_path.lower().endswith(".pdf"):
            msg.add_attachment(file_data, maintype="application", subtype="pdf", filename=file_name)
        else:
            msg.add_attachment(file_data, maintype="video", subtype="mp4", filename=file_name)
        
    with smtplib.SMTP_SSL(CONFIG["SMTP_SERVER"], CONFIG["SMTP_PORT"]) as server:
        server.login(CONFIG["SENDER_EMAIL"], CONFIG["SENDER_PASSWORD"])
        server.send_message(msg)

# ==============================================================================
# 7. MAIN PIPELINE
# ==============================================================================
def main():
    print("\n--- B2B Prospecting & Strategic Presentation Pipeline ---")
    print("Choose presentation output mode:")
    print("  [1] MP4 Video (with Voiceover Audio)")
    print("  [2] PDF Slide Deck (Visual Slides Only, No Audio)")
    print("  [3] Data Only (Skip Assets, Append Directly to Sheet)")
    print("  [4] Google Slides (Editable slides)")
    
    output_choice = input("Select Output: [1] Video  [2] PDF  [3] Data Only  [4] Google Slides [Default 1]: ").strip() or "1"
    create_video = (output_choice == "1")
    create_pdf = (output_choice == "2")
    create_slides = (output_choice == "4")

    if create_video:
        mode_choice = input("Select audio mode: [1] Free Preview (Google)  [2] Final Production (ElevenLabs): ").strip()
        CONFIG["TTS_ENGINE"] = "elevenlabs" if mode_choice == "2" else "google"
        print(f"-> Mode: Video | Voice Engine: {CONFIG['TTS_ENGINE'].upper()}")
    elif create_pdf:
        print("-> Mode: PDF Presentation Deck (No Voiceover Audio Needed)")
    elif create_slides:
        print("-> Mode: Google Slides (Presentation will be created in Google Drive)")
    else:
        print("-> Mode: Data Only (Bypassing visual assets, saving straight to Google Sheet)")
    
    print("\nSelect Prospect Mode:")
    print("  [1] Batch Discovery via Google Places")
    print("  [2] Single Prospect by Website URL")
    run_mode = input("Select Mode [1 or 2, Default 1]: ").strip() or "1"

    if run_mode == "2":
        single_url = input("\nEnter the prospect's full website URL: ").strip()
        if not single_url.startswith("http"):
            single_url = "https://" + single_url

        # Guess business name from domain
        clean_domain = urlparse(single_url).netloc.replace("www.", "")
        name_guess = clean_domain.split(".")[0].replace("-", " ").title()

        name_input = input(f"Enter prospect business name [Default: '{name_guess}']: ").strip()
        prospect_name = name_input if name_input else name_guess

        # Needed so find_benchmark_competitor can find a local rival for comparison
        category = input("Enter business category for competitor benchmark (e.g., HVAC, Optometrist): ").strip()
        location = input("Enter city/region for competitor benchmark (e.g., Estero FL, Naples FL): ").strip()

        leads = [{
            "name": prospect_name,
            "website": single_url,
            "address": location,
            "rating": 0,
            "review_count": 0
        }]
    else:

        category = input("\nEnter target business category (e.g., HVAC, Optometrist, Roofing): ").strip()
        location = input("Enter target geographic region (e.g., Estero FL, Naples FL): ").strip()

        count_input = input("How many businesses to return and process? [Default 1, Max 20]: ").strip()
        try:
            limit = int(count_input) if count_input else 1
            limit = max(1, limit)
        except ValueError:
            limit = 1

        print(f"\n[1/5] Finding up to {limit} business(es) for '{category}' in '{location}'...")
        leads = find_businesses(category, location, limit=limit)
    
    if not leads:
        print("\n[TERMINATED] No leads were retrieved. Inspect search criteria or Places API key.")
        return
    
    records = []
    
    for lead in leads:
        name = lead["name"]
        website = lead["website"]
        print(f"\nProcessing: {name} ({website})")
        
        # 1. Scrape standard website footprint
        print("  -> Scraping target website footprint...")
        footprint = scrape_site_footprint(website)

        # 2. Competitor Discovery & Scraping
        print("  -> Discovering local benchmark competitor...")
        rival = find_benchmark_competitor(category, location, name)
        print(f"     Benchmark Rival: {rival['name']} ({rival.get('website', 'No URL')})")
        rival_fp = scrape_site_footprint(rival.get("website", ""))

        # 3. Key Executive Discovery
        print("  -> Discovering key executive decision-maker...")
        contact = find_decision_maker(website, footprint["email"])
        print(f"     Target: {contact['name']} | Title: {contact['title']} | Email: {contact['email']} | Provider: {contact['source']}")

        active_logo = None
        active_shot = None

        # 4. Asset Capture for Video/PDF
        if create_video or create_pdf:
            print("  -> Capturing above-the-fold screenshot and brand logo via Playwright...")
            pw_assets = capture_site_assets_playwright(website)
            active_logo = pw_assets["logo_path"] if pw_assets.get("logo_path") else footprint.get("logo_img_path")
            active_shot = pw_assets.get("screenshot_path")

        # 5. LLM Audit with Head-to-Head Competitor Gap Analysis
        print("  -> Running competitive gap audit via NRP cluster...")
        audit = audit_and_compose(lead, footprint, contact, rival, rival_fp)

        clean_name = re.sub(r'[^a-zA-Z0-9]', '', name)
        email_recipient = contact["email"]
        generated_asset_path = "N/A (Skipped)"
        delivery_status = "Skipped"

        # 6. Build Output Assets (Video / PDF / Google Slides / Data Only)
        if create_video:
            video_filename = f"{clean_name}_audit_brief.mp4"
            generated_asset_path = str(CONFIG["OUTPUT_DIR"] / video_filename)
            print(f"  -> Rendering complete executive video to: {generated_asset_path}")
            assemble_pitch_video(name, contact["name"], audit, active_logo, active_shot, generated_asset_path)

            delivery_status = "Skipped (No Email)"
            if email_recipient != "Not Listed" and "@" in email_recipient:
                print(f"  -> Sending prospecting email to {contact['name']} ({email_recipient})...")
                try:
                    send_prospect_email(email_recipient, audit["email_subject"], audit["email_body"], generated_asset_path)
                    delivery_status = f"Email Sent with Video to {contact['name']}"
                except Exception as e:
                    print(f"  -> Email delivery failed: {e}")
                    delivery_status = f"Failed ({e})"

        elif create_pdf:
            pdf_filename = f"{clean_name}_audit_deck.pdf"
            generated_asset_path = str(CONFIG["OUTPUT_DIR"] / pdf_filename)
            print(f"  -> Rendering slide deck PDF to: {generated_asset_path}")
            assemble_pitch_pdf(name, contact["name"], audit, active_logo, active_shot, generated_asset_path)

            delivery_status = "Skipped (No Email)"
            if email_recipient != "Not Listed" and "@" in email_recipient:
                print(f"  -> Sending prospecting email to {contact['name']} ({email_recipient})...")
                try:
                    send_prospect_email(email_recipient, audit["email_subject"], audit["email_body"], generated_asset_path)
                    delivery_status = f"Email Sent with PDF Deck to {contact['name']}"
                except Exception as e:
                    print(f"  -> Email delivery failed: {e}")
                    delivery_status = f"Failed ({e})"

        elif create_slides:
            print("  -> Creating native Google Slides deck in Google Drive...")
            generated_asset_path = assemble_pitch_google_slides(name, lead, rival, audit)

            delivery_status = "Skipped (No Email)"
            if email_recipient != "Not Listed" and "@" in email_recipient:
                print(f"  -> Sending prospecting email to {contact['name']} ({email_recipient})...")
                try:
                    slide_email_body = f"{audit['email_body']}\n\nYou can review your interactive audit presentation here:\n{generated_asset_path}"
                    send_prospect_email(email_recipient, audit["email_subject"], slide_email_body, "")
                    delivery_status = f"Email Sent with Google Slide Link to {contact['name']}"
                except Exception as e:
                    print(f"  -> Email delivery failed: {e}")
                    delivery_status = f"Failed ({e})"

        else:
            delivery_status = "Skipped (Data Only Mode)"
            generated_asset_path = "N/A (Data Only)"
        
        records.append({
            "Business Name": name,
            "Decision Maker": contact["name"],
            "Title": contact["title"],
            "Data Source": contact["source"],
            "Address": lead["address"],
            "Website": website,
            "Contact Email": email_recipient,
            "Google Rating": lead.get("rating", 0),
            "Review Count": lead.get("review_count", 0),
            "Benchmark Competitor": rival["name"],
            "Competitor Rating": rival.get("rating", 0),
            "Competitor Reviews": rival.get("review_count", 0),
            "SEO Score": audit["scores"]["seo"],
            "Social Score": audit["scores"]["social_media"],
            "Speed Score": audit["scores"]["website_speed"],
            "Clarity Score": audit["scores"]["content_clarity"],
            "Lead Conversion Score": audit["scores"].get("lead_conversion", 0),
            "Reputation Score": audit["scores"].get("reputation", 0),
            "Has Lead Form": footprint.get("has_lead_form", False),
            "Has Tap-to-Call": footprint.get("has_click_to_call", False),
            "Has Schema": footprint.get("has_schema", False),
            "Core Weakness": audit["core_weakness"],
            "Quick Win": audit.get("quick_win", ""),
            "Proposed Solution": audit["solution"],
            "Email Subject": audit["email_subject"],
            "Email Status": delivery_status,
            "Presentation Asset": generated_asset_path
        })
        
    save_records_to_google_sheet(records)
    print("\n[SUCCESS] Pipeline run complete.")

if __name__ == "__main__":
    main()