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

    # Agency Branding
    "BRAND_PRIMARY": "ELKINS & CO.",
    "BRAND_SUBTITLE": "REVENUE STRATEGIES",
    "AGENCY_WEBSITE": "WWW.ELKINSREVENUE.COM",
    "AGENCY_PHONE": "917-327-0636",
    "AGENCY_EMAIL": "lorren@elkinsrevenue.com",

    # Email SMTP Settings
    "SMTP_SERVER": "smtp.gmail.com",
    "SMTP_PORT": 465,
    "SENDER_EMAIL": "your-email@domain.com",
    "SENDER_PASSWORD": "your-app-password",

    # Data Persistence
    "GOOGLE_SHEET_NAME": "Prospecting Pipeline & Audit Data",
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

STYLE = {
    "BG": (244, 246, 248),
    "CARD_BG": (255, 255, 255),
    "CARD_BORDER": (235, 238, 243),
    "TEXT_DARK": (15, 23, 42),
    "TEXT_BODY": (30, 41, 59),
    "TEXT_MUTED": (100, 116, 139),
    "BLUE": (37, 99, 235),
    "PILL_BG": (239, 246, 255),
    "DIVIDER": (203, 213, 225)
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
    """Prints token consumption metrics and run cost estimates."""
    p_tokens = TOKEN_STATS["prompt_tokens"]
    c_tokens = TOKEN_STATS["completion_tokens"]
    total = TOKEN_STATS["total_tokens"]
    calls = TOKEN_STATS["llm_calls"]

    # Pricing benchmark: Standard commercial Qwen / GPT-4o-mini rates ($0.40/1M in, $1.20/1M out)
    comm_prompt_cost = (p_tokens / 1_000_000) * 0.40
    comm_compl_cost = (c_tokens / 1_000_000) * 1.20
    commercial_equiv = comm_prompt_cost + comm_compl_cost

    # Actual cost on NRP Nautilus endpoint
    actual_nrp_cost = 0.00

    print("\n" + "=" * 60)
    print("                RUN METRICS & COST SUMMARY")
    print("=" * 60)
    print(f"Total Leads Processed   : {leads_processed}")
    print(f"Total LLM Invocations   : {calls}")
    print("-" * 60)
    print(f"Prompt (Input) Tokens   : {p_tokens:,}")
    print(f"Completion Tokens       : {c_tokens:,}")
    print(f"Total Tokens Used       : {total:,}")
    print("-" * 60)
    print(f"Actual API Cost (NRP)   : ${actual_nrp_cost:.4f} (NSF Grant Funded)")
    print(f"Commercial Equivalent   : ${commercial_equiv:.4f} (Commercial API Value)")
    if leads_processed > 0:
        print(f"Avg Cost per Lead       : ${commercial_equiv / leads_processed:.4f}")
    print("=" * 60 + "\n")

# ==============================================================================
# 1. DISCOVERY, SCRAPING & ENRICHMENT
# ==============================================================================
def find_businesses(category: str, location: str, limit: int = 1) -> list:
    """Discovers local targets via Google Places API."""
    api_key = CONFIG.get("GOOGLE_PLACES_KEY")
    if not api_key or "your-" in api_key:
        print("\n[MOCK MODE] Missing Google Places Key. Returning test mock lead.")
        return [{
            "name": f"Premier {category}",
            "website": "https://example.com",
            "address": location,
            "rating": 4.3,
            "review_count": 48
        }]

    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.displayName,places.websiteUri,places.formattedAddress,places.rating,places.userRatingCount"
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
            "review_count": p.get("userRatingCount", 0)
        } for p in places]
    except Exception as e:
        print(f"[Places API Error]: {e}")
        return []

def find_benchmark_competitor(category: str, location: str, exclude_name: str) -> dict:
    """Finds a top local benchmark competitor for head-to-head comparison."""
    candidates = find_businesses(category, location, limit=5)
    for c in candidates:
        if c["name"].lower() != exclude_name.lower():
            return c
    return {
        "name": f"Top-Rated {category} Rival",
        "website": "https://example.com",
        "rating": 4.9,
        "review_count": 210,
        "address": location
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
        "logo_img_path": "prospect_logo_temp.png"
    }
    if not website_url or not website_url.startswith("http"):
        details["missing_elements"].append("Inaccessible page")
        return details
    try:
        start = requests.compat.time.time()
        resp = requests.get(website_url, timeout=7, headers={"User-Agent": "Mozilla/5.0"})
        details["load_speed_sec"] = round(requests.compat.time.time() - start, 2)
        soup = BeautifulSoup(resp.text, "html.parser")

        emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', resp.text)
        valid_emails = [e for e in emails if not e.endswith(('.png', '.jpg', '.webp', '.svg'))]
        if valid_emails:
            details["email"] = valid_emails[0]

        for link in soup.find_all("a", href=True):
            href = link["href"].lower()
            for platform in ["facebook.com", "instagram.com", "linkedin.com", "youtube.com"]:
                if platform in href and href not in details["social_links"]:
                    details["social_links"].append(href)

        details["has_lead_form"] = bool(soup.find_all("form"))
        details["has_click_to_call"] = bool(soup.find("a", href=re.compile(r"^tel:")))
        details["has_schema"] = any("schema.org" in t.text.lower() for t in soup.find_all("script", type="application/ld+json"))
        details["has_meta_desc"] = bool(soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)}))
        details["is_mobile_responsive"] = bool(soup.find("meta", attrs={"name": re.compile(r"^viewport$", re.I)}))

        if not details["has_lead_form"]:
            details["missing_elements"].append("No direct lead capture form")
        if not details["has_click_to_call"]:
            details["missing_elements"].append("No tap-to-call link")
        if not details["has_schema"]:
            details["missing_elements"].append("Missing structured schema markup")

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
            page.goto(website_url, timeout=20000, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
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
        print(f"    [Playwright Info] Stealth browser pass bypassed: {e}")
    return result

# ==============================================================================
# 2. LLM AUDIT ENGINE WITH USAGE TALLY
# ==============================================================================
def call_nrp_llm(prompt: str) -> str:
    """Sends prompt to custom NRP Nautilus vLLM endpoint and tallies token usage."""
    headers = {"Authorization": f"Bearer {CONFIG['NRP_API_KEY']}", "Content-Type": "application/json"}
    payload = {"model": CONFIG["MODEL_NAME"], "messages": [{"role": "user", "content": prompt}], "temperature": 0.2}
    res = requests.post(f"{CONFIG['NRP_ENDPOINT']}/chat/completions", headers=headers, json=payload, timeout=30)
    res.raise_for_status()
    data = res.json()

    # Extract usage metrics returned by the vLLM endpoint
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
Analyze this business and return ONLY a valid JSON object.
Target Decision Maker: {contact['name']} ({contact['title']})
Business: {target['name']} | Website: {target['website']}
Google Reviews: {target['rating']} stars ({target['review_count']} reviews)
Load Time: {target_fp['load_speed_sec']}s | Form: {target_fp['has_lead_form']} | Tap-to-Call: {target_fp['has_click_to_call']}
Flags: {target_fp['missing_elements']}
{rival_context}

Return strictly this JSON schema:
{{
  "scores": {{
    "seo": 70, "social_media": 65, "website_speed": 55, "content_clarity": 80, "lead_conversion": 50, "reputation": 75
  }},
  "core_weakness": "conversion and mobile tap-to-call friction",
  "quick_win": "Deploy instant tap-to-call links and local schema markup",
  "solution": "Turnkey conversion architecture upgrade and mobile UX optimization",
  "email_subject": "Revenue diagnostic & lead conversion roadmap for {target['name']}",
  "email_body": "Hi {contact['name']}, we evaluated {target['name']}'s local conversion infrastructure and flagged key points of lead leakage. Attached is a diagnostic briefing covering the fixes.",
  "intro_voiceover": "We examined your local market position and conversion capture flow. This executive briefing outlines primary bottlenecks suppressing buyer calls and our proposed roadmap to resolve them.",
  "intro_bullets": [
    "Audited page speed, lead flow, search visibility and mobile UX",
    "Identified conversion bottlenecks suppressing local buyer inquiries",
    "Delivering clear, zero-friction revenue recovery roadmap"
  ],
  "slides": [
    {{
      "pill": "01 / EXECUTIVE AUDIT FINDING",
      "title": "Primary Revenue Bottleneck",
      "bullets": [
        "Inaccessible mobile touchpoints drop high-intent visitors",
        "Page load latency slows mobile engagement",
        "Missing direct conversion capture links"
      ],
      "voiceover": "We evaluated page load speed, lead capture friction, and mobile responsiveness. The biggest bottleneck is user friction that drops potential customers before they initiate contact."
    }},
    {{
      "pill": "02 / REVENUE & PIPELINE IMPACT",
      "title": "Market Share & Lead Leakage",
      "bullets": [
        "Zero visible lead capture suppresses daily inquiries",
        "Competitors capture high-intent local demand",
        "Mobile bounce rate drains marketing returns"
      ],
      "voiceover": "Every missed mobile interaction is missed revenue. Without instant tap-to-call and quick lead forms, high-intent prospects immediately bounce to other local options."
    }},
    {{
      "pill": "03 / PROPOSED STRATEGIC FIX",
      "title": "The High-ROI Solution",
      "bullets": [
        "Quick win: install tap-to-call and lead capture retainers",
        "Rebuild fast-loading mobile-first appointment funnel",
        "Projected lift in qualified inquiries and conversions"
      ],
      "voiceover": "The fix begins with quick wins: deploying clear tap-to-call triggers, responsive forms, and local schema to convert inbound visits into confirmed client calls."
    }},
    {{
      "pill": "04 / RECOMMENDED NEXT STEP",
      "title": "Implementation & Next Steps",
      "bullets": [
        "Review comprehensive technical diagnostic data",
        "Prioritize high-impact quick wins with no downtime",
        "Turnkey roadmap execution with zero team overhead"
      ],
      "voiceover": "Next, connect with our team for a zero-friction walkthrough of your complete diagnostic dataset and a turnkey rollout to reclaim local search demand."
    }}
  ]
}}
"""
    try:
        raw = call_nrp_llm(prompt)
        clean = re.search(r'\{.*\}', raw, re.DOTALL).group(0)
        return json.loads(clean)
    except Exception as e:
        print(f"[LLM Fallback Used]: {e}")
        return {
            "scores": {"seo": 70, "social_media": 60, "website_speed": 65, "content_clarity": 75, "lead_conversion": 50, "reputation": 70},
            "core_weakness": "Mobile conversion friction and response latency",
            "quick_win": "Deploy instant tap-to-call and lead forms",
            "solution": "Mobile-first conversion architecture update",
            "email_subject": f"Digital performance brief for {target['name']}",
            "email_body": f"Hi {contact['name']}, we evaluated your digital presence and identified opportunities to capture more inbound inquiries.",
            "intro_voiceover": "We evaluated your local conversion infrastructure. This briefing highlights friction points and how to fix them.",
            "intro_bullets": ["Audited website performance & lead capture", "Identified primary points of conversion leakage", "Proposing turnkey strategic roadmap"],
            "slides": [
                {
                    "pill": "01 / EXECUTIVE AUDIT FINDING",
                    "title": "Primary Revenue Bottleneck",
                    "bullets": ["Slow mobile load and hidden call links", "Friction directs local demand to competitors", "Missing structured schema markup"],
                    "voiceover": "The primary bottleneck is digital friction that causes visitors to leave before contacting your business."
                },
                {
                    "pill": "02 / REVENUE & PIPELINE IMPACT",
                    "title": "Market Share & Lead Leakage",
                    "bullets": ["Suppressed inbound inquiry flow", "Higher local drop-off rates", "Missed appointment opportunities"],
                    "voiceover": "Without direct click-to-call options, visitors looking for immediate service look elsewhere."
                },
                {
                    "pill": "03 / PROPOSED STRATEGIC FIX",
                    "title": "The High-ROI Solution",
                    "bullets": ["Add sticky tap-to-call and contact forms", "Deploy mobile conversion triggers", "Boost conversion capture rate"],
                    "voiceover": "We recommend an immediate tactical upgrade: streamlined forms, tap-to-call buttons, and responsive pages."
                },
                {
                    "pill": "04 / RECOMMENDED NEXT STEP",
                    "title": "Implementation & Next Steps",
                    "bullets": ["Review complete technical audit", "Prioritize fastest-ROI fixes", "Turnkey implementation"],
                    "voiceover": "Let's schedule a brief conversation to review the data and implement these conversion upgrades."
                }
            ]
        }

# ==============================================================================
# 3. GRAPHIC SLIDE RENDERER (PIL)
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
    draw.rectangle([0, 0, W, H], fill=STYLE["BG"])
    mx, my = 100, 60
    draw.rounded_rectangle([mx, my, W - mx, H - my], radius=24, fill=STYLE["CARD_BG"], outline=STYLE["CARD_BORDER"], width=2)
    draw.text((mx + 70, my + 60), CONFIG["BRAND_PRIMARY"], fill=STYLE["TEXT_DARK"], font=load_font(26, bold=True))
    bbox = draw.textbbox((mx + 70, my + 60), CONFIG["BRAND_PRIMARY"], font=load_font(26, bold=True))
    draw.text((bbox[2] + 16, my + 64), CONFIG["BRAND_SUBTITLE"], fill=STYLE["BLUE"], font=load_font(18, bold=True))

def render_title_slide(lead_name: str, contact_name: str, bullets: list, out_path: str, logo_path: str = None):
    W, H = 1920, 1080
    img = Image.new("RGB", (W, H), color=STYLE["BG"])
    draw = ImageDraw.Draw(img)
    draw_card_base(draw, W, H)

    start_x = 170
    draw.rounded_rectangle([start_x, 185, start_x + 530, 225], radius=6, fill=STYLE["PILL_BG"], outline=(219, 234, 254), width=1)
    draw.text((start_x + 20, 193), "CONFIDENTIAL EXECUTIVE BRIEFING · RESEARCH & STRATEGY", fill=STYLE["BLUE"], font=load_font(16, bold=True))

    draw.text((start_x, 260), "Digital Diagnostic & Revenue Roadmap", fill=STYLE["TEXT_DARK"], font=load_font(56, bold=True))
    target_str = f"Prepared for: {contact_name} & Leadership at {lead_name}" if contact_name not in ["Leadership", "Business Leader"] else f"Prepared Exclusively for: {lead_name}"
    draw.text((start_x, 340), target_str, fill=STYLE["TEXT_MUTED"], font=load_font(28))

    bullet_y = 440
    font_b = load_font(32)
    for b in bullets[:4]:
        draw.ellipse([start_x, bullet_y + 18, start_x + 16, bullet_y + 34], fill=STYLE["BLUE"])
        draw.text((start_x + 36, bullet_y), b, fill=STYLE["TEXT_BODY"], font=font_b)
        bullet_y += 70

    if logo_path and os.path.exists(logo_path):
        try:
            with Image.open(logo_path) as l_img:
                l_img = l_img.convert("RGBA")
                l_img.thumbnail((260, 90), Image.Resampling.LANCZOS)
                img.paste(l_img, (W - 450, 180), l_img)
        except Exception:
            pass

    draw.text((start_x, H - 120), "CONFIDENTIAL · PREPARED FOR EXECUTIVE REVIEW", fill=STYLE["TEXT_MUTED"], font=load_font(18, bold=True))
    draw.text((W - 480, H - 120), CONFIG["AGENCY_WEBSITE"], fill=STYLE["BLUE"], font=load_font(18, bold=True))
    img.save(out_path)

def render_bullet_slide(pill_text: str, main_title: str, bullets: list, out_path: str):
    W, H = 1920, 1080
    img = Image.new("RGB", (W, H), color=STYLE["BG"])
    draw = ImageDraw.Draw(img)
    draw_card_base(draw, W, H)

    start_x = 170
    current_y = 195

    font_pill = load_font(18, bold=True)
    p_box = draw.textbbox((0, 0), pill_text, font=font_pill)
    pw, ph = p_box[2] - p_box[0], p_box[3] - p_box[1]
    draw.rounded_rectangle([start_x, current_y, start_x + pw + 32, current_y + ph + 20], radius=8, fill=STYLE["PILL_BG"], outline=(219, 234, 254), width=1)
    draw.text((start_x + 16, current_y + 10), pill_text, fill=STYLE["BLUE"], font=font_pill)

    current_y += ph + 55
    draw.text((start_x, current_y), main_title, fill=STYLE["TEXT_DARK"], font=load_font(54, bold=True))

    current_y += 115
    font_b = load_font(34)
    for b in bullets:
        draw.ellipse([start_x, current_y + 20, start_x + 18, current_y + 38], fill=STYLE["BLUE"])
        draw.text((start_x + 40, current_y), b, fill=STYLE["TEXT_BODY"], font=font_b)
        current_y += 75

    draw.text((start_x, H - 120), "CONFIDENTIAL · PREPARED FOR EXECUTIVE REVIEW", fill=STYLE["TEXT_MUTED"], font=load_font(18, bold=True))
    draw.text((W - 480, H - 120), CONFIG["AGENCY_WEBSITE"], fill=STYLE["BLUE"], font=load_font(18, bold=True))
    img.save(out_path)

def render_outro_slide(out_path: str):
    W, H = 1920, 1080
    img = Image.new("RGB", (W, H), color=STYLE["BG"])
    draw = ImageDraw.Draw(img)
    draw_card_base(draw, W, H)

    start_x = 170
    draw.text((start_x, 260), "Ready to Eliminate Digital Leakage?", fill=STYLE["TEXT_DARK"], font=load_font(60, bold=True))
    draw.text((start_x, 345), "Let's review the complete diagnostic dataset and implement the roadmap.", fill=STYLE["TEXT_MUTED"], font=load_font(28))

    cy = 470
    draw.text((start_x, cy), "VISIT US ONLINE", fill=STYLE["TEXT_MUTED"], font=load_font(20, bold=True))
    draw.text((start_x, cy + 36), CONFIG["AGENCY_WEBSITE"].lower(), fill=STYLE["BLUE"], font=load_font(28))

    draw.text((start_x + 450, cy), "DIRECT INQUIRIES", fill=STYLE["TEXT_MUTED"], font=load_font(20, bold=True))
    draw.text((start_x + 450, cy + 36), CONFIG["AGENCY_PHONE"], fill=STYLE["TEXT_DARK"], font=load_font(28))

    draw.text((start_x + 850, cy), "EMAIL OUR TEAM", fill=STYLE["TEXT_MUTED"], font=load_font(20, bold=True))
    draw.text((start_x + 850, cy + 36), CONFIG["AGENCY_EMAIL"], fill=STYLE["TEXT_DARK"], font=load_font(28))
    img.save(out_path)

# ==============================================================================
# 4. AUDIO & OUTPUT ASSEMBLY
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

def assemble_video(target: dict, contact: dict, audit: dict, out_video_path: str, logo_path: str = None) -> str:
    clips, temps = [], []

    # Slide 1: Intro
    s1_img, s1_aud = "tmp_s1.png", "tmp_s1.mp3"
    temps.extend([s1_img, s1_aud])
    render_title_slide(target['name'], contact['name'], audit["intro_bullets"], s1_img, logo_path)
    generate_voiceover(audit["intro_voiceover"], s1_aud)
    a1 = AudioFileClip(s1_aud)
    clips.append(ImageClip(s1_img).with_duration(a1.duration).with_audio(a1))

    # Slides 2-5: Core Diagnostic Points
    for i, s in enumerate(audit["slides"]):
        si_img, si_aud = f"tmp_s_{i}.png", f"tmp_a_{i}.mp3"
        temps.extend([si_img, si_aud])
        render_bullet_slide(s["pill"], s["title"], s["bullets"], si_img)
        generate_voiceover(s["voiceover"], si_aud)
        ai = AudioFileClip(si_aud)
        clips.append(ImageClip(si_img).with_duration(ai.duration).with_audio(ai))

    # Slide 6: Outro
    s6_img, s6_aud = "tmp_s6.png", "tmp_s6.mp3"
    temps.extend([s6_img, s6_aud])
    render_outro_slide(s6_img)
    generate_voiceover(f"To review the full diagnostic data, connect with our leadership team at {CONFIG['AGENCY_WEBSITE'].lower()}.", s6_aud)
    a6 = AudioFileClip(s6_aud)
    clips.append(ImageClip(s6_img).with_duration(a6.duration).with_audio(a6))

    final = concatenate_videoclips(clips, method="compose")
    final.write_videofile(out_video_path, fps=24, codec="libx264", audio_codec="aac", logger=None)

    for f in temps:
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                pass
    return out_video_path

def assemble_pdf(target: dict, contact: dict, audit: dict, out_pdf_path: str, logo_path: str = None) -> str:
    temps = []
    slide_images = []

    s1_img = "tmp_pdf_s1.png"
    temps.append(s1_img)
    render_title_slide(target['name'], contact['name'], audit["intro_bullets"], s1_img, logo_path)
    slide_images.append(Image.open(s1_img).convert("RGB"))

    for i, s in enumerate(audit["slides"]):
        si_img = f"tmp_pdf_s_{i}.png"
        temps.append(si_img)
        render_bullet_slide(s["pill"], s["title"], s["bullets"], si_img)
        slide_images.append(Image.open(si_img).convert("RGB"))

    s6_img = "tmp_pdf_s6.png"
    temps.append(s6_img)
    render_outro_slide(s6_img)
    slide_images.append(Image.open(s6_img).convert("RGB"))

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
# 5. DATA PERSISTENCE & EMAIL
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
# 6. INTERACTIVE PIPELINE ENTRY POINT
# ==============================================================================
def main():
    print("=" * 70)
    print("   B2B PROSPECT AUDIT & ASSET ENGINE")
    print("=" * 70)

    # 1. Output Type Prompt
    print("\n[Step 1] Select Deliverable Output Format:")
    print("  [1] MP4 Video Presentation (Visual Slides + Voiceover)")
    print("  [2] PDF Slide Deck (Visual Diagnostic Presentation)")
    print("  [3] Data Only (Direct to Google Sheets / CSV)")
    output_choice = input("Select Output [1/2/3, Default: 1]: ").strip() or "1"
    create_video = (output_choice == "1")
    create_pdf = (output_choice == "2")

    # 2. Voiceover Engine Prompt (Only if Video)
    if create_video:
        print("\n[Step 2] Select Voiceover Engine:")
        print("  [1] Google TTS (Free Preview)")
        print("  [2] ElevenLabs (Production Executive Voice)")
        voice_choice = input("Select Audio Engine [1/2, Default: 1]: ").strip() or "1"
        CONFIG["TTS_ENGINE"] = "elevenlabs" if voice_choice == "2" else "google"
        print(f"  -> Active Engine: {CONFIG['TTS_ENGINE'].upper()}")

    # 3. Prospecting Discovery Prompt
    print("\n[Step 3] Select Prospect Mode:")
    print("  [1] Automated Batch Discovery (via Google Places)")
    print("  [2] Single Prospect by Website URL")
    run_mode = input("Select Mode [1/2, Default: 1]: ").strip() or "1"

    # 4. Competitor Benchmark Option
    print("\n[Step 4] Include Competitor Benchmark Analysis?")
    print("  [y] Yes (Compare prospect against a local market rival)")
    print("  [n] No  (Single-business internal technical diagnostic only)")
    include_competitor = (input("Include Competitor? [y/n, Default: y]: ").strip().lower() or "y") == "y"

    # Resolve Leads
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
        leads = [{"name": p_name, "website": single_url, "address": location, "rating": 0, "review_count": 0}]
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

        print("  [1/4] Scraping website footprint...")
        footprint = scrape_site_footprint(website)

        # Decision Maker Search
        print("  [2/4] Identifying executive decision-maker...")
        contact = find_decision_maker(website, footprint["email"])
        print(f"        Contact: {contact['name']} ({contact['title']}) | {contact['email']}")

        # Optional Competitor Lookup
        rival, rival_fp = None, None
        if include_competitor:
            print("        Finding local benchmark rival...")
            rival = find_benchmark_competitor(category, location, name)
            rival_fp = scrape_site_footprint(rival.get("website", ""))
            print(f"        Benchmark Rival: {rival['name']} ({rival.get('rating')} stars)")

        # Asset Capture
        logo_path = None
        if create_video or create_pdf:
            print("  [3/4] Capturing logo & layout via Playwright...")
            pw_assets = capture_site_assets_playwright(website)
            logo_path = pw_assets["logo_path"]

        # Audit Generation
        print("  [4/4] Generating executive audit copy via LLM...")
        audit = generate_audit(lead, footprint, contact, rival=rival, rival_fp=rival_fp)

        # Build Output Asset
        generated_asset = "N/A (Data Only)"
        if create_video:
            out_video = str(CONFIG["OUTPUT_DIR"] / f"{clean_name}_audit_brief.mp4")
            print(f"        Rendering MP4 video to: {out_video}")
            assemble_video(lead, contact, audit, out_video, logo_path=logo_path)
            generated_asset = out_video
        elif create_pdf:
            out_pdf = str(CONFIG["OUTPUT_DIR"] / f"{clean_name}_audit_deck.pdf")
            print(f"        Rendering PDF presentation to: {out_pdf}")
            assemble_pdf(lead, contact, audit, out_pdf, logo_path=logo_path)
            generated_asset = out_pdf

        # Email Delivery (if valid email present)
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

        records.append({
            "Business Name": name,
            "Decision Maker": contact["name"],
            "Title": contact["title"],
            "Contact Email": email_recipient,
            "Competitor Benchmark": rival["name"] if rival else "None",
            "SEO Score": audit["scores"]["seo"],
            "Speed Score": audit["scores"]["website_speed"],
            "Lead Conversion Score": audit["scores"]["lead_conversion"],
            "Core Weakness": audit["core_weakness"],
            "Proposed Solution": audit["solution"],
            "Asset Path": generated_asset,
            "Email Status": delivery_status
        })

    # Save to Sheets / CSV
    save_records(records)
    print("\n[COMPLETE] Run finished successfully.")

    # Print cumulative token usage and cost summary
    print_usage_and_cost_summary(len(records))

if __name__ == "__main__":
    main()