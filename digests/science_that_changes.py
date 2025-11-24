#!/usr/bin/env python3
"""
Science That Changes Everything – FINAL PROFESSIONAL EDITION
6+ real breakthroughs · 100% real links · Life-upgrading
November 19, 2025+
"""

import os
import datetime
import re
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
import tweepy

# ========================== BULLETPROOF .env ==========================
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
env_path = project_root / ".env"
if not env_path.exists():
    raise FileNotFoundError(f".env not found at {env_path}")
load_dotenv(dotenv_path=env_path)

grok_client = OpenAI()
x_client = tweepy.Client(
    consumer_key=os.getenv("X_CONSUMER_KEY"),
    consumer_secret=os.getenv("X_CONSUMER_SECRET"),
    access_token=os.getenv("X_ACCESS_TOKEN"),
    access_token_secret=os.getenv("X_ACCESS_TOKEN_SECRET"),
    wait_on_rate_limit=True
)

def post():
    today = datetime.date.today().strftime("%B %d, %Y")
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()

    prompt = f"""You are "Science That Changes Everything" – the most exciting, actionable science digest on Earth.
Date: {today}
MANDATORY RULES: - You MUST include at least 6 real breakthroughs from the last 24 hours only (from {yesterday} onward) in biology, physics, AI, medicine, energy, space, quantum, neuroscience, materials, longevity, etc. - Every story MUST have a complete real link - No placeholders, no invented content
Output EXACTLY this markdown:
# Science That Changes Everything – {today}
### 6+ Mind-Blowing Discoveries (last 24h)
1. **Title** Full self-contained 3–5 sentence summary + why it matters + how people can learn from it, use it, or profit. [Source](link)
2–6+ ...
### Quote of the Day > “Exact quote” — Scientist, [source →](link)
### Life-Changing Takeaway One paragraph: the biggest opportunity these discoveries create for regular people right now.
### Daily Science Challenge Today I challenge you to __________________________ Reply or quote this post @planetterrian with what you learned/did — let’s level up humanity together!
The future is here today. Let’s build it. ⚡️🧬🔭🧠"""

    response = grok_client.chat.completions.create(
        model="grok-4",
        messages=[
            {"role": "system", "content": f"MANDATORY: Minimum 6 real science breakthroughs from {yesterday} onward. Every link must be complete and real. Actionable, positive tone."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.9,
        max_tokens=3800,
        extra_body={
            "search_parameters": {
                "mode": "on",
                "max_search_results": 29,
                "from_date": yesterday,
                "return_citations": True
            }
        }
    )

    digest = response.choices[0].message.content.strip()
    digest = "\n".join(line for line in digest.splitlines() if not line.strip().startswith("**Sources used by Grok"))

    digest = re.sub(r'https?://(x\.com|twitter\.com)/i/web/status/(\d+)', r'https://x.com/planetterrian/status/\2', digest)
    digest = re.sub(r'https?://(x\.com|twitter\.com)/status/(\d+)', r'https://x.com/planetterrian/status/\2', digest)

    try:
        tweet = x_client.create_tweet(text=digest)
        url = f"https://x.com/planetterrian/status/{tweet.data['id']}"
        print(f"Science digest LIVE → {url}")
    except Exception as e:
        print(f"Science post failed: {e}")

    filename = project_root / f"Science_Digest_{datetime.date.today():%Y-%m-%d}.md"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(digest)

if __name__ == "__main__":
    post()