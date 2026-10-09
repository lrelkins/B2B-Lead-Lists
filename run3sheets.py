import os
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# ==============================================================================
# 1. CANVAS CONFIGURATION & BRAND TOKENS
# ==============================================================================
W, H = 2550, 3300  # 8.5" x 11" at 300 DPI
MX = 95            # Standard Scorecard Margin
USABLE_W = W - (2 * MX)

# Brand Palette matching elkinsrevenue.com
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

# Vertical spacing parameters
MODULE_GAP_4MOD = 100  # Gap for 4-module sheets (Sheets 1 & 2)
MODULE_GAP_5MOD = 70   # Gap for 5-module methodology sheet (Sheet 3)

# ==============================================================================
# 2. UNIVERSAL FONT LOADER
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

FONTS = {
    "brand_main":   load_font(["arialbd.ttf", "segoeuib.ttf"], 72),
    "brand_sub":    load_font(["arialbd.ttf", "segoeuib.ttf"], 30),
    "doc_title":    load_font(["arialbd.ttf", "segoeuib.ttf"], 70),
    "doc_meta":     load_font(["arial.ttf", "segoeui.ttf"], 32),
    
    # Hero Banner
    "hero_head":    load_font(["arialbd.ttf", "segoeuib.ttf"], 48),
    "hero_sub":     load_font(["arialbd.ttf", "segoeuib.ttf"], 32),
    "hero_note":    load_font(["arial.ttf", "segoeui.ttf"], 28),

    # Module Cards (+4 pt Boosted Scale)
    "card_title":   load_font(["arialbd.ttf", "segoeuib.ttf"], 38),
    "badge_pill":   load_font(["arialbd.ttf", "segoeuib.ttf"], 28),
    "mod_summary":  load_font(["arial.ttf", "segoeui.ttf"], 26),
    "item_title":   load_font(["arialbd.ttf", "segoeuib.ttf"], 32),
    "item_desc":    load_font(["arial.ttf", "segoeui.ttf"], 29),

    # Footer
    "footer_hook":  load_font(["arialbd.ttf", "segoeuib.ttf"], 38),
    "footer_btn":   load_font(["arialbd.ttf", "segoeuib.ttf"], 28),
    "footer_meta":  load_font(["arial.ttf", "segoeui.ttf"], 26),
}

# ==============================================================================
# 3. GRAPHIC RENDERING COMPONENTS
# ==============================================================================
def draw_header_zone(img, draw, right_title: str, subtitle_meta: str, gap: int = 100):
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

    # Right-aligned Document Title & Meta Line
    t_bbox = draw.textbbox((0, 0), right_title, font=FONTS["doc_title"])
    hdr_t_w = t_bbox[2] - t_bbox[0]
    draw.text((W - MX - hdr_t_w, y), right_title, fill=TEXT_MAIN, font=FONTS["doc_title"])

    m_bbox = draw.textbbox((0, 0), subtitle_meta, font=FONTS["doc_meta"])
    prep_w = m_bbox[2] - m_bbox[0]
    draw.text((W - MX - prep_w, y + 82), subtitle_meta, fill=TEXT_MUTED, font=FONTS["doc_meta"])

    y += 138
    draw.line([(MX, y), (W - MX, y)], fill=BORDER_LIGHT, width=3)
    return y + gap

def draw_lead_banner(draw, y, headline: str, subhead: str, protocol_note: str, banner_h: int = 185, gap: int = 100):
    """Renders executive summary card with increased padding."""
    draw.rounded_rectangle([MX, y, MX + USABLE_W, y + banner_h], radius=18, fill=BG_CARD, outline=BORDER_LIGHT, width=2)
    draw.rounded_rectangle([MX, y, MX + 14, y + banner_h], radius=6, fill=C_BLUE)

    draw.text((MX + 42, y + 20), headline, fill=TEXT_MAIN, font=FONTS["hero_head"])
    draw.text((MX + 42, y + 78), subhead, fill=C_BLUE, font=FONTS["hero_sub"])
    draw.text((MX + 42, y + 124), protocol_note, fill=TEXT_MUTED, font=FONTS["hero_note"])

    return y + banner_h + gap

def draw_section_card(draw, y, card_h: int, title: str, badge_text: str, summary_text: str, rows: list, gap: int = 100, col2_offset: int = 670, row_spacing: int = 56):
    """Draws a structured 2-column data card with a plain-English 2-sentence summary and +4pt boosted item listings."""
    draw.rounded_rectangle([MX, y, MX + USABLE_W, y + card_h], radius=18, fill=BG_CARD, outline=BORDER_LIGHT, width=2)

    # 1. Section Title
    draw.text((MX + 36, y + 22), title, fill=TEXT_MAIN, font=FONTS["card_title"])

    # 2. Pill Badge
    p_bbox = draw.textbbox((0, 0), badge_text, font=FONTS["badge_pill"])
    pw = p_bbox[2] - p_bbox[0] + 36
    px = W - MX - pw - 32
    draw.rounded_rectangle([px, y + 18, px + pw, y + 62], radius=22, fill=C_BLUE_LIGHT, outline=C_BLUE, width=2)
    draw.text((px + 18, y + 24), badge_text, fill=C_BLUE, font=FONTS["badge_pill"])

    # Divider below title row
    draw.line([(MX + 28, y + 76), (W - MX - 28, y + 76)], fill=BORDER_LIGHT, width=2)

    # 3. Plain-English Summary (2 Sentences)
    summary_y = y + 92
    draw.text((MX + 42, summary_y), summary_text, fill=TEXT_BODY, font=FONTS["mod_summary"])

    # Compute bounding box and apply 50px buffer before bullet rows start
    sum_bbox = draw.textbbox((MX + 42, summary_y), summary_text, font=FONTS["mod_summary"])
    summary_actual_h = sum_bbox[3] - sum_bbox[1]
    row_y = summary_y + summary_actual_h + 50

    # 4. Two-Column Metric Rows
    col1_x = MX + 42
    col2_x = MX + col2_offset

    for metric_title, metric_desc in rows:
        draw.rounded_rectangle([col1_x, row_y + 8, col1_x + 12, row_y + 22], radius=3, fill=C_BLUE)
        draw.text((col1_x + 28, row_y), metric_title, fill=TEXT_MAIN, font=FONTS["item_title"])
        draw.text((col2_x, row_y + 2), metric_desc, fill=TEXT_BODY, font=FONTS["item_desc"])
        row_y += row_spacing

    return y + card_h + gap

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
    """Sheet 1: Authorized 1st-Party Client Data Specification."""
    img = Image.new("RGB", (W, H), color=BG_PAGE)
    draw = ImageDraw.Draw(img)

    y = draw_header_zone(img, draw, "CLIENT AUDIT", "Authorized 1st-Party Data Specification", gap=MODULE_GAP_4MOD)
    y = draw_lead_banner(
        draw, y,
        headline="We Unlock Your Exact Dollar Impact",
        subhead="Your Metrics Unlocked After View-Only Permissions",
        protocol_note="SECURITY PROTOCOL: View-Only | No changes made to campaigns or billing",
        banner_h=185,
        gap=MODULE_GAP_4MOD
    )

    # 1. Google Search Console
    m1_summary = (
        "This tool shows the exact words customers type into Google when looking for your services.\n"
        "It matters because ranking on page two means high-intent local buyers are calling your competitors instead."
    )
    gsc_metrics = [
        ("Organic Clicks", "Actual count of customers clicking to your site from Google search (not estimates)."),
        ("Search Impressions", "Exact frequency your business appeared in Google results for localized queries."),
        ("Click-Through Rate", "Identifies whether search metadata entices active searchers to click through."),
        ("Average Search Position", "Pinpoints ranking depth on primary service keywords; flags pages falling off Page 1."),
        ("Top Commercial Queries", "Actual customer query phrases typed immediately before reaching your site.")
    ]
    y = draw_section_card(draw, y, 460, "1. Google Search · Organic Intent", "WHERE YOU APPEAR", m1_summary, gsc_metrics, gap=MODULE_GAP_4MOD)

    # 2. Google Analytics 4
    m2_summary = (
        "This tracks what real visitors do after landing on your website and where they drop off.\n"
        "It matters because sending traffic to pages with slow loading or broken buttons wastes your marketing dollars."
    )
    ga4_metrics = [
        ("Sessions & Real Users", "Direct verified traffic volume filtering out internal visits and automated web bots."),
        ("Engagement Duration", "Reveals if prospects consume your service pages or abandon due to high friction."),
        ("Qualified Conversions", "Verified counts of form inquiries, consultation bookings, and contact clicks."),
        ("Drop-off Bottlenecks", "Pinpoints the exact landing page where ready-to-buy prospects leave without calling.")
    ]
    y = draw_section_card(draw, y, 410, "2. Google Analytics", "VISITOR PATHWAYS", m2_summary, ga4_metrics, gap=MODULE_GAP_4MOD)

    # 3. Google Business Profile
    m3_summary = (
        "This reveals how many nearby customers find your business on Google Maps and tap to call.\n"
        "It matters because local map searches generate your most urgent, high-ticket inbound customer leads."
    )
    gbp_metrics = [
        ("Direct Phone Calls", "Total phone calls tapped directly from Google Map Pack cards on mobile devices."),
        ("Website Clicks from Maps", "High-intent local shoppers driving from your map pin directly to your website."),
        ("Direction Requests", "In-market customers requesting direct GPS navigation routes to your physical address."),
        ("Map Search Keywords", "Granular keyword queries triggering your Google Map pin in localized 3-packs.")
    ]
    y = draw_section_card(draw, y, 410, "3. Google Business Profile", "LOCAL SEARCH CAPTURE", m3_summary, gbp_metrics, gap=MODULE_GAP_4MOD)

    # 4. Google Ads
    m4_summary = (
        "This inspects your paid search campaigns to uncover exactly how much budget produces paying customers.\n"
        "It matters because poorly targeted ad keywords silently burn cash on clicks from people who will never buy."
    )
    gads_metrics = [
        ("Actual Ad Spend", "Audits exact dollar waste across under-performing campaigns, ad groups, and keywords."),
        ("Real Cost-Per-Click (CPC)", "Actual bid cost paid per click versus regional competitor benchmark averages."),
        ("Cost-Per-Acquisition (CPA)", "Exact expenditure required to generate a paying customer inquiry via search ads."),
        ("Negative Keyword Bleed", "Flags budget spent on unqualified, low-intent, or non-commercial search matches.")
    ]
    y = draw_section_card(draw, y, 410, "4. Google Ads", "MEDIA EFFICIENCY", m4_summary, gads_metrics, gap=MODULE_GAP_4MOD)

    draw_scorecard_footer(draw)
    img.save(out_path, "PDF", resolution=300.0)
    print(f"  -> Generated: {out_path}")

def render_sheet_third_party(out_path="Scorecard_Data_Paid_3rd_Party.pdf"):
    """Sheet 2: 3rd-Party Paid Intelligence Layer."""
    img = Image.new("RGB", (W, H), color=BG_PAGE)
    draw = ImageDraw.Draw(img)

    y = draw_header_zone(img, draw, "COMPETITIVE BENCHMARKING", "3rd-Party Intelligence Layer", gap=MODULE_GAP_4MOD)
    y = draw_lead_banner(
        draw, y,
        headline="Market & Competitor Intelligence",
        subhead="Cold Discovery & Head-to-Head Rival Audits",
        protocol_note="Requires Zero Client Access or Permission",
        banner_h=185,
        gap=MODULE_GAP_4MOD
    )

    # 1. Semrush / Ahrefs
    m1_summary = (
        "We scan the search engine visibility of your competitors to see where they currently outrank you.\n"
        "It matters because knowing their winning keywords shows us exactly how to redirect those buyers to your business."
    )
    seo_metrics = [
        ("Domain Authority", "Algorithmic trust score (0–100) determining baseline ability to outrank local rivals."),
        ("Indexed Keyword", "Total volume of search terms where you or your competitors currently rank on Google."),
        ("Keyword Gap Analysis", "High-volume buyer keywords where rivals hold Page 1 rankings while you are invisible."),
        ("Backlink Trust", "Total referring domain count and toxic link footprint suppressing organic rankings.")
    ]
    y = draw_section_card(draw, y, 410, "1. Organic Search Footprint", "ENTERPRISE CRAWLER FEEDS", m1_summary, seo_metrics, gap=MODULE_GAP_4MOD)

    # 2. SpyFu / Paid Ad Intelligence
    m2_summary = (
        "We reverse-engineer the paid Google ads your competitors are running and estimate their monthly budget.\n"
        "It matters because this exposes their sales offers and allows you to capture customer calls at a lower cost."
    )
    ad_metrics = [
        ("Modeled Monthly Ad Spend", "Estimated monthly Google Ads budget deployed by leading regional competitors."),
        ("Bidded Competitor Keywords", "Specific high-intent keywords competitors buy to divert customer phone calls."),
        ("Ad Copy & Angle Archive", "Historical record of competitor headlines, promotional discounts, and CTA hooks."),
        ("Paid Landing Page Targets", "The specific conversion funnels and destinations competitors route paid traffic into.")
    ]
    y = draw_section_card(draw, y, 410, "2. Competitor PPC Dissection", "OBSERVED SEARCH CAMPAIGNS", m2_summary, ad_metrics, gap=MODULE_GAP_4MOD)

    # 3. BuiltWith / Wappalyzer
    m3_summary = (
        "We inspect the software, booking tools, and follow-up tracking tags installed on competitor sites.\n"
        "It matters because businesses with automated lead booking respond faster and win more clients every day."
    )
    tech_metrics = [
        ("Underlying CMS Platform", "Identifies if the site runs on WordPress, Webflow, Squarespace, Wix, or custom code."),
        ("CRM & Dispatch Detection", "Detects operational software (ServiceTitan, Housecall Pro, Jobber, GoHighLevel)."),
        ("Active Retargeting Pixels", "Validates presence or absence of Meta Pixel, Google Tag Manager, or LinkedIn Insight."),
        ("Lead Capture Widgets", "Surfaces installed chat widgets (Podium, Intercom) and booking calendar engines.")
    ]
    y = draw_section_card(draw, y, 410, "3. Tech Stack & Pixel Audit", "TECHNICAL BACKEND", m3_summary, tech_metrics, gap=MODULE_GAP_4MOD)

    # 4. Local Citations
    m4_summary = (
        "We check that your company name, phone number, and address are listed accurately across all online directories.\n"
        "It matters because conflicting listings confuse customers and cause Google Maps to demote your ranking."
    )
    citation_metrics = [
        ("Contact Consistency Rating", "Evaluates Name, Address, Phone uniformity across Yelp, Apple Maps, Bing, and BBB."),
        ("Map Pin Flags", "Identifies rogue or conflicting directory pins triggering Google Map Pack ranking penalties."),
        ("Competitor Citation Gap", "Directories where rivals hold active listings but the business is unlisted.")
    ]
    y = draw_section_card(draw, y, 360, "4. Local Citation Index", "REGIONAL DIRECTORY AUDIT", m4_summary, citation_metrics, gap=MODULE_GAP_4MOD)

    draw_scorecard_footer(draw)
    img.save(out_path, "PDF", resolution=300.0)
    print(f"  -> Generated: {out_path}")

def render_sheet_scoring_methodology(out_path="Scorecard_Grading_Methodology.pdf"):
    """Sheet 3: Scoring Algorithms & Analytical Foundations."""
    img = Image.new("RGB", (W, H), color=BG_PAGE)
    draw = ImageDraw.Draw(img)

    y = draw_header_zone(img, draw, "AUDIT METHODOLOGY", "Scoring Algorithms & Analytical Foundations", gap=MODULE_GAP_5MOD)
    y = draw_lead_banner(
        draw, y,
        headline="Digital Marketing Effectiveness Is Measurable",
        subhead="How Scores, Formulas, and Diagnostic Grades Are Determined",
        protocol_note="A Proprietary Elkins & Co. System",
        banner_h=165,
        gap=MODULE_GAP_5MOD
    )

    # 1. Overall Grade
    m1_summary = (
        "This grade acts like an executive report card for your digital storefront, measuring how easily visitors can turn into paying customers.[cite: 2]\n"
        "It matters because an attractive website is useless if slow load times or broken contact links cause prospective buyers to leave without calling.[cite: 2]"
    )
    m1_rows = [
        ("Weighted 5-Factor Matrix", "Overall Score = 0.30(Conversion) + 0.25(SEO) + 0.20(Speed) + 0.15(Reputation) + 0.10(Marketing)"),
        ("Active Leakage Penalties", "Deducts 10 pts if page latency > 3.0s without click-to-call; deducts 5 pts for missing SSL or viewport."),
        ("Grade Tiering Rubric", "A (>=92), B+ (85-91), B (78-84), B- (70-77), C+ (60-69), C (50-59), D (<50)."),
        ("Core Economic Logic", "Prioritizes immediate customer capture and trust proof over superficial vanity traffic metrics.")
    ]
    y = draw_section_card(draw, y, 365, "1. Overall Grade", "WEIGHTED MULTI-FACTOR ENGINE", m1_summary, m1_rows, gap=MODULE_GAP_5MOD, col2_offset=740, row_spacing=46)

    # 2. What Signals We Collect
    m2_summary = (
        "We audit your actual website code and public Google listings to see exactly what a customer experiences in real time.[cite: 2]\n"
        "This is vital because hidden technical flaws—like missing phone tags or unlisted addresses—silently block ready-to-buy customers from reaching you.[cite: 2]"
    )
    m2_rows = [
        ("Technical Scraping", "Inspects <form> tags, tel: click-to-call links, JSON-LD Schema, viewport tags, H1/H2 hierarchy, and alt tags."),
        ("Marketing Stack Detection", "Verifies presence of Google Tag Manager (GTM), Google Analytics 4 (GA4), and Meta Pixel tracking containers."),
        ("Interactive Widgets & CMS", "Scans iframe/DOM footprints for scheduling embeds (Calendly/Acuity) and live chat widgets (Podium/Tidio)."),
        ("Google Places Data", "Captures verified Google star ratings, total review counts, verified NAP address, and category taxonomy.")
    ]
    y = draw_section_card(draw, y, 365, "2. What Signals We Collect", "PUBLIC DISCOVERY", m2_summary, m2_rows, gap=MODULE_GAP_5MOD, col2_offset=740, row_spacing=46)

    # 3. Priority Scores
    m3_summary = (
        "These four scores represent the primary decision points where a local customer chooses either you or your closest competitor.[cite: 2]\n"
        "Improving these ensures your business is easy to find on Google Maps, loads instantly on mobile, and allows callers to reach you with a single tap.[cite: 2]"
    )
    m3_rows = [
        ("Website Loading Speed", "Measures homepage latency in seconds; slow mobile rendering causes immediate customer abandonment."),
        ("Ease of Booking & Calling", "Evaluates mobile 1-tap dial buttons, direct inquiry forms, and booking calendar embed availability."),
        ("Lead Capture & Tracking", "Scored from active marketing pixels, GTM tags, and lead capture architectures capturing visitor intent."),
        ("Local Search & Maps", "Synthesizes star ratings, review velocity, and LocalBusiness schema required to rank in the Local 3-Pack.")
    ]
    y = draw_section_card(draw, y, 365, "3. Priority Scores · Why These 4", "URGENCY PILLARS", m3_summary, m3_rows, gap=MODULE_GAP_5MOD, col2_offset=740, row_spacing=46)

    # 4. Permission Access Gateway
    m4_summary = (
        "Public scans only evaluate external website symptoms, not your actual credit balances, marketing budget waste, or true customer volume.[cite: 2]\n"
        "Granting temporary view-only access lets us open the hood to prove exactly how many calls were missed and how many ad dollars were wasted.[cite: 2]"
    )
    m4_rows = [
        ("Public Audit Limitations", "Public scraping detects code presence, but cannot quantify lost dollars, ad waste, or funnel bounce points."),
        ("Google Search Console", "Requires View-level access to reveal exact customer search phrases, total impressions, and organic SERP rank."),
        ("Google Analytics 4 & Ads", "Unlocks verified lead conversion funnels, visitor drop-off pages, true CPA, and negative keyword ad spend waste."),
        ("Google Business Profile", "OAuth authorization unlocks actual phone call clicks, direction routes, and monthly Map search queries.")
    ]
    y = draw_section_card(draw, y, 365, "4. Permission Access Gateway · Unlocking Your Revenue Opportunity", "API ACCESS", m4_summary, m4_rows, gap=MODULE_GAP_5MOD, col2_offset=740, row_spacing=46)

    # 5. Mathematical Modeling Foundations
    m5_summary = (
        "We use strict mathematical formulas rather than subjective opinions to benchmark your performance against local market rivals.[cite: 2]\n"
        "This gives you an honest, transparent breakdown of where your setup is strong and the exact quick fixes that will generate more customer inquiries.[cite: 2]"
    )
    m5_rows = [
        ("Speed Formula", "max(10, min(100, 100 - (load_speed_sec * 18)))  -> Directly maps response latency into a 10-100 scale."),
        ("Conversion", "30(has_click_to_call) + 25(has_lead_form) + 25(has_booking/chat) + 20(is_mobile_responsive)."),
        ("Reputation", "15(has_ssl) + min(45, rating * 9) + min(40, sqrt(reviews) * 1.5)  -> Smooth curve rewards review depth."),
        ("Marketing Stack", "40(has_ga4) + 30(has_gtm) + 20(has_meta_pixel) + 10(social_links_present).")
    ]
    y = draw_section_card(draw, y, 365, "5. Mathematical Modeling Foundations", "EXACT UNBIASED ALGORITHMS", m5_summary, m5_rows, gap=MODULE_GAP_5MOD, col2_offset=740, row_spacing=46)

    draw_scorecard_footer(draw)
    img.save(out_path, "PDF", resolution=300.0)
    print(f"  -> Generated: {out_path}")

# ==============================================================================
# 5. INTERACTIVE TERMINAL QUERY CONTROLLER
# ==============================================================================
def parse_sheet_selection(user_input: str) -> set:
    """
    Parses numeric selections and text equivalents into a set of sheet numbers: {1}, {2}, {3}.
    Accepts: '1', '2', '3', '1 and 2', '2 and 3', '1 and 3', 'all', 'all three', etc.
    """
    cleaned = user_input.strip().lower()
    
    # Handle direct text shortcuts
    if cleaned in ["all", "all three", "all 3", "4", "7", ""]:
        return {1, 2, 3}
    if cleaned in ["1 and 2", "1 & 2", "1, 2", "1,2", "1 2", "5"]:
        return {1, 2}
    if cleaned in ["2 and 3", "2 & 3", "2, 3", "2,3", "2 3", "6"]:
        return {2, 3}
    if cleaned in ["1 and 3", "1 & 3", "1, 3", "1,3", "1 3"]:
        return {1, 3}
    
    # Extract any digits entered
    digits = set()
    for char in cleaned:
        if char in "123":
            digits.add(int(char))
    
    return digits if digits else {1, 2, 3}

if __name__ == "__main__":
    script_dir = Path(__file__).resolve().parent
    sheet_1_path = str(script_dir / "Scorecard_Data_Authorized_1st_Party.pdf")
    sheet_2_path = str(script_dir / "Scorecard_Data_Paid_3rd_Party.pdf")
    sheet_3_path = str(script_dir / "Scorecard_Grading_Methodology.pdf")

    print("\n" + "=" * 65)
    print("      ELKINS & CO. DATA & METHODOLOGY SHEET RENDERER")
    print("=" * 65)
    print("Select which document(s) you would like to produce:")
    print("  [1] Just Sheet 1  (Authorized 1st-Party Client Data)")
    print("  [2] Just Sheet 2  (3rd-Party Paid Intelligence Layer)")
    print("  [3] Just Sheet 3  (Audit Scoring & Grading Methodology)")
    print("  [4] Sheet 1 and 2 (Both Data Tear-Sheets)")
    print("  [5] Sheet 2 and 3 (Competitive Layer + Scoring Logic)")
    print("  [6] Sheet 1 and 3 (1st-Party Data + Scoring Logic)")
    print("  [7] All Three     (Full 3-Document Executive Package)")
    print("-" * 65)

    user_choice = input("Enter choice [1-7 or description, Default: All Three]: ").strip()
    selected_sheets = parse_sheet_selection(user_choice)

    print(f"\nProcessing active queue for Sheet(s): {sorted(list(selected_sheets))}...\n")

    if 1 in selected_sheets:
        print("[Sheet 1] Generating Authorized 1st-Party Client Data Specification...")
        render_sheet_first_party(sheet_1_path)

    if 2 in selected_sheets:
        print("[Sheet 2] Generating 3rd-Party Paid Intelligence Layer...")
        render_sheet_third_party(sheet_2_path)

    if 3 in selected_sheets:
        print("[Sheet 3] Generating Scoring Methodology & Analytical Foundations...")
        render_sheet_scoring_methodology(sheet_3_path)

    print("\nExecution complete. Output files ready in 300 DPI print-ready PDF format.")