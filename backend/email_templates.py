"""
HTML email templates for SonicDNA user engagement and recalibration reminders.
Crafted with dark-mode aesthetic, neon cyan accents, and mobile-responsive layout.
"""

from __future__ import annotations

from typing import Optional


def render_recalibration_reminder(
    display_name: str,
    archetype: Optional[str] = None,
    shadow_archetype: Optional[str] = None,
    days_elapsed: int = 7,
    recalibrate_url: str = "https://sonicdna.app/#quiz",
) -> str:
    """
    Generate responsive HTML email for the 7-14 day Taste Genome recalibration reminder.
    """
    name = (display_name or "Sonic Explorer").strip()
    primary_badge = archetype or "Uncalibrated Sound"
    shadow_badge = f" • Shadow: {shadow_archetype}" if shadow_archetype else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Time to Recalibrate Your Taste Genome</title>
  <style>
    body {{
      margin: 0;
      padding: 0;
      background-color: #0B0C10;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      color: #C5C6C7;
      -webkit-font-smoothing: antialiased;
    }}
    .wrapper {{
      width: 100%;
      background-color: #0B0C10;
      padding: 40px 16px;
      box-sizing: border-box;
    }}
    .container {{
      max-width: 580px;
      margin: 0 auto;
      background-color: #12151E;
      border: 1px solid #1F2833;
      border-radius: 16px;
      overflow: hidden;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
    }}
    .header {{
      padding: 32px 32px 20px;
      text-align: center;
      border-bottom: 1px solid #1F2833;
      background: linear-gradient(180deg, #181E2E 0%, #12151E 100%);
    }}
    .logo {{
      font-size: 22px;
      font-weight: 800;
      letter-spacing: 0.15em;
      color: #66FCF1;
      text-transform: uppercase;
      margin: 0 0 8px;
    }}
    .tagline {{
      font-size: 11px;
      letter-spacing: 0.25em;
      color: #45A29E;
      text-transform: uppercase;
      margin: 0;
    }}
    .content {{
      padding: 36px 32px;
      line-height: 1.6;
    }}
    h1 {{
      font-size: 24px;
      font-weight: 700;
      color: #FFFFFF;
      margin: 0 0 16px;
      letter-spacing: -0.01em;
    }}
    p {{
      font-size: 15px;
      color: #A0A5B5;
      margin: 0 0 20px;
    }}
    .badge-card {{
      background: #181C28;
      border: 1px solid #2B3547;
      border-radius: 12px;
      padding: 20px;
      margin: 24px 0;
      text-align: center;
    }}
    .badge-label {{
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.18em;
      color: #45A29E;
      margin-bottom: 6px;
    }}
    .badge-title {{
      font-size: 20px;
      font-weight: 700;
      color: #66FCF1;
      margin: 0;
    }}
    .badge-sub {{
      font-size: 12px;
      color: #8C93A8;
      margin-top: 6px;
    }}
    .cta-container {{
      text-align: center;
      margin: 32px 0 16px;
    }}
    .cta-button {{
      display: inline-block;
      background: linear-gradient(135deg, #66FCF1 0%, #45A29E 100%);
      color: #0B0C10 !important;
      font-weight: 700;
      font-size: 15px;
      letter-spacing: 0.04em;
      text-decoration: none;
      padding: 14px 36px;
      border-radius: 9999px;
      box-shadow: 0 4px 20px rgba(102, 252, 241, 0.25);
    }}
    .footer {{
      padding: 24px 32px;
      border-top: 1px solid #1F2833;
      text-align: center;
      font-size: 12px;
      color: #626A7F;
    }}
    .footer a {{
      color: #45A29E;
      text-decoration: none;
    }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="container">
      <div class="header">
        <div class="logo">SonicDNA</div>
        <div class="tagline">Acoustic Identity System</div>
      </div>
      <div class="content">
        <h1>Has your musical sound shifted?</h1>
        <p>Hey {name},</p>
        <p>
          It has been <strong>{days_elapsed} days</strong> since your acoustic coordinates were last calculated.
          Musical taste evolves constantly as you encounter new moods, tracks, and rhythms.
        </p>

        <div class="badge-card">
          <div class="badge-label">Current Recorded Archetype</div>
          <div class="badge-title">{primary_badge}</div>
          <div class="badge-sub">{shadow_badge}</div>
        </div>

        <p>
          Recalibrating takes under 2 minutes. See how your taste genome has drifted, track your timeline evolution, and discover new compatibility wavelengths.
        </p>

        <div class="cta-container">
          <a href="{recalibrate_url}" class="cta-button" target="_blank">Recalibrate My Genome &rarr;</a>
        </div>
      </div>
      <div class="footer">
        <p style="margin: 0 0 8px;">SonicDNA &bull; Decoding acoustic identity and musical resonance</p>
        <p style="margin: 0;">You are receiving this reminder because you calibrated your SonicDNA profile.</p>
      </div>
    </div>
  </div>
</body>
</html>
"""
