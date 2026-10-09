import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# ==============================================================================
# 1. CANVAS CONFIGURATION & BRAND TOKENS (Matching allinone_enhanced_phase1.py)
# ==============================================================================
W, H = 2550, 3300  # 8.5" x 11" at 300 DPI
MX = 95            # Scorecard Margin
USABLE_W = W - (2 * MX)

# Brand Color Palette
TEXT_MAIN    = (15, 23, 42)       # Slate Charcoal #0F172A
TEXT_BODY    = (51, 65, 85)       # Medium Dark Slate #334155
TEXT_MUTED   = (100, 116, 139)    # Cool Slate #64748B
C_BLUE       = (37, 99, 235)      # Electric Cobalt Accent #2563EB
C_BLUE_LIGHT = (239, 246, 255)    # Subtle Pill Fill #EFF6FF
C_GREEN      = (22, 163, 74)      # Accent Green #16A34A
BG_PAGE      = (248, 250, 252)    # Canvas #F8FAFC
BG_CARD      = (255, 255, 255)    # White Card #FFFFFF
BORDER_LIGHT = (226, 232, 240)    # Card Border #E2E8F0

# guarantees all 5 modules and footer fit within 3300 px
MODULE_GAP = 70

# ==============================================================================
# 2. UNIVERSAL FONT LOADER (+4 pt Scale)
# ==============================================================================
def load_font(arg1, arg2=None, bold: bool = False):
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

FONTS = {
    "brand_main":   load_font(["arialbd.ttf", "segoeuib.ttf"], 72),
    "brand_sub":    load_font(["arialbd.ttf", "segoeuib.ttf"], 30),
    "doc_title":    load_font(["arialbd.ttf", "segoeuib.ttf"], 70),
    "doc_meta":     load_font(["arial.ttf", "segoeui.ttf"], 32),
    "hero_head":    load_font(["arialbd.ttf", "segoeuib.ttf"], 44),
    "hero_sub":     load_font(["arialbd.ttf", "segoeuib.ttf"], 30),
    "hero_note":    load_font(["arial.ttf", "segoeui.ttf"], 26),
    
    # Module Typography
    "card_title":   load_font(["arialbd.ttf", "segoeuib.ttf"], 36),
    "badge_pill":   load_font(["arialbd.ttf", "segoeuib.ttf"], 26),
    "mod_summary":  load_font(["arial.ttf", "segoeui.ttf"], 26),
    "item_title":   load_font(["arialbd.ttf", "segoeuib.ttf"], 30),
    "item_desc":    load_font(["arial.ttf", "segoeui.ttf"], 27),
    
    # Footer
    "footer_hook":  load_font(["arialbd.ttf", "segoeuib.ttf"], 38),
    "footer_btn":   load_font(["arialbd.ttf", "segoeuib.ttf"], 28),
    "footer_meta":  load_font(["arial.ttf", "segoeui.ttf"], 26),
}

# ==============================================================================
# 3. GRAPHIC RENDERING COMPONENTS
# ==============================================================================
def draw_header_zone(img, draw, right_title: str, subtitle_meta: str):
    y = 75
    logo_file_candidates = [
        Path(r"G:\My Drive\Elkins Revenue Consulting\logo.png"),
        Path(__file__).resolve().parent / "logo.png",
        Path.cwd() / "logo.png"
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
        logo_h = 100
        logo_w = int(logo_h * aspect)
        resized_logo = loaded_logo.resize((logo_w, logo_h), Image.Resampling.LANCZOS)
        img.paste(resized_logo, (MX, y), mask=resized_logo.split()[3])
    else:
        cur_x = MX
        draw.text((cur_x, y), "ELKINS ", fill=TEXT_MAIN, font=FONTS["brand_main"])
        cur_x += draw.textbbox((0, 0), "ELKINS ", font=FONTS["brand_main"])[2]
        draw.text((cur_x, y), "& ", fill=C_BLUE, font=FONTS["brand_main"])
        cur_x += draw.textbbox((0, 0), "& ", font=FONTS["brand_main"])[2]
        draw.text((cur_x, y), "CO.", fill=TEXT_MAIN, font=FONTS["brand_main"])
        draw.text((MX + 2, y + 80), "REVENUE SOLUTIONS", fill=C_BLUE, font=FONTS["brand_sub"])

    t_bbox = draw.textbbox((0, 0), right_title, font=FONTS["doc_title"])
    hdr_t_w = t_bbox[2] - t_bbox[0]
    draw.text((W - MX - hdr_t_w, y), right_title, fill=TEXT_MAIN, font=FONTS["doc_title"])

    m_bbox = draw.textbbox((0, 0), subtitle_meta, font=FONTS["doc_meta"])
    prep_w = m_bbox[2] - m_bbox[0]
    draw.text((W - MX - prep_w, y + 82), subtitle_meta, fill=TEXT_MUTED, font=FONTS["doc_meta"])

    y += 138
    draw.line([(MX, y), (W - MX, y)], fill=BORDER_LIGHT, width=3)
    return y + MODULE_GAP

def draw_lead_banner(draw, y, headline: str, subhead: str, protocol_note: str):
    banner_h = 165
    draw.rounded_rectangle([MX, y, MX + USABLE_W, y + banner_h], radius=18, fill=BG_CARD, outline=BORDER_LIGHT, width=2)
    draw.rounded_rectangle([MX, y, MX + 14, y + banner_h], radius=6, fill=C_BLUE)

    draw.text((MX + 42, y + 20), headline, fill=TEXT_MAIN, font=FONTS["hero_head"])
    draw.text((MX + 42, y + 74), subhead, fill=C_BLUE, font=FONTS["hero_sub"])
    draw.text((MX + 42, y + 116), protocol_note, fill=TEXT_MUTED, font=FONTS["hero_note"])
    return y + banner_h + MODULE_GAP

def draw_section_card(draw, y, card_h: int, title: str, badge_text: str, summary_text: str, rows: list, col2_offset: int = 740):
    draw.rounded_rectangle([MX, y, MX + USABLE_W, y + card_h], radius=18, fill=BG_CARD, outline=BORDER_LIGHT, width=2)

    # 1. Section Title
    draw.text((MX + 36, y + 20), title, fill=TEXT_MAIN, font=FONTS["card_title"])

    # 2. Pill Badge
    p_bbox = draw.textbbox((0, 0), badge_text, font=FONTS["badge_pill"])
    pw = p_bbox[2] - p_bbox[0] + 36
    px = W - MX - pw - 32
    draw.rounded_rectangle([px, y + 16, px + pw, y + 58], radius=20, fill=C_BLUE_LIGHT, outline=C_BLUE, width=2)
    draw.text((px + 18, y + 22), badge_text, fill=C_BLUE, font=FONTS["badge_pill"])

    # Inner horizontal divider
    draw.line([(MX + 28, y + 70), (W - MX - 28, y + 70)], fill=BORDER_LIGHT, width=2)

    # 3. Plain-English Summary
    summary_y = y + 84
    draw.text((MX + 42, summary_y), summary_text, fill=TEXT_BODY, font=FONTS["mod_summary"])
    
    # 50px buffer below summary
    sum_bbox = draw.textbbox((MX + 42, summary_y), summary_text, font=FONTS["mod_summary"])
    summary_actual_h = sum_bbox[3] - sum_bbox[1]
    row_y = summary_y + summary_actual_h + 35

    col1_x = MX + 42
    col2_x = MX + col2_offset

    for metric_title, metric_desc in rows:
        draw.rounded_rectangle([col1_x, row_y + 8, col1_x + 12, row_y + 20], radius=3, fill=C_BLUE)
        draw.text((col1_x + 26, row_y), metric_title, fill=TEXT_MAIN, font=FONTS["item_title"])
        draw.text((col2_x, row_y + 2), metric_desc, fill=TEXT_BODY, font=FONTS["item_desc"])
        row_y += 46

    return y + card_h + MODULE_GAP

def draw_scorecard_footer(draw):
    foot_h = 240
    fy = H - MX - foot_h
    draw.rounded_rectangle([MX, fy, MX + USABLE_W, fy + foot_h], radius=18, fill=C_BLUE)

    hook_text = "Ready to see what each missed call is worth?"
    hb = draw.textbbox((0, 0), hook_text, font=FONTS["footer_hook"])
    hw = hb[2] - hb[0]
    draw.text(((W - hw) // 2, fy + 32), hook_text, fill=(255, 255, 255), font=FONTS["footer_hook"])

    btn_text = "Book your free 15-minute walkthrough"
    bb = draw.textbbox((0, 0), btn_text, font=FONTS["footer_btn"])
    bw = bb[2] - bb[0] + 60
    bh = 58
    bx = (W - bw) // 2
    by = fy + 94
    draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=29, fill=(255, 255, 255))
    draw.text((bx + 30, by + 12), btn_text, fill=C_BLUE, font=FONTS["footer_btn"])

    contact_text = "www.elkinsrevenue.com   |   917-327-0636   |   info@elkinsrevenue.com"
    cb = draw.textbbox((0, 0), contact_text, font=FONTS["footer_meta"])
    cw = cb[2] - cb[0]
    draw.text(((W - cw) // 2, fy + 176), contact_text, fill=(255, 255, 255), font=FONTS["footer_meta"])

# ==============================================================================
# 4. METHODOLOGY & SCORING LOGIC GENERATOR
# ==============================================================================
def render_sheet_scoring_methodology(out_path="Scorecard_Grading_Methodology.pdf"):
    img = Image.new("RGB", (W, H), color=BG_PAGE)
    draw = ImageDraw.Draw(img)

    y = draw_header_zone(img, draw, "AUDIT METHODOLOGY", "Scoring Algorithms & Analytical Foundations")
    y = draw_lead_banner(
        draw, y,
        headline="Digital Marketing Effectiveness Is Measurable",
        subhead="How Scores, Formulas, and Diagnostic Grades Are Determined",
        protocol_note="A Proprietary Elkins & Co. System"
    )

    # MODULE 1
    m1_summary = "This grade acts like an executive report card for your digital storefront, measuring how easily visitors can turn into paying customers.\nIt matters because an attractive website is useless if slow load times or broken contact links cause prospective buyers to leave without calling."
    m1_rows = [
        ("Weighted 5-Factor Matrix", "Overall Score = 0.30(Conversion) + 0.25(SEO) + 0.20(Speed) + 0.15(Reputation) + 0.10(Marketing)"),
        ("Active Leakage Penalties", "Deducts 10 pts if page latency > 3.0s without click-to-call; deducts 5 pts for missing SSL or viewport."),
        ("Grade Tiering Rubric", "A (>=92), B+ (85-91), B (78-84), B- (70-77), C+ (60-69), C (50-59), D (<50)."),
        ("Core Economic Logic", "Prioritizes immediate customer capture and trust proof over superficial vanity traffic metrics.")
    ]
    y = draw_section_card(draw, y, 365, "1. Overall Grade", "WEIGHTED MULTI-FACTOR ENGINE", m1_summary, m1_rows)

    # MODULE 2
    m2_summary = "We audit your actual website code and public Google listings to see exactly what a customer experiences in real time.\nThis is vital because hidden technical flaws—like missing phone tags or unlisted addresses—silently block ready-to-buy customers from reaching you."
    m2_rows = [
        ("Technical Scraping", "Inspects <form> tags, tel: click-to-call links, JSON-LD Schema, viewport tags, H1/H2 hierarchy, and alt tags."),
        ("Marketing Stack Detection", "Verifies presence of Google Tag Manager (GTM), Google Analytics 4 (GA4), and Meta Pixel tracking containers."),
        ("Interactive Widgets & CMS", "Scans iframe/DOM footprints for scheduling embeds (Calendly/Acuity) and live chat widgets (Podium/Tidio)."),
        ("Google Places Data", "Captures verified Google star ratings, total review counts, verified NAP address, and category taxonomy.")
    ]
    y = draw_section_card(draw, y, 365, "2. What Signals We Collect", "PUBLIC DISCOVERY", m2_summary, m2_rows)

    # MODULE 3
    m3_summary = "These four scores represent the primary decision points where a local customer chooses either you or your closest competitor. Improving these\nensures your business is easy to find on Google Maps, loads instantly on mobile, and allows callers to reach you with a single tap or click."
    m3_rows = [
        ("Website Loading Speed", "Measures homepage latency in seconds; slow mobile rendering causes immediate customer abandonment."),
        ("Ease of Booking & Calling", "Evaluates mobile 1-tap dial buttons, direct inquiry forms, and booking calendar embed availability."),
        ("Lead Capture & Tracking", "Scored from active marketing pixels, GTM tags, and lead capture architectures capturing visitor intent."),
        ("Local Search & Maps", "Synthesizes star ratings, review velocity, and LocalBusiness schema required to rank in the Local 3-Pack.")
    ]
    y = draw_section_card(draw, y, 365, "3. Priority Scores · Why These 4", "URGENCY PILLARS", m3_summary, m3_rows)

    # MODULE 4
    m4_summary = "Public scans only evaluate external website symptoms, not your actual credit balances, marketing budget waste, or true customer volume.\nGranting temporary view-only access lets us open the hood to prove exactly how many calls were missed and how many ad dollars were wasted."
    m4_rows = [
        ("Public Audit Limitations", "Public scraping detects code presence, but cannot quantify lost dollars, ad waste, or funnel bounce points."),
        ("Google Search Console", "Requires View-level access to reveal exact customer search phrases, total impressions, and organic SERP rank."),
        ("Google Analytics 4 & Ads", "Unlocks verified lead conversion funnels, visitor drop-off pages, true CPA, and negative keyword ad spend waste."),
        ("Google Business Profile", "OAuth authorization unlocks actual phone call clicks, direction routes, and monthly Map search queries.")
    ]
    y = draw_section_card(draw, y, 365, "4. Permission Access Gateway · Unlocking Your Revenue Opportunity", "API ACCESS", m4_summary, m4_rows)

    # MODULE 5
    m5_summary = "We use strict mathematical formulas rather than subjective opinions to benchmark your performance against local market rivals.\nThis gives you an honest, transparent breakdown of where your setup is strong and the exact quick fixes that will generate more customer inquiries."
    m5_rows = [
        ("Speed Formula", "max(10, min(100, 100 - (load_speed_sec * 18)))  -> Directly maps response latency into a 10-100 scale."),
        ("Conversion", "30(has_click_to_call) + 25(has_lead_form) + 25(has_booking/chat) + 20(is_mobile_responsive)."),
        ("Reputation", "15(has_ssl) + min(45, rating * 9) + min(40, sqrt(reviews) * 1.5)  -> Smooth curve rewards review depth."),
        ("Marketing Stack", "40(has_ga4) + 30(has_gtm) + 20(has_meta_pixel) + 10(social_links_present).")
    ]
    y = draw_section_card(draw, y, 365, "5. Mathematical Modeling Foundations", "EXACT UNBIASED ALGORITHMS", m5_summary, m5_rows)

    draw_scorecard_footer(draw)
    img.save(out_path, "PDF", resolution=300.0)
    print(f"Generated: {out_path}")

if __name__ == "__main__":
    render_sheet_scoring_methodology()