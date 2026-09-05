import os
import re
import json
import smtplib
import asyncio
from email.message import EmailMessage
from urllib.parse import urlparse
import requests
import pandas as pd
from bs4 import BeautifulSoup
import edge_tts
from moviepy import ImageClip, AudioFileClip, concatenate_videoclips
from PIL import Image, ImageDraw, ImageFont

# ==============================================================================
# CONFIGURATION & API KEYS
# ==============================================================================
CONFIG = {
    # Custom LLM / NRP API Endpoint
    "NRP_ENDPOINT": "https://ellm.nrp-nautilus.io/v1",
    "NRP_API_KEY": os.getenv("NRP_API_KEY", "your-nrp-api-key"),
    "MODEL_NAME": "qwen3",  # <-- Swapped from 'default-model' to your live cluster model
    # Places & Enrichment
    "GOOGLE_PLACES_KEY": os.getenv("GOOGLE_PLACES_KEY"),
    # Voiceover (ElevenLabs)
    "ELEVENLABS_KEY": os.getenv("ELEVENLABS_KEY", "your-elevenlabs-key"),
    # Email SMTP Settings
    "SMTP_SERVER": "smtp.gmail.com",
    "SMTP_PORT": 465,
    "SENDER_EMAIL": "your-email@domain.com",
    "SENDER_PASSWORD": "your-app-password",
    "OUTPUT_CSV": "prospecting_leads.csv",
}
# ==============================================================================
# 1. CORE DISCOVERY & SCRAPING
# ==============================================================================
def find_businesses(category: str, location: str, limit: int = 5) -> list:
    """Discovers targets via Google Places API (New Text Search) with full diagnostics."""
    api_key = CONFIG.get("GOOGLE_PLACES_KEY")
    if not api_key or api_key == "your-places-api-key":
        print("\n[CONFIG ERROR] Missing Google Places API Key in CONFIG['GOOGLE_PLACES_KEY'].")
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
    """Scrapes homepage HTML for emails, social links, and basic performance indicators."""
    details = {
        "email": "Not Listed",
        "social_links": [],
        "load_speed_sec": 0.0,
        "content_snippet": "",
        "missing_elements": []
    }
    if not website_url:
        return details
        
    try:
        start_time = requests.compat.time.time()
        resp = requests.get(website_url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        load_time = round(requests.compat.time.time() - start_time, 2)
        details["load_speed_sec"] = load_time
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Scrape raw email via regex
        emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', resp.text)
        valid_emails = [e for e in emails if not e.endswith(('.png', '.jpg', '.webp', '.svg'))]
        if valid_emails:
            details["email"] = valid_emails[0]
            
        # Detect Social Channels
        for link in soup.find_all("a", href=True):
            href = link["href"].lower()
            for platform in ["facebook.com", "instagram.com", "linkedin.com", "youtube.com", "tiktok.com"]:
                if platform in href and href not in details["social_links"]:
                    details["social_links"].append(href)
                    
        # Check conversion & SEO baseline
        h1s = soup.find_all("h1")
        if not h1s:
            details["missing_elements"].append("Missing H1 Header")
        if not re.search(r'href=["\']tel:', resp.text):
            details["missing_elements"].append("No Tap-to-Call Link")
            
        body_text = ' '.join([p.get_text() for p in soup.find_all(['p', 'h1', 'h2'])])
        details["content_snippet"] = body_text[:1500]
        
    except Exception as e:
        details["missing_elements"].append("Website Inaccessible/Slow")
        
    return details

# ==============================================================================
# 2. AUDIT & OUTREACH GENERATION (NRP ENDPOINT)
# ==============================================================================
def call_nrp_llm(prompt: str) -> str:
    """Sends prompt to your custom NRP LLM endpoint."""
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
    """Evaluates the digital presence, identifies core weakness, and drafts email & video script."""
    audit_prompt = f"""
    Analyze the digital footprint of this business and return a JSON object with your assessment.
    Business Name: {lead['name']}
    Website: {lead['website']}
    Page Load Time: {footprint['load_speed_sec']} seconds
    Identified Social Accounts: {footprint['social_links']}
    Technical/UX Flags: {footprint['missing_elements']}
    Website Text Sample: {footprint['content_snippet']}
    
    Required JSON response format:
    {{
      "scores": {{
         "seo": <1-100>,
         "social_media": <1-100>,
         "website_speed": <1-100>,
         "content_clarity": <1-100>
      }},
      "core_weakness": "<name of lowest category and specific diagnostic reason>",
      "solution": "<our agency's targeted, high-ROI fix>",
      "email_subject": "<compelling, non-spammy subject line>",
      "email_body": "<under 130 words, referencing their specific bottleneck, offering the fix, and referencing the attached 60s breakdown video>",
      "video_script": [
         {{"slide_title": "Current Bottleneck", "voiceover": "<15 seconds breaking down what is currently losing them leads>"}},
         {{"slide_title": "Missed Revenue", "voiceover": "<15 seconds highlighting the impact of this weakness on local traffic>"}},
         {{"slide_title": "The Strategic Fix", "voiceover": "<15 seconds outlining our agency solution>"}},
         {{"slide_title": "Next Step", "voiceover": "<15 seconds zero-friction call to action>"}}
      ]
    }}
    Return ONLY pure, valid JSON.
    """
    raw_response = call_nrp_llm(audit_prompt)
    clean_json = re.search(r'\{.*\}', raw_response, re.DOTALL).group(0)
    return json.loads(clean_json)

# ==============================================================================
# 3. 60-SECOND SLIDE VIDEO GENERATOR (MOVIEPY 2.0+ SYNTAX)
# ==============================================================================
def create_slide_image(
    slide_index: int,
    title: str,
    text: str,
    output_path: str,
    logo_path: str = "logo.png"
):
    """
    Renders an executive 1920x1080 widescreen presentation card matching
    the Elkins & Co. Revenue Strategies digital-studio brand identity.
    """
    W, H = 1920, 1080
    
    # 1. Base Canvas - Deep Slate/Navy Background
    BG_COLOR = (15, 23, 42)          # #0F172A
    CARD_BG = (30, 41, 59)           # #1E293B
    CARD_BORDER = (51, 65, 85)       # #334155
    ACCENT_BLUE = (37, 99, 235)      # #2563EB
    TEXT_WHITE = (255, 255, 255)     # #FFFFFF
    TEXT_MUTED = (203, 213, 225)     # #CBD5E1
    SLATE_GRAY = (148, 163, 184)     # #94A3B8

    img = Image.new("RGB", (W, H), color=BG_COLOR)
    draw = ImageDraw.Draw(img)

    # 2. Main Center Card Container (Rounded Modern UI)
    card_margin_x, card_margin_y = 120, 90
    card_rect = [card_margin_x, card_margin_y, W - card_margin_x, H - card_margin_y]
    draw.rounded_rectangle(card_rect, radius=24, fill=CARD_BG, outline=CARD_BORDER, width=2)

    # 3. Typography Selection (Falls back to default if TTF unavailable)
    try:
        font_brand = ImageFont.truetype("DejaVuSans-Bold.ttf", 26)
        font_pill = ImageFont.truetype("DejaVuSans-Bold.ttf", 20)
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", 60)
        font_body = ImageFont.truetype("DejaVuSans.ttf", 36)
        font_footer = ImageFont.truetype("DejaVuSans.ttf", 20)
    except:
        font_brand = font_pill = font_title = font_body = font_footer = ImageFont.load_default()

    # 4. Top Brand Header & Logo Lockup
    header_y = card_margin_y + 50
    content_x = card_margin_x + 80

    if os.path.exists(logo_path):
        try:
            logo = Image.open(logo_path).convert("RGBA")
            logo.thumbnail((260, 60), Image.Resampling.LANCZOS)
            img.paste(logo, (content_x, header_y), logo)
            brand_text_x = content_x + logo.width + 25
        except Exception:
            brand_text_x = content_x
    else:
        # Programmatic "Kinetic Pulse" Bar Graph Emblem fallback
        bar_x = content_x
        bar_w = 8
        draw.rectangle([bar_x, header_y + 18, bar_x + bar_w, header_y + 40], fill=SLATE_GRAY)
        draw.rectangle([bar_x + 14, header_y + 10, bar_x + 14 + bar_w, header_y + 40], fill=CARD_BORDER)
        draw.rectangle([bar_x + 28, header_y, bar_x + 28 + bar_w, header_y + 40], fill=ACCENT_BLUE)
        brand_text_x = content_x + 55

    draw.text((brand_text_x, header_y + 6), "ELKINS & CO · REVENUE STRATEGIES", fill=TEXT_MUTED, font=font_brand)
    
    # 5. Slide Category Pill / Badge
    pill_y = header_y + 100
    pill_labels = [
        "EXECUTIVE AUDIT FINDING",
        "REVENUE & TRAFFIC IMPACT",
        "PROPOSED STRATEGIC FIX",
        "RECOMMENDED ACTION STEP"
    ]
    pill_label = pill_labels[slide_index] if slide_index < len(pill_labels) else "DIAGNOSTIC BRIEF"
    
    bbox = draw.textbbox((0, 0), pill_label, font=font_pill)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pill_padding_x, pill_padding_y = 20, 8
    pill_rect = [content_x, pill_y, content_x + tw + (pill_padding_x * 2), pill_y + th + (pill_padding_y * 2)]
    
    draw.rounded_rectangle(pill_rect, radius=8, fill=ACCENT_BLUE)
    draw.text((content_x + pill_padding_x, pill_y + pill_padding_y), pill_label, fill=TEXT_WHITE, font=font_pill)

    # 6. Slide Title
    title_y = pill_rect[3] + 35
    draw.text((content_x, title_y), title, fill=TEXT_WHITE, font=font_title)
    
    line_y = title_y + 90
    draw.line((content_x, line_y, content_x + 200, line_y), fill=ACCENT_BLUE, width=5)

    # 7. Body Copy (Word Wrapped to 52 chars)
    body_y = line_y + 50
    words = text.split()
    lines, current_line = [], []
    for word in words:
        if len(" ".join(current_line + [word])) < 52:
            current_line.append(word)
        else:
            lines.append(" ".join(current_line))
            current_line = [word]
    lines.append(" ".join(current_line))

    for line in lines:
        draw.text((content_x, body_y), line, fill=TEXT_MUTED, font=font_body)
        body_y += 58

    # 8. Card Footer
    footer_y = H - card_margin_y - 65
    draw.line((content_x, footer_y - 20, W - card_margin_x - 80, footer_y - 20), fill=CARD_BORDER, width=1)
    draw.text((content_x, footer_y), "CONFIDENTIAL · PREPARED FOR EXECUTIVE REVIEW", fill=SLATE_GRAY, font=font_footer)
    draw.text((W - card_margin_x - 360, footer_y), "WWW.ELKINSREVENUE.COM", fill=ACCENT_BLUE, font=font_footer)

    img.save(output_path)

def generate_tts_elevenlabs(text: str, output_audio_path: str):
    """Generates clean, free neural voiceover locally via Edge-TTS (No API key needed)."""
    async def _run():
        communicate = edge_tts.Communicate(text, "en-US-GuyNeural")
        await communicate.save(output_audio_path)
    asyncio.run(_run())

def assemble_pitch_video(company_name: str, video_slides: list, output_filename: str) -> str:
    """Builds a ~60-second video combining static slides with synchronized TTS audio."""
    clips = []
    
    for i, slide in enumerate(video_slides):
        slide_img = f"slide_{i}.png"
        slide_audio = f"audio_{i}.mp3"
        
        create_slide_image(
            slide_index=i,
            title=slide["slide_title"],
            text=slide["voiceover"],
            output_path=slide_img,
            logo_path="G:\\My Drive\\Elkins Revenue Consulting\\logo.png"
        )
        generate_tts_elevenlabs(slide["voiceover"], slide_audio)
        
        audio_clip = AudioFileClip(slide_audio)
        img_clip = ImageClip(slide_img).with_duration(audio_clip.duration).with_audio(audio_clip)
        clips.append(img_clip)
        
    final_video = concatenate_videoclips(clips, method="compose")
    final_video.write_videofile(output_filename, fps=24, codec="libx264", audio_codec="aac", logger=None)
    
    for i in range(len(video_slides)):
        if os.path.exists(f"slide_{i}.png"): os.remove(f"slide_{i}.png")
        if os.path.exists(f"audio_{i}.mp3"): os.remove(f"audio_{i}.mp3")
        
    return output_filename
# ==============================================================================
# 4. EMAIL TRANSMISSION
# ==============================================================================
def send_prospect_email(to_email: str, subject: str, body: str, attachment_path: str):
    """Sends the outreach email with the mp4 video directly attached."""
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
# MAIN EXECUTION LOOP
# ==============================================================================
def main():
    print("\n--- B2B Prospecting & Custom Video Pipeline ---")
    category = input("Enter target business category (e.g., HVAC, Locksmith, Event Planner): ").strip()
    location = input("Enter target geographic region (e.g., Naples FL, Denver CO): ").strip()
    
    print(f"\n[1/5] Finding businesses for '{category}' in '{location}'...")
    leads = find_businesses(category, location, limit=1)
    
    if not leads:
        print("\n[TERMINATED] No leads were retrieved. Inspect the API messages above to resolve.")
        return
    
    records = []
    
   for lead in leads[:1]:
        name = lead["name"]
        website = lead["website"]
        print(f"\nProcessing: {name} ({website})")
        
        print("  -> Scraping website and social accounts...")
        footprint = scrape_site_footprint(website)
        
        print("  -> Performing digital audit & composing pitch via NRP endpoint...")
        audit = audit_and_compose(lead, footprint)
        
        clean_name = re.sub(r'[^a-zA-Z0-9]', '', name)
        video_file = f"{clean_name}_audit_brief.mp4"
        
        print("  -> Rendering custom 60-second video presentation...")
        assemble_pitch_video(name, audit["video_script"], video_file)
        
        email_recipient = footprint["email"]
        delivery_status = "Skipped (No Email)"
        
        if email_recipient != "Not Listed" and "@" in email_recipient:
            print(f"  -> Sending prospecting email to {email_recipient}...")
            send_prospect_email(email_recipient, audit["email_subject"], audit["email_body"], video_file)
            delivery_status = "Email Sent with Video"
        
        records.append({
            "Business Name": name,
            "Address": lead["address"],
            "Website": website,
            "Contact Email": email_recipient,
            "SEO Score": audit["scores"]["seo"],
            "Social Score": audit["scores"]["social_media"],
            "Speed Score": audit["scores"]["website_speed"],
            "Clarity Score": audit["scores"]["content_clarity"],
            "Core Weakness": audit["core_weakness"],
            "Proposed Solution": audit["solution"],
            "Email Subject": audit["email_subject"],
            "Email Status": delivery_status,
            "Video Asset": video_file
        })
        
    df = pd.DataFrame(records)
    df.to_csv(CONFIG["OUTPUT_CSV"], index=False)
    print(f"\n[SUCCESS] Execution complete. {len(records)} leads saved to '{CONFIG['OUTPUT_CSV']}'.")

if __name__ == "__main__":
    main()