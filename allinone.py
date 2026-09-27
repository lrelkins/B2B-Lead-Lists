import os
import re
import json
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

# Optional: Google Sheets Integration
try:
    import gspread
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
    "GOOGLE_SHEET_NAME": "Prospect Audit",
    "GOOGLE_SHEETS_CREDENTIALS_JSON": r"G:\My Drive\Elkins Revenue Consulting\AI Agent Scripts\Prospect Database\service_account.json",
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
        start = requests.compat.time.time()
        resp = requests.get(website_url, timeout=8, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        details["load_speed_sec"] = round(requests.compat.time.time() - start, 2)
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
    payload = {"model": CONFIG["MODEL_NAME"], "messages": [{"role": "user", "content": prompt}], "temperature": 0.2}
    res = requests.post(f"{CONFIG['NRP_ENDPOINT']}/chat/completions", headers=headers, json=payload, timeout=35)
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

def generate_audit(target: dict, target_fp: dict, contact: dict, rival: dict = None, rival_fp: dict = None) -> dict:
    has_rival = rival is not None
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
        clean = re.search(r'\{.*\}', raw, re.DOTALL).group(0)
        return json.loads(clean)
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
def load_font(size: int, bold: bool = False):
    names = ["arialbd.ttf", "segoeuib.ttf"] if bold else ["arial.ttf", "segoeui.ttf"]
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except Exception:
            continue
    return ImageFont.load_default()

def draw_card_base(draw, W, H):
    """Clean Executive White Canvas (#FFFFFF) with Soft Card (#F8FAFC)."""
    draw.rectangle([0, 0, W, H], fill=STYLE["BG"])
    mx, my = 100, 60
    draw.rounded_rectangle([mx, my, W - mx, H - my], radius=24, fill=STYLE["CARD_BG"], outline=STYLE["CARD_BORDER"], width=2)
    # Brand Lockup
    draw.text((mx + 70, my + 60), CONFIG["BRAND_PRIMARY"], fill=STYLE["TEXT_DARK"], font=load_font(26, bold=True))
    bbox = draw.textbbox((mx + 70, my + 60), CONFIG["BRAND_PRIMARY"], font=load_font(26, bold=True))
    draw.text((bbox[2] + 16, my + 64), CONFIG["BRAND_SUBTITLE"], fill=STYLE["BLUE"], font=load_font(18, bold=True))

def render_title_slide(lead_name: str, contact_name: str, bullets: list, out_path: str, logo_path: str = None):
    """Slide 1: Executive Title Slide."""
    W, H = 1920, 1080
    img = Image.new("RGB", (W, H), color=STYLE["BG"])
    draw = ImageDraw.Draw(img)
    draw_card_base(draw, W, H)

    start_x = 170
    draw.rounded_rectangle([start_x, 185, start_x + 540, 225], radius=6, fill=STYLE["PILL_BG"], outline=(219, 234, 254), width=1)
    draw.text((start_x + 20, 193), "CONFIDENTIAL EXECUTIVE BRIEFING · RESEARCH & STRATEGY", fill=STYLE["BLUE"], font=load_font(16, bold=True))

    draw.text((start_x, 260), "Digital Diagnostic & Revenue Roadmap", fill=STYLE["TEXT_DARK"], font=load_font(56, bold=True))
    target_str = f"Prepared for: {contact_name} & Leadership at {lead_name}" if contact_name not in ["Leadership", "Business Leader"] else f"Prepared Exclusively for: {lead_name}"
    draw.text((start_x, 340), target_str, fill=STYLE["TEXT_MUTED"], font=load_font(28))

    bullet_y = 440
    font_b = load_font(32)
    for b in bullets[:3]:
        draw.ellipse([start_x, bullet_y + 18, start_x + 16, bullet_y + 34], fill=STYLE["BLUE"])
        draw.text((start_x + 36, bullet_y), b, fill=STYLE["TEXT_BODY"], font=font_b)
        bullet_y += 75

    # Prospect Logo or Rounded Badge Fallback
    logo_drawn = False
    if logo_path and os.path.exists(logo_path):
        try:
            with Image.open(logo_path) as l_img:
                l_img = l_img.convert("RGBA")
                l_img.thumbnail((300, 100), Image.Resampling.LANCZOS)
                img.paste(l_img, (W - 480, 180), l_img)
                logo_drawn = True
        except Exception:
            logo_drawn = False
    if not logo_drawn:
        draw.rounded_rectangle([W - 480, 180, W - 220, 240], radius=12, fill=(241, 245, 249), outline=STYLE["DIVIDER"], width=1)
        draw.text((W - 430, 198), "PROSPECT", fill=STYLE["TEXT_MUTED"], font=load_font(20, bold=True))

    draw.text((start_x, H - 120), "CONFIDENTIAL · PREPARED FOR EXECUTIVE REVIEW", fill=STYLE["TEXT_MUTED"], font=load_font(18, bold=True))
    draw.text((W - 480, H - 120), CONFIG["AGENCY_WEBSITE"], fill=STYLE["BLUE"], font=load_font(18, bold=True))
    img.save(out_path)

def render_viewport_screenshot_slide(screenshot_path: str, bullets: list, out_path: str):
    """Slide 2: Live Viewport Screenshot Mockup."""
    W, H = 1920, 1080
    img = Image.new("RGB", (W, H), color=STYLE["BG"])
    draw = ImageDraw.Draw(img)
    draw_card_base(draw, W, H)

    start_x = 170
    current_y = 195

    # Dynamic Eyebrow Pill
    pill_text = "02 / VISUAL CONVERSION AUDIT"
    font_pill = load_font(18, bold=True)
    p_box = draw.textbbox((0, 0), pill_text, font=font_pill)
    pw, ph = p_box[2] - p_box[0], p_box[3] - p_box[1]
    draw.rounded_rectangle([start_x, current_y, start_x + pw + 36, current_y + ph + 20], radius=8, fill=STYLE["PILL_BG"], outline=(219, 234, 254), width=1)
    draw.text((start_x + 18, current_y + 10), pill_text, fill=STYLE["BLUE"], font=font_pill)

    current_y += ph + 55
    draw.text((start_x, current_y), "Above-the-Fold Viewport & Mobile Access", fill=STYLE["TEXT_DARK"], font=load_font(52, bold=True))

    # Left: Mockup Frame for Screenshot
    frame_x, frame_y, frame_w, frame_h = start_x, current_y + 90, 880, 520
    draw.rounded_rectangle([frame_x, frame_y, frame_x + frame_w, frame_y + frame_h], radius=16, fill=(255, 255, 255), outline=STYLE["DIVIDER"], width=2)
    # Browser Top Bar
    draw.rounded_rectangle([frame_x, frame_y, frame_x + frame_w, frame_y + 40], radius=16, fill=(241, 245, 249))
    draw.rectangle([frame_x, frame_y + 25, frame_x + frame_w, frame_y + 40], fill=(241, 245, 249))
    draw.ellipse([frame_x + 15, frame_y + 14, frame_x + 27, frame_y + 26], fill=(239, 68, 68))
    draw.ellipse([frame_x + 35, frame_y + 14, frame_x + 47, frame_y + 26], fill=(245, 158, 11))
    draw.ellipse([frame_x + 55, frame_y + 14, frame_x + 67, frame_y + 26], fill=(34, 197, 94))

    if screenshot_path and os.path.exists(screenshot_path):
        try:
            with Image.open(screenshot_path) as s_img:
                s_img = s_img.convert("RGB")
                shot_h = frame_h - 42
                s_img = s_img.resize((frame_w - 4, shot_h), Image.Resampling.LANCZOS)
                img.paste(s_img, (frame_x + 2, frame_y + 41))
        except Exception:
            draw.text((frame_x + 240, frame_y + 240), "[Viewport Capture Active]", fill=STYLE["TEXT_MUTED"], font=load_font(26))
    else:
        draw.text((frame_x + 240, frame_y + 240), "[Viewport Capture Active]", fill=STYLE["TEXT_MUTED"], font=load_font(26))

    # Right: Scannable Bullets
    right_x = start_x + frame_w + 70
    right_y = frame_y + 50
    font_b = load_font(30)
    for b in bullets[:3]:
        draw.ellipse([right_x, right_y + 18, right_x + 16, right_y + 34], fill=STYLE["BLUE"])
        draw.text((right_x + 36, right_y), b, fill=STYLE["TEXT_BODY"], font=font_b)
        right_y += 100

    draw.text((start_x, H - 120), "CONFIDENTIAL · PREPARED FOR EXECUTIVE REVIEW", fill=STYLE["TEXT_MUTED"], font=load_font(18, bold=True))
    draw.text((W - 480, H - 120), CONFIG["AGENCY_WEBSITE"], fill=STYLE["BLUE"], font=load_font(18, bold=True))
    img.save(out_path)

def render_competitor_slide(target: dict, target_fp: dict, rival: dict, rival_fp: dict, bullets: list, out_path: str):
    """Slide 3: Head-to-Head Competitor Benchmark."""
    W, H = 1920, 1080
    img = Image.new("RGB", (W, H), color=STYLE["BG"])
    draw = ImageDraw.Draw(img)
    draw_card_base(draw, W, H)

    start_x = 170
    current_y = 195

    pill_text = "03 / COMPETITIVE BENCHMARK"
    font_pill = load_font(18, bold=True)
    p_box = draw.textbbox((0, 0), pill_text, font=font_pill)
    pw, ph = p_box[2] - p_box[0], p_box[3] - p_box[1]
    draw.rounded_rectangle([start_x, current_y, start_x + pw + 36, current_y + ph + 20], radius=8, fill=STYLE["PILL_BG"], outline=(219, 234, 254), width=1)
    draw.text((start_x + 18, current_y + 10), pill_text, fill=STYLE["BLUE"], font=font_pill)

    current_y += ph + 55
    draw.text((start_x, current_y), "Local Market Benchmark Comparison", fill=STYLE["TEXT_DARK"], font=load_font(52, bold=True))

    card_y = current_y + 90
    card_w, card_h = 750, 240

    # Prospect Card
    draw.rounded_rectangle([start_x, card_y, start_x + card_w, card_y + card_h], radius=16, fill=(255, 255, 255), outline=STYLE["DIVIDER"], width=2)
    draw.text((start_x + 40, card_y + 30), f"YOUR BUSINESS: {target['name'][:30]}", fill=STYLE["TEXT_DARK"], font=load_font(24, bold=True))
    draw.text((start_x + 40, card_y + 85), f"Google Reviews: {target.get('rating', 0)}★ ({target.get('review_count', 0)} reviews)", fill=STYLE["TEXT_BODY"], font=load_font(22))
    draw.text((start_x + 40, card_y + 130), f"Mobile Page Load: {target_fp.get('load_speed_sec', 1.5)}s", fill=STYLE["TEXT_BODY"], font=load_font(22))
    draw.text((start_x + 40, card_y + 175), f"Lead Capture: {'Active Form & Call' if target_fp.get('has_lead_form') and target_fp.get('has_click_to_call') else 'Conversion Friction Present'}", fill=STYLE["RED"] if not target_fp.get('has_click_to_call') else STYLE["GREEN"], font=load_font(22, bold=True))

    # Rival Card
    rival_x = start_x + card_w + 60
    rival_name = rival["name"] if rival else "Local Benchmark Rival"
    draw.rounded_rectangle([rival_x, card_y, rival_x + card_w, card_y + card_h], radius=16, fill=(255, 255, 255), outline=STYLE["BLUE"], width=2)
    draw.text((rival_x + 40, card_y + 30), f"BENCHMARK: {rival_name[:30]}", fill=STYLE["BLUE"], font=load_font(24, bold=True))
    draw.text((rival_x + 40, card_y + 85), f"Google Reviews: {rival.get('rating', 4.8) if rival else 4.8}★ ({rival.get('review_count', 180) if rival else 180} reviews)", fill=STYLE["TEXT_BODY"], font=load_font(22))
    draw.text((rival_x + 40, card_y + 130), f"Mobile Page Load: {rival_fp.get('load_speed_sec', 1.2) if rival_fp else 1.2}s", fill=STYLE["TEXT_BODY"], font=load_font(22))
    draw.text((rival_x + 40, card_y + 175), "Lead Capture: Streamlined Mobile Funnel", fill=STYLE["GREEN"], font=load_font(22, bold=True))

    # Comparative Bullets
    bullet_y = card_y + card_h + 50
    font_b = load_font(30)
    for b in bullets[:3]:
        draw.ellipse([start_x, bullet_y + 18, start_x + 16, bullet_y + 34], fill=STYLE["BLUE"])
        draw.text((start_x + 36, bullet_y), b, fill=STYLE["TEXT_BODY"], font=font_b)
        bullet_y += 65

    draw.text((start_x, H - 120), "CONFIDENTIAL · PREPARED FOR EXECUTIVE REVIEW", fill=STYLE["TEXT_MUTED"], font=load_font(18, bold=True))
    draw.text((W - 480, H - 120), CONFIG["AGENCY_WEBSITE"], fill=STYLE["BLUE"], font=load_font(18, bold=True))
    img.save(out_path)

def render_bullet_slide(pill_text: str, main_title: str, bullets: list, out_path: str):
    """Slides 4-9: Core Diagnostic & Strategy Cards."""
    W, H = 1920, 1080
    img = Image.new("RGB", (W, H), color=STYLE["BG"])
    draw = ImageDraw.Draw(img)
    draw_card_base(draw, W, H)

    start_x = 170
    current_y = 195

    # Auto-Padding Pill
    font_pill = load_font(18, bold=True)
    p_box = draw.textbbox((0, 0), pill_text, font=font_pill)
    pw, ph = p_box[2] - p_box[0], p_box[3] - p_box[1]
    draw.rounded_rectangle([start_x, current_y, start_x + pw + 36, current_y + ph + 20], radius=8, fill=STYLE["PILL_BG"], outline=(219, 234, 254), width=1)
    draw.text((start_x + 18, current_y + 10), pill_text, fill=STYLE["BLUE"], font=font_pill)

    current_y += ph + 55
    draw.text((start_x, current_y), main_title, fill=STYLE["TEXT_DARK"], font=load_font(52, bold=True))

    current_y += 120
    font_b = load_font(34)
    for b in bullets[:3]:
        draw.ellipse([start_x, current_y + 20, start_x + 18, current_y + 38], fill=STYLE["BLUE"])
        draw.text((start_x + 40, current_y), b, fill=STYLE["TEXT_BODY"], font=font_b)
        current_y += 85

    draw.text((start_x, H - 120), "CONFIDENTIAL · PREPARED FOR EXECUTIVE REVIEW", fill=STYLE["TEXT_MUTED"], font=load_font(18, bold=True))
    draw.text((W - 480, H - 120), CONFIG["AGENCY_WEBSITE"], fill=STYLE["BLUE"], font=load_font(18, bold=True))
    img.save(out_path)

def render_outro_slide(out_path: str):
    """Slide 10: Call-To-Action & Contact Outro Card."""
    W, H = 1920, 1080
    img = Image.new("RGB", (W, H), color=STYLE["BG"])
    draw = ImageDraw.Draw(img)
    draw_card_base(draw, W, H)

    start_x = 170
    draw.text((start_x, 240), "Ready to Eliminate Digital Leakage?", fill=STYLE["TEXT_DARK"], font=load_font(58, bold=True))
    
    # Custom CTA Form Text
    draw.text((start_x, 330), CONFIG["CUSTOM_CTA"], fill=STYLE["BLUE"], font=load_font(30, bold=True))

    card_y = 440
    draw.rounded_rectangle([start_x, card_y, W - start_x, card_y + 260], radius=20, fill=(255, 255, 255), outline=STYLE["DIVIDER"], width=2)

    cy = card_y + 70
    draw.text((start_x + 60, cy), "VISIT US ONLINE", fill=STYLE["TEXT_MUTED"], font=load_font(20, bold=True))
    draw.text((start_x + 60, cy + 40), CONFIG["AGENCY_WEBSITE"].lower(), fill=STYLE["BLUE"], font=load_font(30, bold=True))

    draw.text((start_x + 550, cy), "DIRECT INQUIRIES", fill=STYLE["TEXT_MUTED"], font=load_font(20, bold=True))
    draw.text((start_x + 550, cy + 40), CONFIG["AGENCY_PHONE"], fill=STYLE["TEXT_DARK"], font=load_font(30, bold=True))

    draw.text((start_x + 1000, cy), "EMAIL OUR LEADERSHIP", fill=STYLE["TEXT_MUTED"], font=load_font(20, bold=True))
    draw.text((start_x + 1000, cy + 40), CONFIG["AGENCY_EMAIL"], fill=STYLE["TEXT_DARK"], font=load_font(30, bold=True))

    draw.text((start_x, H - 120), "CONFIDENTIAL · PREPARED FOR EXECUTIVE REVIEW", fill=STYLE["TEXT_MUTED"], font=load_font(18, bold=True))
    draw.text((W - 480, H - 120), CONFIG["AGENCY_WEBSITE"], fill=STYLE["BLUE"], font=load_font(18, bold=True))
    img.save(out_path)

# ==============================================================================
# 4. AUDIO & 10-SLIDE ASSET ASSEMBLY
# ==============================================================================
def generate_voiceover(text: str, out_path: str):
    engine = CONFIG.get("TTS_ENGINE", "google").lower()
    if engine == "elevenlabs":
        api_key = CONFIG.get("ELEVENLABS_KEY")
        if api_key and "your-" not in api_key:
            try:
                url = f"https://api.elevenlabs.io/v1/text-to-speech/{CONFIG['VOICE_ID']}"
                headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
                payload = {
                    "text": text, "model_id": "eleven_turbo_v2_5",
                    "voice_settings": {"stability": 0.45, "similarity_boost": 0.80}
                }
                res = requests.post(url, headers=headers, json=payload, timeout=20)
                if res.status_code == 200:
                    with open(out_path, "wb") as f:
                        f.write(res.content)
                    return
            except Exception:
                pass
    gTTS(text=text, lang="en", tld="com", slow=False).save(out_path)

def assemble_video(target: dict, target_fp: dict, contact: dict, audit: dict, rival: dict, rival_fp: dict, out_video_path: str, logo_path: str = None, shot_path: str = None) -> str:
    clips, temps = [], []

    # Slide 1: Intro Title
    s1_img, s1_aud = "tmp_s1.png", "tmp_s1.mp3"
    temps.extend([s1_img, s1_aud])
    render_title_slide(target['name'], contact['name'], audit["intro_bullets"], s1_img, logo_path)
    generate_voiceover(audit["intro_voiceover"], s1_aud)
    a1 = AudioFileClip(s1_aud)
    clips.append(ImageClip(s1_img).with_duration(a1.duration).with_audio(a1))

    # Slide 2: Viewport Screenshot
    s2_img, s2_aud = "tmp_s2.png", "tmp_s2.mp3"
    temps.extend([s2_img, s2_aud])
    render_viewport_screenshot_slide(shot_path, audit.get("slide_2_viewport_bullets", []), s2_img)
    generate_voiceover(audit.get("slide_2_viewport_voiceover", "Here is your current above-the-fold layout."), s2_aud)
    a2 = AudioFileClip(s2_aud)
    clips.append(ImageClip(s2_img).with_duration(a2.duration).with_audio(a2))

    # Slide 3: Competitor Benchmark
    s3_img, s3_aud = "tmp_s3.png", "tmp_s3.mp3"
    temps.extend([s3_img, s3_aud])
    render_competitor_slide(target, target_fp, rival, rival_fp, audit.get("slide_3_competitor_bullets", []), s3_img)
    generate_voiceover(audit.get("slide_3_competitor_voiceover", "Here is how your business compares against top local rivals."), s3_aud)
    a3 = AudioFileClip(s3_aud)
    clips.append(ImageClip(s3_img).with_duration(a3.duration).with_audio(a3))

    # Slides 4-9: Diagnostic & Roadmap Body Slides
    for idx, s in enumerate(audit.get("body_slides", [])):
        si_img, si_aud = f"tmp_sb_{idx}.png", f"tmp_ab_{idx}.mp3"
        temps.extend([si_img, si_aud])
        render_bullet_slide(s["pill"], s["title"], s["bullets"], si_img)
        generate_voiceover(s["voiceover"], si_aud)
        ai = AudioFileClip(si_aud)
        clips.append(ImageClip(si_img).with_duration(ai.duration).with_audio(ai))

    # Slide 10: Outro Card
    s10_img, s10_aud = "tmp_s10.png", "tmp_s10.mp3"
    temps.extend([s10_img, s10_aud])
    render_outro_slide(s10_img)
    generate_voiceover(audit.get("outro_voiceover", f"Connect with our leadership team at {CONFIG['AGENCY_WEBSITE'].lower()}."), s10_aud)
    a10 = AudioFileClip(s10_aud)
    clips.append(ImageClip(s10_img).with_duration(a10.duration).with_audio(a10))

    final = concatenate_videoclips(clips, method="compose")
    final.write_videofile(out_video_path, fps=24, codec="libx264", audio_codec="aac", logger=None)

    for f in temps:
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                pass
    return out_video_path

def assemble_pdf(target: dict, target_fp: dict, contact: dict, audit: dict, rival: dict, rival_fp: dict, out_pdf_path: str, logo_path: str = None, shot_path: str = None) -> str:
    temps = []
    slide_images = []

    # Slide 1
    s1_img = "tmp_pdf_s1.png"
    temps.append(s1_img)
    render_title_slide(target['name'], contact['name'], audit["intro_bullets"], s1_img, logo_path)
    slide_images.append(Image.open(s1_img).convert("RGB"))

    # Slide 2
    s2_img = "tmp_pdf_s2.png"
    temps.append(s2_img)
    render_viewport_screenshot_slide(shot_path, audit.get("slide_2_viewport_bullets", []), s2_img)
    slide_images.append(Image.open(s2_img).convert("RGB"))

    # Slide 3
    s3_img = "tmp_pdf_s3.png"
    temps.append(s3_img)
    render_competitor_slide(target, target_fp, rival, rival_fp, audit.get("slide_3_competitor_bullets", []), s3_img)
    slide_images.append(Image.open(s3_img).convert("RGB"))

    # Slides 4-9
    for idx, s in enumerate(audit.get("body_slides", [])):
        si_img = f"tmp_pdf_sb_{idx}.png"
        temps.append(si_img)
        render_bullet_slide(s["pill"], s["title"], s["bullets"], si_img)
        slide_images.append(Image.open(si_img).convert("RGB"))

    # Slide 10
    s10_img = "tmp_pdf_s10.png"
    temps.append(s10_img)
    render_outro_slide(s10_img)
    slide_images.append(Image.open(s10_img).convert("RGB"))

    if slide_images:
        slide_images[0].save(out_pdf_path, save_all=True, append_images=slide_images[1:], resolution=100.0)

    for f in temps:
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                pass
    return out_pdf_path

# ==============================================================================
# 5. DATA PERSISTENCE & OUTREACH DISPATCH
# ==============================================================================
def save_records(records: list):
    if not records:
        return
    df = pd.DataFrame(records)
    creds_file = CONFIG.get("GOOGLE_SHEETS_CREDENTIALS_JSON", "")
    if GSPREAD_AVAILABLE and os.path.exists(creds_file):
        try:
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_name(creds_file, scope)
            client = gspread.authorize(creds)
            sheet_name = CONFIG["GOOGLE_SHEET_NAME"]
            try:
                sheet = client.open(sheet_name).sheet1
            except gspread.SpreadsheetNotFound:
                sheet = client.create(sheet_name).sheet1
            if not sheet.get_all_values():
                sheet.append_row(list(df.columns))
            sheet.append_rows(df.astype(str).values.tolist())
            print(f"[GOOGLE SHEETS] Successfully synced {len(records)} record(s) to '{sheet_name}'.")
            return
        except Exception as e:
            print(f"[Google Sheets Fallback Triggered]: {e}")

    csv_file = CONFIG["FALLBACK_LOCAL_CSV"]
    file_exists = os.path.exists(csv_file)
    df.to_csv(csv_file, mode="a", header=not file_exists, index=False)
    print(f"[LOCAL CSV] Appended {len(records)} record(s) to '{csv_file}'.")

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
    print("  [1] MP4 Video Presentation (10 Slides + Voiceover)")
    print("  [2] PDF Slide Deck (10 Visual Diagnostic Slides)")
    print("  [3] Data Only (Direct to Google Sheets / CSV)")
    output_choice = input("Select Output [1/2/3, Default: 1]: ").strip() or "1"
    create_video = (output_choice == "1")
    create_pdf = (output_choice == "2")

    # 2. Voiceover Engine Selection
    if create_video:
        print("\n[Step 2] Select Voiceover Engine:")
        print("  [1] Google TTS (Free Preview)")
        print("  [2] ElevenLabs (Production Executive Voice)")
        voice_choice = input("Select Audio Engine [1/2, Default: 1]: ").strip() or "1"
        CONFIG["TTS_ENGINE"] = "elevenlabs" if voice_choice == "2" else "google"
        print(f"  -> Active Engine: {CONFIG['TTS_ENGINE'].upper()}")

    # 3. Discovery Mode Selection
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

        print("  [1/4] Scraping technical footprint & marketing stack...")
        footprint = scrape_site_footprint(website)

        print("  [2/4] Identifying executive decision-maker...")
        contact = find_decision_maker(website, footprint["email"])
        print(f"        Contact: {contact['name']} ({contact['title']}) | {contact['email']}")

        print("        Benchmarking local market competitor...")
        rival = find_benchmark_competitor(category, location, name)
        rival_fp = scrape_site_footprint(rival.get("website", ""))
        print(f"        Benchmark Rival: {rival['name']} ({rival.get('rating')} stars)")

        shot_path, logo_path = None, None
        if create_video or create_pdf:
            print("  [3/4] Capturing logo & viewport screenshot via Playwright...")
            pw_assets = capture_site_assets_playwright(website)
            shot_path = pw_assets["screenshot_path"]
            logo_path = pw_assets["logo_path"]

        print("  [4/4] Generating 10-slide executive audit copy via LLM...")
        audit = generate_audit(lead, footprint, contact, rival=rival, rival_fp=rival_fp)

        # Asset Assembly
        generated_asset = "N/A (Data Only)"
        if create_video:
            out_video = str(CONFIG["OUTPUT_DIR"] / f"{clean_name}_audit_brief.mp4")
            print(f"        Rendering 10-slide MP4 video to: {out_video}")
            assemble_video(lead, footprint, contact, audit, rival, rival_fp, out_video, logo_path=logo_path, shot_path=shot_path)
            generated_asset = out_video
        elif create_pdf:
            out_pdf = str(CONFIG["OUTPUT_DIR"] / f"{clean_name}_audit_deck.pdf")
            print(f"        Rendering 10-slide PDF presentation to: {out_pdf}")
            assemble_pdf(lead, footprint, contact, audit, rival, rival_fp, out_pdf, logo_path=logo_path, shot_path=shot_path)
            generated_asset = out_pdf

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
        records.append({
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
        })

    # Save to Google Sheets / Local CSV
    save_records(records)
    print("\n[COMPLETE] Run finished successfully.")

    # Print Token and Run Cost Report
    print_usage_and_cost_summary(len(records))

if __name__ == "__main__":
    main()