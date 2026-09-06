import os
import re
import json
import smtplib
from pathlib import Path
from email.message import EmailMessage
from urllib.parse import urlparse, urljoin
import requests
import pandas as pd
from gtts import gTTS
from bs4 import BeautifulSoup
from moviepy import ImageClip, AudioFileClip, concatenate_videoclips
from PIL import Image, ImageDraw, ImageFont

# Optional: Google Sheets API
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
    "GOOGLE_PLACES_KEY": os.getenv("GOOGLE_PLACES_KEY"),
    
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

    # Google Sheets Integration
    "GOOGLE_SHEET_NAME": "Prospecting Pipeline & Audit Data",
    "GOOGLE_SHEETS_CREDENTIALS_JSON": "service_account.json",  # Path to Google service account key
    "FALLBACK_LOCAL_CSV": "prospecting_leads.csv",

    # Output Destination Directory for Rendered Videos
    "OUTPUT_DIR": Path(r"G:\My Drive\Elkins Revenue Consulting\AI Agent Scripts\ElkinsRev Prospect Videos")
}

# Ensure destination directory exists on startup
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
# 1. DISCOVERY & SCRAPING ENGINE
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


def scrape_site_footprint(website_url: str) -> dict:
    """Scrapes homepage HTML for emails, social links, logo, technical SEO, and conversion friction."""
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

        # 1. Public email discovery
        emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', resp.text)
        valid_emails = [e for e in emails if not e.endswith(('.png', '.jpg', '.webp', '.svg'))]
        if valid_emails:
            details["email"] = valid_emails[0]

        # 2. Social links discovery
        for link in soup.find_all("a", href=True):
            href = link["href"].lower()
            for platform in ["facebook.com", "instagram.com", "linkedin.com", "youtube.com", "tiktok.com"]:
                if platform in href and href not in details["social_links"]:
                    details["social_links"].append(href)

        # 3. Conversion checks
        has_form = bool(soup.find_all("form"))
        details["has_lead_form"] = has_form
        if not has_form:
            details["missing_elements"].append("No Direct Lead Capture Form")

        has_tel = bool(soup.find("a", href=re.compile(r"^tel:")))
        details["has_click_to_call"] = has_tel
        if not has_tel:
            details["missing_elements"].append("No Tap-to-Call Link")

        # 4. Technical SEO checks
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

        # 5. Scrape prospect logo / icon
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
# 2. AUDIT & OUTREACH COMPOSITION (NRP CLUSTER)
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
        "temperature": 0.3
    }
    res = requests.post(f"{CONFIG['NRP_ENDPOINT']}/chat/completions", headers=headers, json=payload)
    res.raise_for_status()
    return res.json()["choices"][0]["message"]["content"]

def audit_and_compose(lead: dict, footprint: dict) -> dict:
    """Drafts executive audio voiceover paired with distinct scannable slide bullets."""
    audit_prompt = f"""
    Analyze this business and its digital footprint. Return a structured JSON object.
    
    Business Name: {lead['name']}
    Website: {lead['website']}
    Google Reviews: {lead.get('rating', 0)} stars across {lead.get('review_count', 0)} reviews
    Page Load Time: {footprint['load_speed_sec']} seconds
    Direct Lead Form Present: {footprint.get('has_lead_form', False)}
    Tap-to-Call Link Present: {footprint.get('has_click_to_call', False)}
    Mobile Responsive Viewport: {footprint.get('is_mobile_responsive', False)}
    Structured Schema (JSON-LD): {footprint.get('has_schema', False)}
    Meta Description Present: {footprint.get('has_meta_desc', False)}
    Identified Social Accounts: {footprint['social_links']}
    Technical/UX Flags: {footprint['missing_elements']}
    Website Text Sample: {footprint['content_snippet']}
    
    CRITICAL PRESENTATION RULES:
    1. The 'intro_voiceover' MUST state:
       - What was examined during the preliminary research (speed, capture friction, SEO, mobile compatibility).
       - What the presentation reveals (the single primary bottleneck draining revenue and customer inquiries).
       - What is proposed at the conclusion (an immediate, friction-free strategic roadmap to resolve it).
    2. SLIDE TEXT MUST NOT MATCH SPOKEN AUDIO:
       - 'bullets' MUST be an array of 3 concise, punchy bullet points (max 10-12 words each) summarizing key takeaways.
       - 'voiceover' is the full executive narrative spoken by the narrator (~15-18 seconds per slide).

    Required JSON response format:
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
      "email_subject": "<custom subject line>",
      "email_body": "<under 120 words referencing audit and attached video>",
      "intro_voiceover": "<Spoken audio explaining: research conducted, what we show today, and proposal at end>",
      "intro_bullets": [
         "Audited website performance, lead flow & search visibility",
         "Pinpointed key leakage point hurting buyer conversions",
         "Delivering targeted strategic implementation plan"
      ],
      "video_script": [
         {{
           "eyebrow": "01 / EXECUTIVE AUDIT FINDING",
           "slide_title": "Primary Revenue Bottleneck",
           "bullets": [
             "<bullet 1 highlighting the specific technical/UX failure>",
             "<bullet 2 showing impact on mobile or local user experience>",
             "<bullet 3 contrasting against high-converting benchmark>"
           ],
           "voiceover": "<15 seconds executive narrative explaining this bottleneck>"
         }},
         {{
           "eyebrow": "02 / REVENUE & PIPELINE IMPACT",
           "slide_title": "Market Share & Lead Leakage",
           "bullets": [
             "<bullet 1 showing loss of daily inbound inquiries>",
             "<bullet 2 showing competitors capturing this volume>",
             "<bullet 3 quantifying conversion dropoff rate>"
           ],
           "voiceover": "<15 seconds narrative analyzing the lost revenue impact>"
         }},
         {{
           "eyebrow": "03 / PROPOSED STRATEGIC FIX",
           "slide_title": "The High-ROI Solution",
           "bullets": [
             "<bullet 1 immediate tactical fix (quick win)>",
             "<bullet 2 structural conversion architecture upgrade>",
             "<bullet 3 projected lift in qualified buyer response>"
           ],
           "voiceover": "<15 seconds narrative presenting the turnkey solution>"
         }},
         {{
           "eyebrow": "04 / RECOMMENDED NEXT STEP",
           "slide_title": "Implementation & Next Steps",
           "bullets": [
             "<bullet 1 zero-friction strategic review session>",
             "<bullet 2 examine complete technical diagnostic data>",
             "<bullet 3 turnkey rollout with no internal team overhead>"
           ],
           "voiceover": "<12 seconds narrative delivering clear, zero-friction call to action>"
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
# 3. SLIDE DECK RENDERER (Clean Light Mode + Bullet Support)
# ==============================================================================
def load_font(font_name_list, size):
    for name in font_name_list:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()

def draw_agency_brand(draw, img, content_x, header_y):
    """Renders clean dark agency brand header."""
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

def create_title_slide(lead_name: str, bullets: list, output_path: str, prospect_logo_path: str):
    """Renders executive white intro slide with method overview bullets."""
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

    # Wide Eyebrow Pill
    pill_y = header_y + 90
    pill_text = "CONFIDENTIAL EXECUTIVE BRIEFING · RESEARCH & STRATEGY"
    bbox_pill = draw.textbbox((0, 0), pill_text, font=font_pill)
    pw = (bbox_pill[2] - bbox_pill[0]) + 48
    draw.rounded_rectangle([content_x, pill_y, content_x + pw, pill_y + 44], radius=10, fill=STYLE["PILL_BG"], outline=STYLE["ACCENT_BLUE"], width=1)
    draw.text((content_x + 24, pill_y + 9), pill_text, fill=STYLE["ACCENT_BLUE"], font=font_pill)

    # Prospect Logo or Pill
    logo_y = pill_y + 75
    placed_prospect_logo = False
    if os.path.exists(prospect_logo_path):
        try:
            p_logo = Image.open(prospect_logo_path).convert("RGBA")
            p_logo.thumbnail((260, 80), Image.Resampling.LANCZOS)
            img.paste(p_logo, (content_x, logo_y), p_logo)
            placed_prospect_logo = True
        except Exception:
            pass

    if not placed_prospect_logo:
        draw.rounded_rectangle([content_x, logo_y, content_x + 240, logo_y + 60], radius=8, fill=STYLE["CARD_BORDER"])
        draw.text((content_x + 26, logo_y + 12), "PROSPECT AUDIT", fill=STYLE["TEXT_FAINT"], font=font_badge)

    # Title & Subtitle
    title_y = logo_y + 90
    draw.text((content_x, title_y), "Digital Diagnostic & Revenue Roadmap", fill=STYLE["TEXT_MAIN"], font=font_title)
    draw.line((content_x, title_y + 85, content_x + 280, title_y + 85), fill=STYLE["ACCENT_BLUE"], width=6)

    sub_y = title_y + 105
    draw.text((content_x, sub_y), f"Prepared Exclusively for Leadership at: {lead_name}", fill=STYLE["TEXT_MUTED"], font=font_sub)

    # Render Method / Scope Summary Bullets
    bullet_y = sub_y + 70
    fallback_bullets = [
        "Audited website performance, lead flow & search visibility",
        "Pinpointed key leakage points reducing buyer conversions",
        "Proposing immediate high-ROI strategic implementation plan"
    ]
    render_bullets = bullets if bullets and len(bullets) >= 3 else fallback_bullets

    for b in render_bullets[:3]:
        # Bullet Dot
        draw.ellipse([content_x + 4, bullet_y + 12, content_x + 20, bullet_y + 28], fill=STYLE["ACCENT_BLUE"])
        draw.text((content_x + 40, bullet_y), b, fill=STYLE["TEXT_MAIN"], font=font_bullet)
        bullet_y += 58

    img.save(output_path)

def create_body_slide(eyebrow: str, title: str, bullets: list, output_path: str):
    """Renders executive diagnostic body slides with bullet points."""
    W, H = 1920, 1080
    img = Image.new("RGB", (W, H), color=STYLE["BG"])
    draw = ImageDraw.Draw(img)

    margin_x, margin_y = 100, 70
    draw.rounded_rectangle([margin_x, margin_y, W - margin_x, H - margin_y], radius=24, fill=STYLE["CARD_BG"], outline=STYLE["CARD_BORDER"], width=2)

    font_pill = load_font(["arialbd.ttf", "segoeuib.ttf"], 22)
    font_title = load_font(["arialbd.ttf", "segoeuib.ttf"], 68)
    font_bullet = load_font(["arial.ttf", "segoeui.ttf"], 42)
    font_footer = load_font(["arial.ttf", "segoeui.ttf"], 22)

    content_x = margin_x + 100
    content_max_w = W - margin_x - 100
    header_y = margin_y + 60
    draw_agency_brand(draw, img, content_x, header_y)

    # Dynamic Wide Eyebrow Pill (Accommodates any label length)
    pill_y = header_y + 90
    pill_text = eyebrow.upper()
    bbox = draw.textbbox((0, 0), pill_text, font=font_pill)
    pill_w = (bbox[2] - bbox[0]) + 48
    draw.rounded_rectangle([content_x, pill_y, content_x + pill_w, pill_y + 44], radius=8, fill=STYLE["PILL_BG"], outline=STYLE["ACCENT_BLUE"], width=1)
    draw.text((content_x + 24, pill_y + 9), pill_text, fill=STYLE["ACCENT_BLUE"], font=font_pill)

    # Main Slide Title
    title_y = pill_y + 75
    draw.text((content_x, title_y), title, fill=STYLE["TEXT_MAIN"], font=font_title)
    draw.line((content_x, title_y + 95, content_x + 240, title_y + 95), fill=STYLE["ACCENT_BLUE"], width=6)

    # Render Summary Bullets
    bullet_y = title_y + 150
    for b in bullets[:4]:
        # Bullet indicator dot
        draw.ellipse([content_x + 4, bullet_y + 16, content_x + 22, bullet_y + 34], fill=STYLE["ACCENT_BLUE"])
        
        # Word wrap bullet point text to prevent overflow
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
            bullet_y += 56
        bullet_y += 28

    # Footer
    footer_y = H - margin_y - 65
    draw.line((content_x, footer_y - 20, content_max_w, footer_y - 20), fill=STYLE["CARD_BORDER"], width=1)
    draw.text((content_x, footer_y), "CONFIDENTIAL · PREPARED FOR EXECUTIVE REVIEW", fill=STYLE["TEXT_FAINT"], font=font_footer)
    draw.text((W - margin_x - 380, footer_y), CONFIG.get("AGENCY_WEBSITE", "WWW.ELKINSREVENUE.COM").upper(), fill=STYLE["ACCENT_BLUE"], font=font_footer)

    img.save(output_path)

def create_outro_slide(output_path: str):
    """Renders clean contact closing slide."""
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
    draw.text((content_x, title_y), "Ready to Eliminate Digital Leakage?", fill=STYLE["TEXT_MAIN"], font=font_title)
    draw.line((content_x, title_y + 95, content_x + 280, title_y + 95), fill=STYLE["ACCENT_BLUE"], width=6)
    
    sub_y = title_y + 125
    draw.text((content_x, sub_y), "Let's review the complete diagnostic dataset and implement the roadmap.", fill=STYLE["TEXT_MUTED"], font=font_sub)

    # 3-Column Contact Coordinates Card
    box_y = sub_y + 90
    box_w = W - (content_x * 2)
    draw.rounded_rectangle([content_x, box_y, content_x + box_w, box_y + 175], radius=16, fill=STYLE["BG"], outline=STYLE["CARD_BORDER"], width=2)

    col_w = box_w // 3
    # Col 1: Web
    draw.text((content_x + 40, box_y + 35), "VISIT US ONLINE", fill=STYLE["TEXT_FAINT"], font=font_contact_title)
    draw.text((content_x + 40, box_y + 88), CONFIG["AGENCY_WEBSITE"], fill=STYLE["ACCENT_BLUE"], font=font_contact_val)

    # Col 2: Phone
    draw.text((content_x + col_w + 40, box_y + 35), "DIRECT INQUIRIES", fill=STYLE["TEXT_FAINT"], font=font_contact_title)
    draw.text((content_x + col_w + 40, box_y + 88), CONFIG["AGENCY_PHONE"], fill=STYLE["TEXT_MAIN"], font=font_contact_val)

    # Col 3: Email
    draw.text((content_x + (col_w * 2) + 40, box_y + 35), "EMAIL OUR TEAM", fill=STYLE["TEXT_FAINT"], font=font_contact_title)
    draw.text((content_x + (col_w * 2) + 40, box_y + 88), CONFIG["AGENCY_EMAIL"], fill=STYLE["TEXT_MAIN"], font=font_contact_val)

    img.save(output_path)

# ==============================================================================
# 4. AUDIO & VIDEO COMPILATION
# ==============================================================================
def generate_tts_google(text: str, output_audio_path: str):
    """Generates free voiceover via Google TTS."""
    tts = gTTS(text=text, lang="en", tld="com", slow=False)
    tts.save(output_audio_path)

def generate_voiceover(text: str, output_audio_path: str):
    """Routes voiceover generation based on configured engine."""
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
            raise RuntimeError(f"ElevenLabs API Error {res.status_code}: {res.text}")

        with open(output_audio_path, "wb") as f:
            f.write(res.content)
    else:
        print("    [VOICE] Rendering with Google TTS (Free)...")
        generate_tts_google(text, output_audio_path)

def assemble_pitch_video(company_name: str, audit_data: dict, prospect_logo_path: str, output_video_path: str) -> str:
    """Builds complete executive video presentation."""
    clips = []
    temp_files = []

    # 1. Intro Slide (Spoken research & roadmap + bullet points)
    intro_img = "slide_intro.png"
    intro_audio = "audio_intro.mp3"
    temp_files.extend([intro_img, intro_audio])
    create_title_slide(company_name, audit_data.get("intro_bullets", []), intro_img, prospect_logo_path)
    generate_voiceover(audit_data.get("intro_voiceover", f"Welcome. In this briefing we review the digital baseline and revenue performance for {company_name}."), intro_audio)

    a_clip = AudioFileClip(intro_audio)
    clips.append(ImageClip(intro_img).with_duration(a_clip.duration).with_audio(a_clip))

    # 2. Body Slides
    for i, slide in enumerate(audit_data["video_script"]):
        s_img = f"slide_{i}.png"
        s_audio = f"audio_{i}.mp3"
        temp_files.extend([s_img, s_audio])

        create_body_slide(eyebrow=slide.get("eyebrow", f"0{i+1} / STRATEGIC BRIEF"),
                          title=slide["slide_title"],
                          bullets=slide.get("bullets", []),
                          output_path=s_img)
        generate_voiceover(slide["voiceover"], s_audio)

        a_clip = AudioFileClip(s_audio)
        clips.append(ImageClip(s_img).with_duration(a_clip.duration).with_audio(a_clip))

    # 3. Outro Slide
    outro_img = "slide_outro.png"
    outro_audio = "audio_outro.mp3"
    temp_files.extend([outro_img, outro_audio])
    create_outro_slide(outro_img)
    generate_voiceover(audit_data.get("outro_voiceover", f"Visit {CONFIG['AGENCY_WEBSITE']} to connect with our strategic team."), outro_audio)

    a_clip = AudioFileClip(outro_audio)
    clips.append(ImageClip(outro_img).with_duration(a_clip.duration).with_audio(a_clip))

    # Compile Video
    final_video = concatenate_videoclips(clips, method="compose")
    final_video.write_videofile(output_video_path, fps=24, codec="libx264", audio_codec="aac", logger=None)

    # Cleanup temp files
    for f in temp_files:
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                pass

    if os.path.exists(prospect_logo_path):
        try:
            os.remove(prospect_logo_path)
        except Exception:
            pass

    return output_video_path

# ==============================================================================
# 5. DATA PERSISTENCE: GOOGLE SHEETS & LOCAL CSV
# ==============================================================================
def save_records_to_google_sheet(records: list):
    """Appends records to Google Sheets if credentials exist; falls back to local CSV."""
    if not records:
        return

    df = pd.DataFrame(records)
    creds_file = CONFIG.get("GOOGLE_SHEETS_CREDENTIALS_JSON")

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
            
            # Prepare rows
            existing_values = sheet.get_all_values()
            headers = list(df.columns)
            
            if not existing_values:
                # New sheet: add headers and rows
                sheet.append_row(headers)
            
            rows = df.values.tolist()
            sheet.append_rows(rows)
            print(f"\n[GOOGLE SHEETS] Successfully appended {len(records)} record(s) to '{sheet_name}'.")
            return
        except Exception as e:
            print(f"\n[GOOGLE SHEETS ERROR] Failed syncing with Google Sheets: {e}")
            print("Falling back to local CSV append...")

    # Fallback to Local CSV
    csv_file = CONFIG["FALLBACK_LOCAL_CSV"]
    file_exists = os.path.exists(csv_file)
    df.to_csv(csv_file, mode="a", header=not file_exists, index=False)
    print(f"\n[LOCAL CSV] Saved {len(records)} record(s) to '{csv_file}'.")

# ==============================================================================
# 6. EMAIL TRANSMISSION
# ==============================================================================
def send_prospect_email(to_email: str, subject: str, body: str, attachment_path: str):
    """Sends the outreach email with the mp4 video attached."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = CONFIG["SENDER_EMAIL"]
    msg["To"] = to_email
    msg.set_content(body)
    
    if os.path.exists(attachment_path):
        with open(attachment_path, "rb") as f:
            file_data = f.read()
            file_name = os.path.basename(attachment_path)
        msg.add_attachment(file_data, maintype="video", subtype="mp4", filename=file_name)
        
    with smtplib.SMTP_SSL(CONFIG["SMTP_SERVER"], CONFIG["SMTP_PORT"]) as server:
        server.login(CONFIG["SENDER_EMAIL"], CONFIG["SENDER_PASSWORD"])
        server.send_message(msg)

# ==============================================================================
# 7. MAIN PIPELINE
# ==============================================================================
def main():
    print("\n--- B2B Prospecting & Custom Video Pipeline ---")
    mode_choice = input("Select audio mode: [1] Free Preview (Google)  [2] Final Production (ElevenLabs): ").strip()
    CONFIG["TTS_ENGINE"] = "elevenlabs" if mode_choice == "2" else "google"
    print(f"-> Active Voice Engine: {CONFIG['TTS_ENGINE'].upper()}")
    
    category = input("Enter target business category (e.g., HVAC, Locksmith, Roofing): ").strip()
    location = input("Enter target geographic region (e.g., Naples FL, Denver CO): ").strip()

    count_input = input("How many businesses to return and process? [Default 1, Max 20]: ").strip()
    try:
        limit = int(count_input) if count_input else 1
        if limit < 1:
            limit = 1
    except ValueError:
        print("-> Invalid input detected, defaulting to 1 business.")
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
        
        print("  -> Scraping website, discovering assets & footprint...")
        footprint = scrape_site_footprint(website)
        
        print("  -> Performing digital audit & drafting voiceover + slide bullets via NRP cluster...")
        audit = audit_and_compose(lead, footprint)
        
        clean_name = re.sub(r'[^a-zA-Z0-9]', '', name)
        video_filename = f"{clean_name}_audit_brief.mp4"
        video_full_path = str(CONFIG["OUTPUT_DIR"] / video_filename)
        
        print(f"  -> Rendering complete executive presentation to: {video_full_path}")
        assemble_pitch_video(name, audit, footprint["logo_img_path"], video_full_path)
        
        email_recipient = footprint["email"]
        delivery_status = "Skipped (No Email)"
        
        if email_recipient != "Not Listed" and "@" in email_recipient:
            print(f"  -> Sending prospecting email to {email_recipient}...")
            try:
                send_prospect_email(email_recipient, audit["email_subject"], audit["email_body"], video_full_path)
                delivery_status = "Email Sent with Video"
            except Exception as e:
                print(f"  -> Email delivery failed: {e}")
                delivery_status = f"Failed ({e})"
        
        records.append({
            "Business Name": name,
            "Address": lead["address"],
            "Website": website,
            "Contact Email": email_recipient,
            "Google Rating": lead.get("rating", 0),
            "Review Count": lead.get("review_count", 0),
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
            "Video Asset": video_full_path
        })
        
    # Persist data to Google Sheets (or fallback CSV)
    save_records_to_google_sheet(records)
    print("\n[SUCCESS] Pipeline run complete.")

if __name__ == "__main__":
    main()