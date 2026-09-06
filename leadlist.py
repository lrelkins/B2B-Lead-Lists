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

# ==============================================================================
# CONFIGURATION & CREDENTIALS
# ==============================================================================
CONFIG = {
    # Custom LLM / NRP Nautilus Endpoint
    "NRP_ENDPOINT": os.getenv("NRP_ENDPOINT", "https://ellm.nrp-nautilus.io/v1"),
    "NRP_API_KEY": os.getenv("NRP_API_KEY", "your-nrp-api-key"),
    "MODEL_NAME": "qwen3",
    
    # Google Places API (New)
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
    "OUTPUT_CSV": "prospecting_leads.csv",

    # Output Destination Directory for Rendered Videos
    "OUTPUT_DIR": Path(r"G:\My Drive\Elkins Revenue Consulting\AI Agent Scripts\ElkinsRev Prospect Videos")
}

# Ensure destination directory exists on startup
CONFIG["OUTPUT_DIR"].mkdir(parents=True, exist_ok=True)

# ==============================================================================
# 1. DISCOVERY & SCRAPING ENGINE
# ==============================================================================
def find_businesses(category: str, location: str, limit: int = 1) -> list:
    """Discovers targets via Google Places API (New Text Search)."""
    api_key = CONFIG.get("GOOGLE_PLACES_KEY")
    if not api_key or api_key == "your-places-api-key":
        print("\n[CONFIG ERROR] Missing Google Places API Key in environment or CONFIG.")
        return []

    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.displayName,places.websiteUri,places.formattedAddress,places.rating,places.userRatingCount"
    }
    payload = {"textQuery": f"{category} in {location}", "maxResultCount": limit}

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

        # 3. Conversion & Lead Capture checks
        has_form = bool(soup.find_all("form"))
        details["has_lead_form"] = has_form
        if not has_form:
            details["missing_elements"].append("No Direct Lead Capture Form")

        has_tel = bool(soup.find("a", href=re.compile(r"^tel:")))
        details["has_click_to_call"] = has_tel
        if not has_tel:
            details["missing_elements"].append("No Tap-to-Call Link")

        # 4. Technical SEO & Schema checks
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
    """Evaluates the expanded digital audit, isolates core weakness, and drafts video narrative."""
    audit_prompt = f"""
    Analyze the digital footprint and local market visibility of this business and return a JSON object.
    
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
      "core_weakness": "<name of lowest category and specific diagnostic reason>",
      "quick_win": "<one immediate, high-impact tactical fix>",
      "solution": "<our agency's targeted, high-ROI fix>",
      "email_subject": "<compelling, non-spammy subject line referencing their specific bottleneck>",
      "email_body": "<under 130 words, referencing their bottleneck, proposing the quick win, and referencing the attached video>",
      "intro_voiceover": "Welcome. In this brief executive briefing, we review the digital baseline and revenue performance for {lead['name']}.",
      "video_script": [
         {{"slide_title": "Current Bottleneck", "voiceover": "<15 seconds breaking down what is currently losing them leads>"}},
         {{"slide_title": "Revenue Impact", "voiceover": "<15 seconds highlighting the impact of this weakness on local market share>"}},
         {{"slide_title": "The Strategic Fix", "voiceover": "<15 seconds outlining our agency solution and immediate quick win>"}},
         {{"slide_title": "Action Step", "voiceover": "<12 seconds zero-friction call to action>"}}
      ],
      "outro_voiceover": "To review the complete audit findings or discuss implementation, contact Elkins and Co at elkinsrevenue.com."
    }}
    Return ONLY pure, valid JSON.
    """
    raw_response = call_nrp_llm(audit_prompt)
    clean_json = re.search(r'\{.*\}', raw_response, re.DOTALL).group(0)
    return json.loads(clean_json)

# ==============================================================================
# 3. HIGH-IMPACT SLIDE DECK RENDERER
# ==============================================================================
def load_font(font_name_list, size):
    for name in font_name_list:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()

def draw_agency_brand(draw, img, content_x, header_y):
    """Renders the text-based brand mark matching the website identity."""
    TEXT_WHITE = (255, 255, 255)
    ACCENT_BLUE = (37, 99, 235)
    SLATE_GRAY = (148, 163, 184)
    DIVIDER_COLOR = (71, 85, 105)

    font_main = load_font(["arialbd.ttf", "segoeuib.ttf", "helvetica.ttf"], 30)
    font_sub = load_font(["arialbd.ttf", "segoeuib.ttf", "helvetica.ttf"], 20)

    # 1. Primary Name: "ELKINS & CO."
    primary_text = CONFIG.get("BRAND_PRIMARY", "ELKINS & CO.")
    draw.text((content_x, header_y), primary_text, fill=TEXT_WHITE, font=font_main)
    bbox_main = draw.textbbox((content_x, header_y), primary_text, font=font_main)
    main_w = bbox_main[2] - bbox_main[0]

    # 2. Vertical Divider
    divider_x = content_x + main_w + 20
    draw.line([(divider_x, header_y + 4), (divider_x, header_y + 32)], fill=DIVIDER_COLOR, width=2)

    # 3. Strategy Subtitle: "REVENUE STRATEGIES"
    sub_text = CONFIG.get("BRAND_SUBTITLE", "REVENUE STRATEGIES")
    draw.text((divider_x + 20, header_y + 7), sub_text, fill=ACCENT_BLUE, font=font_sub)

def create_title_slide(lead_name: str, output_path: str, prospect_logo_path: str):
    """Renders the executive title slide with co-branded badges and audit title."""
    W, H = 1920, 1080
    BG_COLOR, CARD_BG = (15, 23, 42), (30, 41, 59)
    CARD_BORDER, ACCENT_BLUE = (51, 65, 85), (37, 99, 235)
    TEXT_WHITE, SLATE_GRAY, TEXT_MUTED = (255, 255, 255), (148, 163, 184), (226, 232, 240)

    img = Image.new("RGB", (W, H), color=BG_COLOR)
    draw = ImageDraw.Draw(img)

    margin_x, margin_y = 100, 70
    draw.rounded_rectangle([margin_x, margin_y, W - margin_x, H - margin_y], radius=20, fill=CARD_BG, outline=CARD_BORDER, width=2)

    content_x = margin_x + 100
    header_y = margin_y + 60
    draw_agency_brand(draw, img, content_x, header_y)

    font_pill = load_font(["arialbd.ttf", "segoeuib.ttf"], 24)
    font_main_title = load_font(["arialbd.ttf", "segoeuib.ttf"], 70)
    font_sub = load_font(["arial.ttf", "segoeui.ttf"], 38)
    font_badge = load_font(["arialbd.ttf", "segoeuib.ttf"], 34)

    # Category Pill
    pill_y = header_y + 110
    draw.rounded_rectangle([content_x, pill_y, content_x + 360, pill_y + 44], radius=8, fill=ACCENT_BLUE)
    draw.text((content_x + 24, pill_y + 8), "CONFIDENTIAL AUDIT BRIEFING", fill=TEXT_WHITE, font=font_pill)

    # Prospect Logo / Badge
    logo_y = pill_y + 85
    placed_prospect_logo = False
    if os.path.exists(prospect_logo_path):
        try:
            p_logo = Image.open(prospect_logo_path).convert("RGBA")
            p_logo.thumbnail((260, 90), Image.Resampling.LANCZOS)
            img.paste(p_logo, (content_x, logo_y), p_logo)
            placed_prospect_logo = True
        except Exception:
            pass

    if not placed_prospect_logo:
        draw.rounded_rectangle([content_x, logo_y, content_x + 220, logo_y + 70], radius=10, fill=CARD_BORDER)
        draw.text((content_x + 30, logo_y + 16), "PROSPECT", fill=SLATE_GRAY, font=font_badge)

    # Main Title
    title_y = logo_y + 110
    draw.text((content_x, title_y), "Digital Performance & Revenue Audit", fill=TEXT_WHITE, font=font_main_title)
    draw.line((content_x, title_y + 95, content_x + 260, title_y + 95), fill=ACCENT_BLUE, width=6)
    
    # Subtext
    sub_y = title_y + 130
    draw.text((content_x, sub_y), f"Prepared Exclusively for Leadership at: {lead_name}", fill=TEXT_MUTED, font=font_sub)
    draw.text((content_x, sub_y + 60), "Executive Assessment of Conversion Infrastructure, Local Visibility & Growth Bottlenecks", fill=SLATE_GRAY, font=font_sub)

    img.save(output_path)

def create_body_slide(slide_index: int, title: str, text: str, output_path: str):
    """Renders high-visibility diagnostic body slides."""
    W, H = 1920, 1080
    BG_COLOR, CARD_BG = (15, 23, 42), (30, 41, 59)
    CARD_BORDER, ACCENT_BLUE = (51, 65, 85), (37, 99, 235)
    TEXT_WHITE, TEXT_MUTED, SLATE_GRAY = (255, 255, 255), (226, 232, 240), (148, 163, 184)

    img = Image.new("RGB", (W, H), color=BG_COLOR)
    draw = ImageDraw.Draw(img)

    margin_x, margin_y = 100, 70
    draw.rounded_rectangle([margin_x, margin_y, W - margin_x, H - margin_y], radius=20, fill=CARD_BG, outline=CARD_BORDER, width=2)

    font_pill = load_font(["arialbd.ttf", "segoeuib.ttf"], 24)
    font_title = load_font(["arialbd.ttf", "segoeuib.ttf"], 72)
    font_body = load_font(["arial.ttf", "segoeui.ttf"], 46)
    font_footer = load_font(["arial.ttf", "segoeui.ttf"], 22)

    content_x = margin_x + 100
    content_max_w = W - margin_x - 100
    header_y = margin_y + 60
    draw_agency_brand(draw, img, content_x, header_y)

    # Slide Category Pill
    pill_y = header_y + 105
    pill_labels = [
        "01 / EXECUTIVE AUDIT FINDING",
        "02 / REVENUE & TRAFFIC IMPACT",
        "03 / PROPOSED STRATEGIC FIX",
        "04 / RECOMMENDED NEXT STEP"
    ]
    pill_label = pill_labels[slide_index] if slide_index < len(pill_labels) else "STRATEGIC BRIEF"
    
    bbox = draw.textbbox((0, 0), pill_label, font=font_pill)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pill_rect = [content_x, pill_y, content_x + tw + 48, pill_y + th + 20]
    draw.rounded_rectangle(pill_rect, radius=8, fill=ACCENT_BLUE)
    draw.text((content_x + 24, pill_y + 10), pill_label, fill=TEXT_WHITE, font=font_pill)

    # Headline
    title_y = pill_rect[3] + 40
    draw.text((content_x, title_y), title, fill=TEXT_WHITE, font=font_title)
    draw.line((content_x, title_y + 110, content_x + 240, title_y + 110), fill=ACCENT_BLUE, width=6)

    # Body Text (Wrapped to 68 characters for widescreen readability)
    body_y = title_y + 170
    words = text.split()
    lines, current_line = [], []
    for word in words:
        if len(" ".join(current_line + [word])) < 68:
            current_line.append(word)
        else:
            lines.append(" ".join(current_line))
            current_line = [word]
    lines.append(" ".join(current_line))

    for line in lines[:5]:
        draw.text((content_x, body_y), line, fill=TEXT_MUTED, font=font_body)
        body_y += 72

    # Footer
    footer_y = H - margin_y - 70
    draw.line((content_x, footer_y - 20, content_max_w, footer_y - 20), fill=CARD_BORDER, width=1)
    draw.text((content_x, footer_y), "CONFIDENTIAL · PREPARED FOR EXECUTIVE REVIEW", fill=SLATE_GRAY, font=font_footer)
    draw.text((W - margin_x - 380, footer_y), CONFIG.get("AGENCY_WEBSITE", "WWW.ELKINSREVENUE.COM").upper(), fill=ACCENT_BLUE, font=font_footer)

    img.save(output_path)

def create_outro_slide(output_path: str):
    """Renders the executive closing slide with agency contact coordinates."""
    W, H = 1920, 1080
    BG_COLOR, CARD_BG = (15, 23, 42), (30, 41, 59)
    CARD_BORDER, ACCENT_BLUE = (51, 65, 85), (37, 99, 235)
    TEXT_WHITE, TEXT_MUTED, SLATE_GRAY = (255, 255, 255), (226, 232, 240), (148, 163, 184)

    img = Image.new("RGB", (W, H), color=BG_COLOR)
    draw = ImageDraw.Draw(img)

    margin_x, margin_y = 100, 70
    draw.rounded_rectangle([margin_x, margin_y, W - margin_x, H - margin_y], radius=20, fill=CARD_BG, outline=CARD_BORDER, width=2)

    font_title = load_font(["arialbd.ttf", "segoeuib.ttf"], 72)
    font_sub = load_font(["arial.ttf", "segoeui.ttf"], 40)
    font_contact_title = load_font(["arialbd.ttf", "segoeuib.ttf"], 36)
    font_contact_val = load_font(["arial.ttf", "segoeui.ttf"], 36)

    content_x = margin_x + 100
    header_y = margin_y + 60
    draw_agency_brand(draw, img, content_x, header_y)

    title_y = header_y + 140
    draw.text((content_x, title_y), "Ready to Eliminate Digital Leakage?", fill=TEXT_WHITE, font=font_title)
    draw.line((content_x, title_y + 100, content_x + 280, title_y + 100), fill=ACCENT_BLUE, width=6)
    
    sub_y = title_y + 130
    draw.text((content_x, sub_y), "Let's review the full diagnostic dataset and implement the fix.", fill=TEXT_MUTED, font=font_sub)

    # 3-Column Contact Coordinates Card
    box_y = sub_y + 100
    box_w = W - (content_x * 2)
    draw.rounded_rectangle([content_x, box_y, content_x + box_w, box_y + 180], radius=16, fill=(15, 23, 42), outline=CARD_BORDER, width=2)

    col_w = box_w // 3
    # Col 1: Web
    draw.text((content_x + 50, box_y + 40), "VISIT US ONLINE", fill=SLATE_GRAY, font=font_contact_title)
    draw.text((content_x + 50, box_y + 95), CONFIG["AGENCY_WEBSITE"], fill=ACCENT_BLUE, font=font_contact_val)

    # Col 2: Phone
    draw.text((content_x + col_w + 50, box_y + 40), "DIRECT INQUIRIES", fill=SLATE_GRAY, font=font_contact_title)
    draw.text((content_x + col_w + 50, box_y + 95), CONFIG["AGENCY_PHONE"], fill=TEXT_WHITE, font=font_contact_val)

    # Col 3: Email
    draw.text((content_x + (col_w * 2) + 50, box_y + 40), "EMAIL OUR TEAM", fill=SLATE_GRAY, font=font_contact_title)
    draw.text((content_x + (col_w * 2) + 50, box_y + 95), CONFIG["AGENCY_EMAIL"], fill=TEXT_WHITE, font=font_contact_val)

    img.save(output_path)

# ==============================================================================
# 4. ELEVENLABS / GOOGLE AUDIO & VIDEO COMPILATION
# ==============================================================================
def generate_tts_google(text: str, output_audio_path: str):
    """Generates free scratch-track voiceover via Google TTS."""
    tts = gTTS(text=text, lang="en", tld="com", slow=False)
    tts.save(output_audio_path)


def generate_voiceover(text: str, output_audio_path: str):
    """Routes voiceover generation based on CONFIG['TTS_ENGINE']."""
    engine = CONFIG.get("TTS_ENGINE", "google").lower()

    if engine == "elevenlabs":
        api_key = os.getenv("ELEVENLABS_KEY") or CONFIG.get("ELEVENLABS_KEY")
        if not api_key or "your-" in api_key:
            print("    [VOICE] ElevenLabs key missing/invalid -> Falling back to Google TTS (Free)")
            generate_tts_google(text, output_audio_path)
            return

        print("    [VOICE] Rendering with ElevenLabs (Paid Credits)...")
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
        print("    [VOICE] Rendering with Google TTS (Free Preview)...")
        generate_tts_google(text, output_audio_path)


def assemble_pitch_video(company_name: str, audit_data: dict, prospect_logo_path: str, output_video_path: str) -> str:
    """Builds a complete 6-slide executive presentation video (Intro + 4 Content + Outro)."""
    clips = []
    temp_files = []

    # 1. Title Slide
    intro_img = "slide_intro.png"
    intro_audio = "audio_intro.mp3"
    temp_files.extend([intro_img, intro_audio])
    create_title_slide(company_name, intro_img, prospect_logo_path)
    generate_voiceover(audit_data.get("intro_voiceover", f"Welcome to the digital performance review for {company_name}."), intro_audio)

    a_clip = AudioFileClip(intro_audio)
    clips.append(ImageClip(intro_img).with_duration(a_clip.duration).with_audio(a_clip))

    # 2. Content Slides (4 diagnostic parts)
    for i, slide in enumerate(audit_data["video_script"]):
        s_img = f"slide_{i}.png"
        s_audio = f"audio_{i}.mp3"
        temp_files.extend([s_img, s_audio])

        create_body_slide(slide_index=i, title=slide["slide_title"], text=slide["voiceover"], output_path=s_img)
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

    # Stitch Video directly to target output path
    final_video = concatenate_videoclips(clips, method="compose")
    final_video.write_videofile(output_video_path, fps=24, codec="libx264", audio_codec="aac", logger=None)

    # Cleanup temp slides & audio
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
# 5. EMAIL TRANSMISSION
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
# 6. MAIN EXECUTION & CSV APPENDING ENGINE
# ==============================================================================
def main():
    print("\n--- B2B Prospecting & Custom Video Pipeline ---")
    mode_choice = input("Select audio mode: [1] Free Preview (Google)  [2] Final Production (ElevenLabs): ").strip()
    CONFIG["TTS_ENGINE"] = "elevenlabs" if mode_choice == "2" else "google"
    print(f"-> Active Voice Engine: {CONFIG['TTS_ENGINE'].upper()}")
    category = input("Enter target business category (e.g., HVAC, Locksmith, Event Planner): ").strip()
    location = input("Enter target geographic region (e.g., Naples FL, Denver CO): ").strip()
    
    print(f"\n[1/5] Finding businesses for '{category}' in '{location}'...")
    leads = find_businesses(category, location, limit=1)
    
    if not leads:
        print("\n[TERMINATED] No leads were retrieved. Inspect your search criteria or API status.")
        return
    
    records = []
    
    for lead in leads[:1]:
        name = lead["name"]
        website = lead["website"]
        print(f"\nProcessing: {name} ({website})")
        
        print("  -> Scraping website, discovering assets & footprint...")
        footprint = scrape_site_footprint(website)
        
        print("  -> Performing digital audit & drafting briefing via NRP cluster...")
        audit = audit_and_compose(lead, footprint)
        
        # Build clean filename and resolve full path in the target output folder
        clean_name = re.sub(r'[^a-zA-Z0-9]', '', name)
        video_filename = f"{clean_name}_audit_brief.mp4"
        video_full_path = str(CONFIG["OUTPUT_DIR"] / video_filename)
        
        print(f"  -> Rendering complete 6-slide video presentation to: {video_full_path}")
        assemble_pitch_video(name, audit, footprint["logo_img_path"], video_full_path)
        
        email_recipient = footprint["email"]
        delivery_status = "Skipped (No Email)"
        
        if email_recipient != "Not Listed" and "@" in email_recipient:
            print(f"  -> Sending prospecting email to {email_recipient}...")
            send_prospect_email(email_recipient, audit["email_subject"], audit["email_body"], video_full_path)
            delivery_status = "Email Sent with Video"
        
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
        
    df = pd.DataFrame(records)
    csv_file = CONFIG["OUTPUT_CSV"]
    
    # Non-destructive CSV append
    file_exists = os.path.exists(csv_file)
    df.to_csv(csv_file, mode="a", header=not file_exists, index=False)
    
    print(f"\n[SUCCESS] Execution complete. Appended {len(records)} lead(s) to '{csv_file}'.")

if __name__ == "__main__":
    main()