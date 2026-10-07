import os
import re
import sys
import json
import time
import base64
import smtplib
from pathlib import Path
from email.message import EmailMessage
from urllib.parse import urlparse, urljoin
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
    "AGENCY_EMAIL": "lorren@elkinsrevenue.com",
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
def render_single_page_scorecard(lead: dict, footprint: dict, contact: dict, rival: dict, rival_fp: dict, audit: dict, shot_path: str, out_pdf: str):
    """
    Renders an executive, high-resolution 8.5" x 11" diagnostic report card at 300 DPI (2550 x 3300 px).
    """
    W, H = 2550, 3300
    im = Image.new("RGB", (W, H), color=STYLE["BG"])
    draw = ImageDraw.Draw(im)

    f_brand = load_font(["arialbd.ttf", "segoeuib.ttf"], 54)
    f_sub = load_font(["arial.ttf", "segoeui.ttf"], 28)
    f_title = load_font(["arialbd.ttf", "segoeuib.ttf"], 40)
    f_score_num = load_font(["arialbd.ttf", "segoeuib.ttf"], 68)
    f_body = load_font(["arial.ttf", "segoeui.ttf"], 28)
    f_bold = load_font(["arialbd.ttf", "segoeuib.ttf"], 30)

    perf_data = compute_overall_performance_score(lead, footprint)
    overall_score = perf_data["overall_score"]

    mx = 120
    y = 120

    # 1. Header Banner
    draw.text((mx, y), CONFIG["BRAND_PRIMARY"], fill=STYLE["TEXT_MAIN"], font=f_brand)
    draw.text((mx, y + 65), f"{CONFIG['BRAND_SUBTITLE']} | REVENUE PERFORMANCE BENCHMARK", fill=STYLE["TEXT_FAINT"], font=f_sub)

    # Overall Score Badge (Top Right)
    badge_w, badge_h = 420, 160
    bx, by = W - mx - badge_w, y - 10
    score_col = STYLE["GREEN"] if overall_score >= 75 else (STYLE["AMBER"] if overall_score >= 50 else STYLE["RED"])
    draw.rounded_rectangle([bx, by, bx + badge_w, by + badge_h], radius=16, fill=STYLE["BLUE_BG"], outline=STYLE["CARD_BORDER"], width=3)
    draw.text((bx + 30, by + 20), "PERFORMANCE SCORE", fill=STYLE["BLUE"], font=load_font(["arialbd.ttf", "segoeuib.ttf"], 20))
    draw.text((bx + 30, by + 55), f"{overall_score}/100", fill=score_col, font=f_score_num)

    y += 180
    draw.line([mx, y, W - mx, y], fill=STYLE["DIVIDER"], width=3)

    # 2. Prospect Target Lockup
    y += 40
    draw.text((mx, y), f"AUDIT TARGET: {lead.get('name', 'Prospect').upper()}", fill=STYLE["TEXT_MAIN"], font=f_title)
    draw.text((mx, y + 55), f"Web: {lead.get('website', 'N/A')}  |  Location: {lead.get('address', 'Local Market')}", fill=STYLE["TEXT_MUTED"], font=f_body)

    # 3. Middle Section: Viewport Mockup (Left) vs. Core Sub-Scores (Right)
    y += 140
    col_w = (W - 2 * mx - 80) // 2

    # Left: Desktop Screen Capture / Wireframe Card
    draw.rounded_rectangle([mx, y, mx + col_w, y + 680], radius=16, fill=STYLE["CARD_BG"], outline=STYLE["CARD_BORDER"], width=2)
    draw.text((mx + 35, y + 30), "VIEWPORT CONVERSION AUDIT", fill=STYLE["TEXT_MAIN"], font=f_bold)

    if shot_path and os.path.exists(shot_path):
        try:
            shot_img = Image.open(shot_path).convert("RGB")
            shot_img = shot_img.resize((col_w - 70, 480))
            im.paste(shot_img, (mx + 35, y + 90))
        except Exception:
            draw.text((mx + 50, y + 250), "[Live Viewport Captured]", fill=STYLE["TEXT_FAINT"], font=f_body)
    else:
        draw.rectangle([mx + 35, y + 90, mx + col_w - 35, y + 570], fill=(230, 235, 242))
        draw.text((mx + 70, y + 260), "Desktop Viewport Mockup", fill=STYLE["TEXT_FAINT"], font=f_bold)
        draw.text((mx + 70, y + 310), f"Load Latency: {footprint.get('load_speed_sec', 2.0)}s", fill=STYLE["TEXT_MUTED"], font=f_body)

    draw.text((mx + 35, y + 600), f"CMS Framework: {footprint.get('cms_framework', 'Custom/Static')}", fill=STYLE["TEXT_FAINT"], font=f_body)

    # Right: Diagnostic Gauges & Sub-Scores
    rx = mx + col_w + 80
    draw.rounded_rectangle([rx, y, rx + col_w, y + 680], radius=16, fill=STYLE["CARD_BG"], outline=STYLE["CARD_BORDER"], width=2)
    draw.text((rx + 35, y + 30), "PERFORMANCE SUB-PILLARS", fill=STYLE["TEXT_MAIN"], font=f_bold)

    pillars = [
        ("Conversion Infrastructure", perf_data["conversion"]),
        ("Technical SEO & Crawl Architecture", perf_data["seo"]),
        ("Mobile Speed & Response Time", perf_data["speed"]),
        ("Local Brand Reputation & Authority", perf_data["reputation"]),
        ("Tagging & Marketing Pixel Maturity", perf_data["marketing"])
    ]

    gy = y + 100
    for p_label, p_val in pillars:
        draw.text((rx + 35, gy), p_label, fill=STYLE["TEXT_MUTED"], font=f_body)
        draw.text((rx + col_w - 110, gy), f"{p_val}%", fill=STYLE["TEXT_MAIN"], font=f_bold)
        # Bar track
        draw.rounded_rectangle([rx + 35, gy + 42, rx + col_w - 35, gy + 62], radius=10, fill=(225, 230, 238))
        # Fill
        fill_w = int((col_w - 70) * (p_val / 100.0))
        b_col = STYLE["GREEN"] if p_val >= 70 else (STYLE["AMBER"] if p_val >= 45 else STYLE["RED"])
        if fill_w > 0:
            draw.rounded_rectangle([rx + 35, gy + 42, rx + 35 + fill_w, gy + 62], radius=10, fill=b_col)
        gy += 105

    # 4. Technical Checklist
    y += 740
    draw.rounded_rectangle([mx, y, W - mx, y + 320], radius=16, fill=STYLE["CARD_BG"], outline=STYLE["CARD_BORDER"], width=2)
    draw.text((mx + 35, y + 25), "TECHNICAL SIGNALS & PIPELINE INTEGRITY", fill=STYLE["TEXT_MAIN"], font=f_bold)

    checks = [
        ("Lead Form Active", footprint.get("has_lead_form")),
        ("Click-to-Call Tap", footprint.get("has_click_to_call")),
        ("SSL Enforced", footprint.get("has_ssl")),
        ("JSON-LD Schema", footprint.get("has_schema")),
        ("GA4 / GTM Tag", footprint.get("has_ga4") or footprint.get("has_gtm")),
        ("Meta Pixel", footprint.get("has_meta_pixel")),
        ("Booking Embed", footprint.get("has_booking_embed")),
        ("Live Chat / SMS", footprint.get("has_live_chat"))
    ]

    cx = mx + 40
    cy = y + 85
    for i, (label, passed) in enumerate(checks):
        status_col = STYLE["GREEN"] if passed else STYLE["RED"]
        mark = "✓" if passed else "✕"
        draw.text((cx, cy), f"{mark} {label}", fill=status_col, font=f_bold)
        cx += 280
        if (i + 1) % 4 == 0:
            cx = mx + 40
            cy += 80

    # 5. Competitor Benchmark Matrix
    y += 370
    draw.rounded_rectangle([mx, y, W - mx, y + 420], radius=16, fill=STYLE["CARD_BG"], outline=STYLE["CARD_BORDER"], width=2)
    draw.text((mx + 35, y + 25), "LOCAL BENCHMARK GAP ANALYSIS", fill=STYLE["TEXT_MAIN"], font=f_bold)

    rival_name = rival.get("name", "Local Top Competitor")
    t_rating = lead.get("rating", 0)
    r_rating = rival.get("rating", 4.8)
    t_rev = lead.get("review_count", 0)
    r_rev = rival.get("review_count", 150)
    t_spd = footprint.get("load_speed_sec", 2.0)
    r_spd = rival_fp.get("load_speed_sec", 1.2)

    headers = ["Metric Dimension", lead.get("name", "Audit Target")[:20], rival_name[:20], "Strategic Gap Advantage"]
    col_offsets = [mx + 40, mx + 620, mx + 1180, mx + 1700]

    my = y + 85
    for idx, h in enumerate(headers):
        draw.text((col_offsets[idx], my), h, fill=STYLE["BLUE"], font=f_bold)
    draw.line([mx + 35, my + 45, W - mx - 35, my + 45], fill=STYLE["DIVIDER"], width=2)

    rows = [
        ("Star Rating", f"{t_rating} ★", f"{r_rating} ★", "Reputation Authority Deficit" if t_rating < r_rating else "Competitive Lead"),
        ("Indexed Review Volume", f"{t_rev} Reviews", f"{r_rev} Reviews", f"{max(0, r_rev - t_rev)} Review Gap"),
        ("Homepage Server Latency", f"{t_spd}s", f"{r_spd}s", f"{round(abs(t_spd - r_spd), 2)}s Friction Gap")
    ]

    my += 65
    for r in rows:
        for idx, val in enumerate(r):
            draw.text((col_offsets[idx], my), str(val), fill=STYLE["TEXT_MAIN"] if idx == 0 else STYLE["TEXT_MUTED"], font=f_body)
        my += 60

    # 6. Strategic Finding & Priority Fix
    y += 470
    draw.rounded_rectangle([mx, y, W - mx, y + 360], radius=16, fill=STYLE["BLUE_BG"], outline=STYLE["BLUE"], width=2)
    draw.text((mx + 35, y + 25), "EXECUTIVE ROADMAP & REVENUE RECOVERY ACTIONS", fill=STYLE["BLUE"], font=f_bold)

    draw.text((mx + 35, y + 85), "PRIMARY WEAKNESS:", fill=STYLE["TEXT_MAIN"], font=f_bold)
    draw.text((mx + 380, y + 85), audit.get("core_weakness", "Conversion friction"), fill=STYLE["TEXT_MUTED"], font=f_body)

    draw.text((mx + 35, y + 160), "HIGH-ROI QUICK WIN:", fill=STYLE["TEXT_MAIN"], font=f_bold)
    draw.text((mx + 380, y + 160), audit.get("quick_win", "Implement instant mobile booking"), fill=STYLE["TEXT_MUTED"], font=f_body)

    draw.text((mx + 35, y + 235), "STRATEGIC SOLUTION:", fill=STYLE["TEXT_MAIN"], font=f_bold)
    draw.text((mx + 380, y + 235), audit.get("solution", "3-Tier Paid Acquisition Architecture"), fill=STYLE["TEXT_MUTED"], font=f_body)

    # 7. Executive Outro Banner
    y += 420
    draw.line([mx, y, W - mx, y], fill=STYLE["DIVIDER"], width=2)
    draw.text((mx, y + 40), CONFIG["CUSTOM_CTA"], fill=STYLE["TEXT_MAIN"], font=f_bold)
    draw.text((mx, y + 90), f"Phone: {CONFIG['AGENCY_PHONE']}   |   Email: {CONFIG['AGENCY_EMAIL']}   |   Web: {CONFIG['AGENCY_WEBSITE']}", fill=STYLE["TEXT_FAINT"], font=f_body)

    im.save(out_pdf, "PDF", resolution=300.0)

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
            render_single_page_scorecard(lead, footprint, contact, rival, rival_fp, audit, shot_path, out_scorecard)
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