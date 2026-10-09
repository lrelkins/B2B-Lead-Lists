import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# ==============================================================================
# 1. CANVAS CONFIGURATION & BRAND TOKENS (from allinone_enhanced_phase1.py)
# ==============================================================================
W, H = 2550, 3300  # 8.5" x 11" at 300 DPI
MX = 95            # Standard Scorecard Margin
USABLE_W = W - (2 * MX)

# Palette matching elkinsrevenue.com and allinone_enhanced_phase1.py
TEXT_MAIN    = (15, 23, 42)       # Slate Charcoal #0F172A
TEXT_BODY    = (51, 65, 85)       # Medium Dark Slate #334155
TEXT_MUTED   = (100, 116, 139)    # Cool Slate #64748B
C_BLUE       = (37, 99, 235)      # Electric Cobalt Accent #2563EB
C_BLUE_LIGHT = (239, 246, 255)    # Subtle Pill Fill #EFF6FF
C_GREEN      = (22, 163, 74)      # Accent Green #16A34A
BG_PAGE      = (248, 250, 252)    # Subtle Slate Canvas #F8FAFC
BG_CARD      = (255, 255, 255)    # Crisp White Container #FFFFFF
BORDER_LIGHT = (226, 232, 240)    # Card Border #E2E8F0
DIVIDER      = (203, 213, 225)    # Dividing Line #CBD5E1

# Vertical separation between modules set to 100 px
MODULE_GAP = 100

# ==============================================================================
# 2. UNIVERSAL FONT LOADER (from allinone_enhanced_phase1.py)
# ==============================================================================
def load_font(arg1, arg2=None, bold: bool = False):
    """
    Universal font loader supporting:
      - load_font(size, bold=True/False)
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

# Typography scale: +4 pt boost applied to all module content
FONTS = {
    "brand_main":   load_font(["arialbd.ttf", "segoeuib.ttf"], 72),
    "brand_sub":    load_font(["arialbd.ttf", "segoeuib.ttf"], 30),
    "doc_title":    load_font(["arialbd.ttf", "segoeuib.ttf"], 70),
    "doc_meta":     load_font(["arial.ttf", "segoeui.ttf"], 32),
    
    # Hero Banner
    "hero_head":    load_font(["arialbd.ttf", "segoeuib.ttf"], 48),  # Boosted
    "hero_sub":     load_font(["arialbd.ttf", "segoeuib.ttf"], 32),  # Boosted
    "hero_note":    load_font(["arial.ttf", "segoeui.ttf"], 28),     # Boosted

    # Modules (+4 pt increase)
    "card_title":   load_font(["arialbd.ttf", "segoeuib.ttf"], 38),  # was 34
    "badge_pill":   load_font(["arialbd.ttf", "segoeuib.ttf"], 28),  # was 24
    "item_title":   load_font(["arialbd.ttf", "segoeuib.ttf"], 32),  # was 28
    "item_desc":    load_font(["arial.ttf", "segoeui.ttf"], 29),     # was 25

    # Footer
    "footer_hook":  load_font(["arialbd.ttf", "segoeuib.ttf"], 38),
    "footer_btn":   load_font(["arialbd.ttf", "segoeuib.ttf"], 28),
    "footer_meta":  load_font(["arial.ttf", "segoeui.ttf"], 26),
}

# ==============================================================================
# 3. GRAPHIC RENDERING COMPONENTS
# ==============================================================================
def draw_header_zone(img, draw, right_title: str, subtitle_meta: str):
    """Renders Header Zone with automatic logo detection or programmatic wordmark."""
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

    # Right: Document Title & Meta Line
    t_bbox = draw.textbbox((0, 0), right_title, font=FONTS["doc_title"])
    hdr_t_w = t_bbox[2] - t_bbox[0]
    draw.text((W - MX - hdr_t_w, y), right_title, fill=TEXT_MAIN, font=FONTS["doc_title"])

    m_bbox = draw.textbbox((0, 0), subtitle_meta, font=FONTS["doc_meta"])
    prep_w = m_bbox[2] - m_bbox[0]
    draw.text((W - MX - prep_w, y + 82), subtitle_meta, fill=TEXT_MUTED, font=FONTS["doc_meta"])

    y += 138
    draw.line([(MX, y), (W - MX, y)], fill=BORDER_LIGHT, width=3)
    return y + MODULE_GAP  # 100 px separation

def draw_lead_banner(draw, y, headline: str, subhead: str, protocol_note: str):
    """Renders the executive summary card with increased padding for larger type."""
    banner_h = 185
    draw.rounded_rectangle([MX, y, MX + USABLE_W, y + banner_h], radius=18, fill=BG_CARD, outline=BORDER_LIGHT, width=2)
    draw.rounded_rectangle([MX, y, MX + 14, y + banner_h], radius=6, fill=C_BLUE)

    draw.text((MX + 42, y + 22), headline, fill=TEXT_MAIN, font=FONTS["hero_head"])
    draw.text((MX + 42, y + 82), subhead, fill=C_BLUE, font=FONTS["hero_sub"])
    draw.text((MX + 42, y + 128), protocol_note, fill=TEXT_MUTED, font=FONTS["hero_note"])

    return y + banner_h + MODULE_GAP  # 100 px separation

def draw_section_card(draw, y, card_h: int, title: str, badge_text: str, rows: list):
    """Draws a structured 2-column data card with +4pt boosted type and clean line height."""
    draw.rounded_rectangle([MX, y, MX + USABLE_W, y + card_h], radius=18, fill=BG_CARD, outline=BORDER_LIGHT, width=2)

    # Section title inside card
    draw.text((MX + 36, y + 24), title, fill=TEXT_MAIN, font=FONTS["card_title"])

    # Blue pill button on right
    p_bbox = draw.textbbox((0, 0), badge_text, font=FONTS["badge_pill"])
    pw = p_bbox[2] - p_bbox[0] + 36
    px = W - MX - pw - 32
    draw.rounded_rectangle([px, y + 20, px + pw, y + 64], radius=22, fill=C_BLUE_LIGHT, outline=C_BLUE, width=2)
    draw.text((px + 18, y + 26), badge_text, fill=C_BLUE, font=FONTS["badge_pill"])

    # Inner horizontal divider
    draw.line([(MX + 28, y + 78), (W - MX - 28, y + 78)], fill=BORDER_LIGHT, width=2)

    # 2-Column Content Layout
    col1_x = MX + 42
    col2_x = MX + 670
    row_y = y + 96

    for metric_title, metric_desc in rows:
        # Precision bullet
        draw.rounded_rectangle([col1_x, row_y + 10, col1_x + 14, row_y + 24], radius=3, fill=C_BLUE)
        draw.text((col1_x + 30, row_y), metric_title, fill=TEXT_MAIN, font=FONTS["item_title"])
        draw.text((col2_x, row_y + 2), metric_desc, fill=TEXT_BODY, font=FONTS["item_desc"])
        row_y += 56  # Expanded vertical step for larger fonts

    return y + card_h + MODULE_GAP  # 100 px separation

def draw_scorecard_footer(draw):
    """Renders the solid cobalt blue footer card."""
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
# 4. SHEET GENERATORS
# ==============================================================================
def render_sheet_first_party(out_path="Scorecard_Data_Authorized_1st_Party.pdf"):
    img = Image.new("RGB", (W, H), color=BG_PAGE)
    draw = ImageDraw.Draw(img)

    y = draw_header_zone(img, draw, "CLIENT REVENUE AUDIT", "Authorized 1st-Party Data Specification")
    y = draw_lead_banner(
        draw, y,
        headline="Unlock Your Exact Dollar Impact with 15 Minutes of Access",
        subhead="First-Party Metrics Unlocked After Client Grants View-Only Permissions",
        protocol_note="SECURITY PROTOCOL: View-Only Google Service Account & OAuth 2.0  |  No changes made to campaigns or billing"
    )

    # 1. Google Search Console
    gsc_metrics = [
        ("Organic Clicks (28d)", "Actual count of customers clicking to your site from Google search (not estimates)."),
        ("Search Impressions (28d)", "Exact frequency your business appeared in Google results for localized queries."),
        ("Click-Through Rate (CTR)", "Identifies whether search metadata entices active searchers to click through."),
        ("Average SERP Position", "Pinpoints ranking depth on primary service keywords; flags pages falling off Page 1."),
        ("Top Commercial Queries", "Actual customer query phrases typed immediately before reaching your site.")
    ]
    y = draw_section_card(draw, y, 395, "1. Google Search Console (GSC) · Organic Intent", "VIEWER / SERVICE ACCOUNT", gsc_metrics)

    # 2. Google Analytics 4
    ga4_metrics = [
        ("Sessions & Real Users", "Direct verified traffic volume filtering out internal visits and automated web bots."),
        ("Engagement Duration", "Reveals if prospects consume your service pages or abandon due to high friction."),
        ("Qualified Conversions", "Verified counts of form inquiries, consultation bookings, and contact clicks."),
        ("Drop-off Bottlenecks", "Pinpoints the exact landing page where ready-to-buy prospects leave without calling.")
    ]
    y = draw_section_card(draw, y, 340, "2. Google Analytics 4 (GA4) · Conversion Paths", "VIEWER ACCESS (PROPERTY ID)", ga4_metrics)

    # 3. Google Business Profile
    gbp_metrics = [
        ("Direct Phone Calls", "Total phone calls tapped directly from Google Map Pack cards on mobile devices."),
        ("Website Clicks from Maps", "High-intent local shoppers driving from your map pin directly to your website."),
        ("Direction Requests", "In-market customers requesting direct GPS navigation routes to your physical address."),
        ("Map Search Keywords", "Granular keyword queries triggering your Google Map pin in localized 3-packs.")
    ]
    y = draw_section_card(draw, y, 340, "3. Google Business Profile (GBP) · Local Search Capture", "OAUTH 2.0 PERFORMANCE API", gbp_metrics)

    # 4. Google Ads
    gads_metrics = [
        ("Actual Ad Spend", "Audits exact dollar waste across under-performing campaigns, ad groups, and keywords."),
        ("Real Cost-Per-Click (CPC)", "Actual bid cost paid per click versus regional competitor benchmark averages."),
        ("Cost-Per-Acquisition (CPA)", "Exact expenditure required to generate a paying customer inquiry via search ads."),
        ("Negative Keyword Bleed", "Flags budget spent on unqualified, low-intent, or non-commercial search matches.")
    ]
    y = draw_section_card(draw, y, 340, "4. Google Ads (PPC) · Media Efficiency & Waste Elimination", "OAUTH 2.0 / 10-DIGIT ID", gads_metrics)

    draw_scorecard_footer(draw)
    img.save(out_path, "PDF", resolution=300.0)
    print(f"Generated: {out_path}")

def render_sheet_third_party(out_path="Scorecard_Data_Paid_3rd_Party.pdf"):
    img = Image.new("RGB", (W, H), color=BG_PAGE)
    draw = ImageDraw.Draw(img)

    y = draw_header_zone(img, draw, "COMPETITIVE BENCHMARK", "Paid 3rd-Party Intelligence Layer")
    y = draw_lead_banner(
        draw, y,
        headline="Market & Competitor Intelligence via Enterprise Platforms",
        subhead="Data Analyzed via Semrush, Ahrefs, SpyFu & BuiltWith Subscriptions",
        protocol_note="DEPLOYMENT: Cold Discovery & Head-to-Head Rival Audits  |  Requires Zero Client Access or Permission"
    )

    # 1. Semrush / Ahrefs
    seo_metrics = [
        ("Domain Authority (DA/DR)", "Algorithmic trust score (0–100) determining baseline ability to outrank local rivals."),
        ("Indexed Keyword Footprint", "Total volume of search terms where you or your competitors currently rank on Google."),
        ("Keyword Gap Analysis", "High-volume buyer keywords where rivals hold Page 1 rankings while you are invisible."),
        ("Backlink Trust Architecture", "Total referring domain count and toxic link footprint suppressing organic rankings.")
    ]
    y = draw_section_card(draw, y, 340, "1. Semrush & Ahrefs · Organic Search Footprint", "ENTERPRISE CRAWLER FEEDS", seo_metrics)

    # 2. SpyFu / Paid Ad Intelligence
    ad_metrics = [
        ("Modeled Monthly Ad Spend", "Estimated monthly Google Ads budget deployed by leading regional competitors."),
        ("Bidded Competitor Keywords", "Specific high-intent keywords competitors buy to divert customer phone calls."),
        ("Ad Copy & Angle Archive", "Historical record of competitor headlines, promotional discounts, and CTA hooks."),
        ("Paid Landing Page Targets", "The specific conversion funnels and destinations competitors route paid traffic into.")
    ]
    y = draw_section_card(draw, y, 340, "2. SpyFu & Paid Research · Competitor PPC Dissection", "OBSERVED SEARCH CAMPAIGNS", ad_metrics)

    # 3. BuiltWith / Wappalyzer
    tech_metrics = [
        ("Underlying CMS Platform", "Identifies if the site runs on WordPress, Webflow, Squarespace, Wix, or custom code."),
        ("CRM & Dispatch Detection", "Detects operational software (ServiceTitan, Housecall Pro, Jobber, GoHighLevel)."),
        ("Active Retargeting Pixels", "Validates presence or absence of Meta Pixel, Google Tag Manager, or LinkedIn Insight."),
        ("Lead Capture Widgets", "Surfaces installed chat widgets (Podium, Intercom) and booking calendar engines.")
    ]
    y = draw_section_card(draw, y, 340, "3. BuiltWith & Wappalyzer · Tech Stack & Pixel Audit", "CODE & DOM PARSER API", tech_metrics)

    # 4. Local Citations
    citation_metrics = [
        ("NAP Consistency Rating", "Evaluates Name, Address, Phone uniformity across Yelp, Apple Maps, Bing, and BBB."),
        ("Duplicate Map Pin Flags", "Identifies rogue or conflicting directory pins triggering Google Map Pack ranking penalties."),
        ("Competitor Citation Gap", "Directories where rivals hold active listings but the business is unlisted.")
    ]
    y = draw_section_card(draw, y, 290, "4. BrightLocal / Whitespark · Local Citation Index", "REGIONAL DIRECTORY AUDIT", citation_metrics)

    draw_scorecard_footer(draw)
    img.save(out_path, "PDF", resolution=300.0)
    print(f"Generated: {out_path}")

if __name__ == "__main__":
    render_sheet_first_party()
    render_sheet_third_party()