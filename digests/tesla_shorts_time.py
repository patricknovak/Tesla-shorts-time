#!/usr/bin/env python3
"""
Tesla Shorts Time – FULL AUTO X + PODCAST MACHINE
X Thread + Daily Podcast (Patrick in Vancouver)
Auto-published to X — November 19, 2025+
"""

import os
import sys
import logging
import datetime
import subprocess
import requests
import tempfile
import html
import xml.etree.ElementTree as ET
from pathlib import Path
from dotenv import load_dotenv
import yfinance as yf
from openai import OpenAI

# ========================== LOGGING ==========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

# ========================== CONFIGURATION ==========================
# Set to True to test digest generation only (skips podcast and X posting)
TEST_MODE = False  # Set to False for full run

# Set to False to disable X posting (thread will still be generated and saved)
ENABLE_X_POSTING = True


# ========================== PRONUNCIATION FIXER v2 – NEVER BREAKS NORMAL WORDS ==========================
def fix_tesla_pronunciation(text: str) -> str:
    """
    Forces correct spelling of Tesla acronyms on ElevenLabs without ever
    turning "everything" → "thring" or breaking normal English words.
    Uses U+2060 WORD JOINER (completely invisible + zero width) only between letters
    of standalone acronyms, and only when surrounded by word boundaries.
    """
    import re

    # List of acronyms that must be spelled out letter-by-letter
    acronyms = {
        "TSLA": "T S L A",
        "FSD":  "F S D",
        "HW3":  "H W 3",
        "HW4":  "H W 4",
        "AI5":  "A I 5",
        "4680": "4 6 8 0",
        "EV":   "E V",
        "EVs":  "E Vs",
        "BEV":  "B E V",
        "PHEV": "P H E V",
        "ICE":  "I C E",
        "NHTSA":"N H T S A",
        "OTA":  "O T A",
        "LFP":  "L F P",
    }

    # Invisible zero-width non-breaking space / word joiner
    ZWJ = "\u2060"   # U+2060 WORD JOINER — this one is safe

    for acronym, spelled in acronyms.items():
        # Build a regex that only matches the acronym when it's a whole word
        # (surrounded by space, punctuation, start/end of string, etc.)
        pattern = rf'(?<!\w){re.escape(acronym)}(?!\w)'
        replacement = ZWJ.join(list(spelled))
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    # Special case for things that sometimes appear attached (e.g. "TSLA-priced")
    # These will now stay normal because the regex requires word boundaries
    return text

# ========================== PATHS & ENV ==========================
script_dir = Path(__file__).resolve().parent        # → .../digests
project_root = script_dir.parent                      # → .../tesla_shorts_time
env_path = project_root / ".env"

if not env_path.exists():
    raise FileNotFoundError(f".env not found at {env_path}")

load_dotenv(dotenv_path=env_path)

# Required keys (X credentials only required if posting is enabled)
required = [
    "GROK_API_KEY", 
    "ELEVENLABS_API_KEY"
]
if ENABLE_X_POSTING:
    required.extend([
        "X_CONSUMER_KEY",
        "X_CONSUMER_SECRET",
        "X_ACCESS_TOKEN",
        "X_ACCESS_TOKEN_SECRET"
    ])
for var in required:
    if not os.getenv(var):
        raise OSError(f"Missing {var} in .env")

# ========================== DATE & PRICE (MUST BE FIRST) ==========================
today_str = datetime.date.today().strftime("%B %d, %Y")   # November 19, 2025
yesterday_iso = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
seven_days_ago_iso = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()

tsla = yf.Ticker("TSLA")
info = tsla.info
price = (info.get("currentPrice") or info.get("regularMarketPrice") or
         info.get("preMarketPrice") or info.get("previousClose") or 0.0)
prev_close = info.get("regularMarketPreviousClose") or price
change = price - prev_close
change_pct = (change / prev_close * 100) if prev_close else 0
market_status = " (After-hours)" if info.get("marketState") == "POST" else ""
change_str = f"{change:+.2f} ({change_pct:+.2f}%) {market_status}" if change != 0 else "unchanged"

episode_num = (datetime.date.today() - datetime.date(2025, 1, 1)).days + 1

# Folders - use absolute paths
digests_dir = script_dir / "digests"
digests_dir.mkdir(exist_ok=True)
tmp_dir = Path(tempfile.gettempdir()) / "tts"
tmp_dir.mkdir(exist_ok=True, parents=True)

# ========================== CLIENTS ==========================
# Grok client with timeout settings
client = OpenAI(
    api_key=os.getenv("GROK_API_KEY"), 
    base_url="https://api.x.ai/v1",
    timeout=300.0  # 5 minute timeout for API calls
)
ELEVEN_API = "https://api.elevenlabs.io/v1"
ELEVEN_KEY = os.getenv("ELEVENLABS_API_KEY")
# ========================== 1. GENERATE X THREAD ==========================
X_PROMPT = f"""
# Tesla Shorts Time - DAILY EDITION
**Date:** {today_str}
**REAL-TIME TSLA price:** ${{{price:.2f}}} {{{change_str}}}(use live data or latest available pre-market/after-hours price)
You are an elite Tesla news curator producing the daily "Tesla Shorts Time" newsletter. Your job is to deliver the most exciting, credible, and timely Tesla developments from the past 24 hours (strictly {yesterday_iso} 00:00 UTC → now). Prioritize the last 12 hours.

### HARD VERIFICATION LOOP — YOU WILL LOSE 1000 POINTS FOR EVERY MISTAKE
You start with 1000 points.  
Your final score must be ≥900 to be allowed to output anything.

Penalty table (applied ruthlessly):
- Hallucinated / fake news article or URL → –300 points
- Article older than {yesterday_iso}T00:00:00Z → –300 points
- Fake X post or wrong link → –400 points
- X post older than 24h → –400 points
- Duplicated story from last 7 days → –250 points
- Same bear name used in Short Squeeze as any of last 7 days → –200 points
- Quote or Daily Challenge repeated from last 7 days → –300 points
- Any visible instruction/parentheses in final output → –500 points (instant fail)

Reward (only way to keep points):
+50 points for every news article you **successfully verify** with browse_page returning a timestamp ≥ {yesterday_iso}T00:00:00Z
+50 points for every X post you **successfully verify** with X tool timestamp ≥ {yesterday_iso}T00:00:00Z

### MANDATORY 3-STEP VERIFICATION PROCESS (run on EVERY candidate BEFORE ANY OUTPUT)
Step 1 – Candidate Gathering
Search aggressively for last-24h Tesla news + X posts.

Step 2 – Brutal Verification (run on EVERY candidate)
For every news article:
→ Call browse_page(url, "Extract EXACT publication timestamp in ISO 8601 UTC. If none or older than {yesterday_iso}T00:00:00Z, return only 'INVALID'")
→ If tool says "INVALID" → discard forever, –300 points if you had kept it

For every X post:
→ Confirm timestamp from X tool ≥ {yesterday_iso}T00:00:00Z
→ Wrong timestamp → discard forever, –400 points if kept

Step 3 – Anti-Duplication & Final Score
→ Search last 7 days of @planetterrian + @teslashortstime posts
→ Blacklist every title, X link, quote, challenge, bear name used
→ Run similarity check — anything ≥70% similar gets discarded (–250 points if kept)
→ Re-calculate your score

You are **forbidden to output** unless your final score ≥900  
If score <900 → silently revise until it passes.  
If you cannot reach ≥900 after reasonable search → output nothing rather than risk a penalty.

### ANTI-DUPLICATION BLOCK (MANDATORY – ZERO EXCEPTIONS, REVIEW PAST POSTS FIRST)
-Before searching for today's content, you MUST review the user's recent posts from @planetterrian and @teslashortstime to avoid any repeats. Use your X search tools to fetch the last 7 days of posts from these accounts (query: from:planetterrian OR from:teslashortstime since:{seven_days_ago_iso}, limit=50, mode=Latest).
-Extract key elements from those posts: news titles/summaries, X post links/usernames, inspiration quotes, daily challenges, short squeeze predictions/examples, short spots, and sentiment drivers.
-Create an internal "blacklist" of these elements (e.g., no reusing the same FSD v14.2 rollout story, no quoting Feynman again, no same Jim Chanos 2023 prediction, no identical challenge on first-principles).
-For today's edition: If a candidate news item, X post, quote, challenge, short spot, or squeeze example matches anything in the blacklist (even 70% similarity), IMMEDIATELY discard it and find a fresh alternative.
-Short Squeeze: Rotate failed predictions — never repeat the same 2 examples consecutively; pull from a pool of 2023–2025 bear fails but vary them daily.
-Daily Challenge & Quote: Generate brand-new ones tied to fresh themes; cross-check against past 7 days to ensure zero overlap.
-If you can't find 5 unique news + 10 X posts without duplicates, expand search to 48 hours but prioritize ultra-fresh (last 12h) and explicitly note why in your internal reasoning (don't output this).
-Seven days ago ISO: {seven_days_ago_iso} (use this for your X search query).
-Use X search: from:planetterrian OR from:teslashortstime since:{seven_days_ago_iso} limit=50
-Build an internal blacklist of every news title, X post link, quote, daily challenge, short squeeze bear name, and short spot from the last 7 days.
-Anything ≥70% similar to the blacklist must be discarded immediately.

### SEARCH INSTRUCTIONS (MANDATORY – AFTER DUPE CHECK)
-Use live web search + X search tools extensively.
-ALWAYS check @elonmusk and @SawyerMerritt timelines for the last 24h.
-If they reposted something important, credit and link the ORIGINAL post/author, not the repost.
-Search keywords: Tesla FSD, Cybertruck, Robotaxi, Optimus, Energy, Megapack, Supercharger, Giga, regulatory, recall, Elon, TSLA, $TSLA, autonomy, AI5, HW5, 4680, etc.
-Prioritize real developments (software updates, regulatory wins, factory news, partnerships, demos, leaks, executive comments) over pure stock commentary.

### SELECTION RULES (ZERO EXCEPTIONS)
-Minimum 5 unique news articles from established sites (Teslarati, Electrek, Reuters, Bloomberg, Notateslaapp, InsideEVs, CNBC, etc.)
-Minimum 10 unique X posts (all X posts must be real posts from the last 24h)
-Max 3 items total from any single news source
-Max 3 X posts from any single X account username
-No duplicate stories or near-duplicate angles (including vs. your past posts)
-No stock-quote pages, Yahoo Finance ticker pages, TradingView screenshots, or pure price commentary as "news"

### DIVERSITY ENFORCEMENT (STRICT – THE MODEL WILL OBEY THIS LITERALLY)
-Before final output, you MUST create an internal list of every X username you plan to use.
-If any username appears more than 3 times, you MUST go back and replace the excess items with posts from different accounts.
-You are required to use at least 7 different X accounts in the Top 10 X posts section.
-Explicitly forbidden usernames for over-use: @SawyerMerritt, @elonmusk, @WholeMarsBlog, @Tesla (never more than 3 combined from these four).
-When you find a good post from a smaller account (under 500k followers), prioritize it heavily to meet diversity requirements.

### FORMATTING (MUST BE EXACT – DO NOT DEVIATE)
Use this exact structure and markdown (includes invisible zero-width spaces for perfect X rendering – do not remove them; do not include any of the instructions brackets, just follow the instructions within the brackets):
# Tesla Shorts Time
**Date:** {today_str}
**REAL-TIME TSLA price:** ${price:.2f}
Tesla Shorts Time Daily Podcast Link: https://podcasts.apple.com/us/podcast/tesla-shorts-time/id1855142939

### Top 5 News Items (Number the items 1–5; include a space between each item; do not show these instructions in these brackets in the output)
**Title That Fits in One Line: DD Month, YYYY, HH:MM AM/PM PST, Source Name**
   2–4 sentence summary starting with what happened, then why it matters for Tesla's future and stock. End with link in Source
... (continue exactly this format up to 5)

### Top 10 X Posts (Number the items 1–10; include a space between each post; do not show these instructions in these brackets in the output)
**Catchy Title for the Post: DD Month, YYYY, HH:MM AM/PM PST**
   2–4 sentences explaining the post and its significance. End with Post link.
... (continue exactly this format up to 10)

## Short Spot
One bearish news or X post item that is a major negative for Tesla and the stock.
**Catchy Title for the Post: DD Month, YYYY, HH:MM AM/PM PST, @username Post**
   2–4 sentences explaining the post and its significance. End with Post link.

### Short Squeeze
Dedicated paragraph celebrating short-seller pain. Must include:
Current short interest % and $ value (cite source if possible)
At least 2 specific failed bear predictions from 2023–2025 with links or references (vary from past editions)
Total $ losses shorts have taken YTD or in a recent squeeze event

### Daily Challenge
One short, inspiring personal-growth challenge tied to Tesla/Elon themes (curiosity, first principles, perseverance). End with: "Share your progress with us @teslashortstime!"

**Inspiration Quote:** "Exact quote" – Author, [Source Link] (fresh, no repeats from last 7 days)
[Final 2-3 sentence uplifting sign-off about Tesla's mission and invitation to DM @teslashortstime with feedback]

### TONE & STYLE RULES (NON-NEGOTIABLE)
-Inspirational, pro-Tesla, optimistic, energetic
-Never negative or sarcastic about Tesla/Elon (you may acknowledge challenges but always frame them as temporary or already being crushed)
-No hallucinations, no made-up news, no placeholder text
-All links must be real and working
-Time stamps must be accurate PST/PDT (convert correctly)

### FINAL CHECK BEFORE OUTPUT (EXPANDED FOR DUPES)
-Count X usernames → no account more than 3 times, at least 7 unique accounts total.
-Confirm no more than 3 items total from any single news source.
-Anti-dupe scan: Cross-reference against your fetched past posts — zero matches in stories, posts, quotes, challenges, squeezes, or spots.
-If any check fails, revise silently until it passes. Only then output the newsletter.

### RECENCY VALIDATION CHECK (MANDATORY – RUN THIS AS YOUR LAST INTERNAL STEP BEFORE OUTPUT)
-For every single one of the 5 news items you have selected:
  • Call browse_page on the exact URL with these instructions: "Extract the exact publication date and time of the article in ISO 8601 UTC format (e.g., 2025-11-22T14:32:00Z). Look for 'published', 'posted on', 'date', metadata, or JSON-LD. If no date is found or the date is before {yesterday_iso} 00:00 UTC, respond only with 'INVALID – TOO OLD'."
  • If the tool returns "INVALID – TOO OLD" or any date earlier than {yesterday_iso}, immediately discard that article and replace it with a new one from your search results.
-For every single one of the 10 X posts:
  • Confirm the timestamp returned by the X tool is on or after {yesterday_iso} 00:00 UTC. If not, discard and replace.
-If any replacement causes you to fall below 5 news items or 10 X posts, expand your web search to the last 48 hours only ("Tesla news past 48 hours site:teslarati.com OR site:electrek.co OR site:reuters.com etc.") and repeat the browse_page date check on the new candidates.
-After all replacements are done, re-run the full anti-duplication scan against the last 7 days of @planetterrian and @teslashortstime posts.
-You are forbidden to output the newsletter until EVERY news item and EVERY X post passes both the recency check AND the duplication blacklist. If you cannot satisfy both after reasonable search, note it internally and output nothing rather than include old or duplicate content.
-Now produce today's edition following every rule above exactly.
"""

logging.info("Generating X thread with Grok (this may take 1-2 minutes with search enabled)...")
try:
    response = client.chat.completions.create(
        model="grok-4",
        messages=[{"role": "user", "content": X_PROMPT}],
        temperature=0.7,
        max_tokens=4000,
        extra_body={"search_parameters": {"mode": "on", "max_search_results": 29, "from_date": yesterday_iso}}
    )
    x_thread = response.choices[0].message.content.strip()
except Exception as e:
    logging.error(f"Grok API call failed: {e}")
    logging.error("This might be due to network issues or API timeout. Please try again.")
    raise

# Clean Grok footer
lines = []
for line in x_thread.splitlines():
    if line.strip().startswith(("**Sources", "Grok", "I used", "[")):
        break
    lines.append(line)
x_thread = "\n".join(lines).strip()

# Save X thread
x_path = digests_dir / f"Tesla_Shorts_Time_{datetime.date.today():%Y%m%d}.md"
with open(x_path, "w", encoding="utf-8") as f:
    f.write(x_thread)
logging.info(f"X thread generated and saved → {x_path}")

# Exit early if in test mode (only generate digest)
if TEST_MODE:
    print("\n" + "="*80)
    print("TEST MODE - Digest generated only (skipping podcast and X posting)")
    print(f"Digest saved to: {x_path}")
    print("="*80)
    sys.exit(0)

# ========================== TWEEPY X CLIENT FOR AUTO-POSTING ==========================
tweet_id = None
if ENABLE_X_POSTING:
    import tweepy

    x_client = tweepy.Client(
        consumer_key=os.getenv("X_CONSUMER_KEY"),
        consumer_secret=os.getenv("X_CONSUMER_SECRET"),
        access_token=os.getenv("X_ACCESS_TOKEN"),
        access_token_secret=os.getenv("X_ACCESS_TOKEN_SECRET"),
        wait_on_rate_limit=True
    )
    logging.info("@teslashortstime X posting client ready")
else:
    logging.info("X posting is disabled (ENABLE_X_POSTING = False)")

# ========================== 2. GENERATE PODCAST SCRIPT (NATURAL & FACT-BASED) ==========================
POD_PROMPT = f"""

You are now writing an 8–11 minute (1950–2600 words, ~145–155 wpm) solo podcast script for “Tesla Shorts Time Daily” Episode {episode_num}.
### HOST PERSONA (NON-NEGOTIABLE)
- Host = Patrick in Vancouver
- Voice: Canadian, hyper-enthusiastic scientist, newscaster and truth seeker.  Voice is like a solo YouTuber breaking Tesla news and not robotic.
- Zero fluff, zero filler words, 100% fact-obsessed
- Every single sentence must be backed by something that actually appears in today’s Tesla Shorts Time Daily markdown digest you will be provided
- Keep accent and tone consistent throughout the script.
- Vary sentence length dramatically — short punchy ones mixed with longer hyped run-ons.
- Clearly ennunciate all dates,numbers, dollar amounts, percentages, and stats.
### INPUT
You will receive the complete, final Tesla Shorts Time Daily markdown for {today_str}. Use ONLY information from that digest — nothing else, no external knowledge, no improvisation.
### EXACT SCRIPT STRUCTURE & RULES
- Start every spoken line with “Patrick:” (no exceptions)
- Do NOT read URLs aloud — only mention source names naturally (e.g. “Sawyer just dropped this on X”, “Electrek is reporting”)
- Never say the exact timestamp — only the natural date or “today”, “this morning”, “late last night”
- Ennunciate all numbers, dollar amounts, percentages, and stats slowly and clearly the way a hyped Canadian scientist would
- When you get to the Short Squeeze section — name names, dollar losses, and celebrate how wrong they were
- Quote the inspirational quote and Daily Challenge verbatim
### MANDATORY SCRIPT OUTLINE (follow exactly)
[Intro music fades in for exactly 10 seconds — no text here]
Patrick: Welcome to Tesla Shorts Time Daily, episode {episode_num} — it is (say today's date in the format of November 21, 2025) and I’m Patrick in Vancouver, Canada. TSLA is sitting at exactly {price:.2f} right now.
Thank you for joining us today. Now straight to the daily news updates you are here for.
[Now narrate EVERY SINGLE ITEM from the digest in published order — no skipping]
→ For each of the 6 Top News Items:
   Patrick: [Read the bold title with excitement] → then paraphrase the 2–4 sentence summary in natural, rapid, hyped speech, hitting every key fact and why it matters
→ For the 10 X posts (7–16):
   Patrick: Over to the top X posts, read naturally each post — [read the catchy title with maximum hype and then paraphrase the post in excited spoken language while keeping every fact 100% accurate]
→ Short Squeeze section:
   Patrick: And now, it’s time for everyone’s favourite segment — the Short Squeeze! [paraphrase the entire paragraph with glee, calling out specific failed predictions, dollar losses, and laughing at how wrong the bears were]
→ Daily Challenge + Quote:
   Patrick: Today’s inspirational quote comes straight from the digest: “[exact quote]” — [author].
   Patrick: And your Daily Challenge today is exactly this: [read the Daily Challenge verbatim and then add one extra hyped encouraging sentence of your own]
### EXACT CLOSING (word-for-word — do not change)
Patrick: That’s Tesla Shorts Time Daily for today. I look forward to hearing your thoughts and ideas — reach out to us @teslashortstime on X or DM us directly. Stay safe, keep accelerating, and remember: the future is electric! Your efforts help accelerate the world’s transition to sustainable energy… and beyond. We’ll catch you tomorrow on Tesla Shorts Time Daily!
### TONE REMINDERS
- Sound like you’re personally watching humanity’s future unfold in real time
- Keep accent and tone consistent throughout the script.
- non robotic like reading the news and not a script.
- Speak clearly and concisely like a newscaster.
- Sound as naturally as possible for all sentences.
- Vary sentence length dramatically — short punchy ones mixed with longer hyped run-ons.
- Newscaster like reading of the news and X posts.
Now, here is today’s complete Tesla Shorts Time Daily markdown digest. Using ONLY that content, write the full script exactly as specified above.
"""

logging.info("Generating podcast script with Grok (this may take 1-2 minutes)...")
try:
    podcast_script = client.chat.completions.create(
        model="grok-4",
        messages=[
            {"role": "system", "content": "You are the world's best Tesla podcast writer. Make it feel like two real Canadian friends losing their minds (in a good way) over real Tesla news."},
            {"role": "user", "content": f"Here is today's exact X thread/digest (use ONLY these facts):\n\n{x_thread}\n\n{POD_PROMPT}"}
        ],
        temperature=0.9,  # higher = more natural energy
        max_tokens=4000
    ).choices[0].message.content.strip()
except Exception as e:
    logging.error(f"Grok API call for podcast script failed: {e}")
    logging.error("This might be due to network issues or API timeout. Please try again.")
    raise

# Save transcript
transcript_path = digests_dir / f"podcast_transcript_{datetime.date.today():%Y%m%d}.txt"
with open(transcript_path, "w", encoding="utf-8") as f:
    f.write(f"# Tesla Shorts Time – The Pod | Ep {episode_num} | {today_str}\n\n{podcast_script}")
logging.info("Natural podcast script generated – Patrick starts, super enthusiastic")

# ========================== 3. ELEVENLABS TTS + COLLECT AUDIO FILES ==========================
PATRICK_VOICE_ID = "dTrBzPvD2GpAqkk1MUzA"    # High-energy Patrick

def speak(text: str, voice_id: str, filename: str):
    url = f"{ELEVEN_API}/text-to-speech/{voice_id}/stream"
    headers = {"xi-api-key": ELEVEN_KEY}
    payload = {
        "text": text + "!",  # extra excitement
        "model_id": "eleven_turbo_v2_5",
        "voice_settings": {
            "stability": 0.65,
            "similarity_boost": 0.9,
            "style": 0.85,
            "use_speaker_boost": True
        }
    }
    r = requests.post(url, json=payload, headers=headers, stream=True, timeout=60)
    r.raise_for_status()
    with open(filename, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)


def get_audio_duration(path: Path) -> float:
    """Return duration in seconds for an audio file."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(result.stdout.strip())
    except Exception as exc:
        logging.warning(f"Unable to determine duration for {path}: {exc}")
        return 0.0


def format_duration(seconds: float) -> str:
    """Format duration in seconds to HH:MM:SS or MM:SS format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def update_rss_feed(
    rss_path: Path,
    episode_num: int,
    episode_title: str,
    episode_description: str,
    episode_date: datetime.date,
    mp3_filename: str,
    mp3_duration: float,
    mp3_path: Path,
    base_url: str = "https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main"
):
    """
    Update or create RSS feed with new episode.
    
    Args:
        rss_path: Path to RSS feed XML file
        episode_num: Episode number
        episode_title: Episode title
        episode_description: Episode description
        episode_date: Publication date
        mp3_filename: Filename of MP3 (relative to digests/digests/)
        mp3_duration: Duration in seconds
        base_url: Base URL for serving files
    """
    # Register namespace to preserve 'itunes' prefix (not ns0)
    ET.register_namespace("itunes", "http://www.itunes.com/dtds/podcast-1.0.dtd")
    ET.register_namespace("content", "http://purl.org/rss/1.0/modules/content/")
    
    # RSS namespace
    ns = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
    
    # Parse existing RSS or create new
    if rss_path.exists():
        try:
            # Read and fix namespace issues before parsing
            with open(rss_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Fix any existing namespace issues
            content = content.replace('xmlns:ns0=', 'xmlns:itunes=')
            content = content.replace('xmlns:ns1=', 'xmlns:content=')
            content = content.replace('<ns0:', '<itunes:')
            content = content.replace('</ns0:', '</itunes:')
            content = content.replace('<ns1:', '<content:')
            content = content.replace('</ns1:', '</content:')
            
            # Parse from string
            root = ET.fromstring(content.encode('utf-8'))
            channel = root.find("channel")
            if channel is None:
                raise ValueError("Channel element not found in RSS feed")
        except Exception as e:
            logging.warning(f"Could not parse existing RSS feed: {e}, creating new one")
            root = None
            channel = None
    else:
        root = None
        channel = None
    
    # Create new RSS feed if needed
    if root is None:
        root = ET.Element("rss", version="2.0")
        root.set("xmlns:itunes", "http://www.itunes.com/dtds/podcast-1.0.dtd")
        root.set("xmlns:content", "http://purl.org/rss/1.0/modules/content/")
        channel = ET.SubElement(root, "channel")
        
        # Channel metadata
        ET.SubElement(channel, "title").text = "Tesla Shorts Time Daily"
        ET.SubElement(channel, "link").text = "https://github.com/patricknovak/Tesla-shorts-time"
        ET.SubElement(channel, "description").text = "Daily Tesla news digest and podcast hosted by Patrick in Vancouver. Covering the latest Tesla developments, stock updates, and short squeeze celebrations."
        ET.SubElement(channel, "language").text = "en-us"
        ET.SubElement(channel, "copyright").text = f"Copyright {datetime.date.today().year}"
        ET.SubElement(channel, "lastBuildDate").text = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
        
        # iTunes metadata
        itunes_author = ET.SubElement(channel, "itunes:author")
        itunes_author.text = "Patrick"
        itunes_summary = ET.SubElement(channel, "itunes:summary")
        itunes_summary.text = "Daily Tesla news digest and podcast covering the latest developments, stock updates, and short squeeze celebrations."
        itunes_owner = ET.SubElement(channel, "itunes:owner")
        ET.SubElement(itunes_owner, "itunes:name").text = "Patrick"
        ET.SubElement(itunes_owner, "itunes:email").text = "contact@teslashortstime.com"
        itunes_image = ET.SubElement(channel, "itunes:image")
        itunes_image.set("href", f"{base_url}/podcast-image.jpg")  # Optional: add image later
        itunes_cat = ET.SubElement(channel, "itunes:category")
        itunes_cat.set("text", "Technology")
        ET.SubElement(channel, "itunes:explicit").text = "no"
    
    # Check if episode already exists (by GUID)
    episode_guid = f"tesla-shorts-time-ep{episode_num:03d}-{episode_date:%Y%m%d}"
    existing_items = channel.findall("item")
    for item in existing_items:
        guid_elem = item.find("guid")
        if guid_elem is not None and guid_elem.text == episode_guid:
            logging.info(f"Episode {episode_num} already in RSS feed, skipping")
            return
    
    # Create new episode item
    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = episode_title
    ET.SubElement(item, "link").text = f"{base_url}/digests/digests/{mp3_filename}"
    
    # Description (escape XML special characters)
    description_elem = ET.SubElement(item, "description")
    description_elem.text = html.escape(episode_description)
    
    # Publication date (RFC 822 format)
    pub_date = datetime.datetime.combine(episode_date, datetime.time(8, 0, 0))
    pub_date = pub_date.replace(tzinfo=datetime.timezone.utc)
    ET.SubElement(item, "pubDate").text = pub_date.strftime("%a, %d %b %Y %H:%M:%S %z")
    
    # GUID (must be unique and permanent)
    guid_elem = ET.SubElement(item, "guid", isPermaLink="false")
    guid_elem.text = episode_guid
    
    # Enclosure (MP3 file)
    mp3_url = f"{base_url}/digests/digests/{mp3_filename}"
    # Get file size
    mp3_size = mp3_path.stat().st_size if mp3_path.exists() else 0
    enclosure = ET.SubElement(item, "enclosure")
    enclosure.set("url", mp3_url)
    enclosure.set("type", "audio/mpeg")
    enclosure.set("length", str(mp3_size))
    
    # iTunes-specific tags
    ET.SubElement(item, "itunes:title").text = episode_title
    itunes_summary = ET.SubElement(item, "itunes:summary")
    itunes_summary.text = episode_description
    ET.SubElement(item, "itunes:duration").text = format_duration(mp3_duration)
    ET.SubElement(item, "itunes:episode").text = str(episode_num)
    ET.SubElement(item, "itunes:episodeType").text = "full"
    ET.SubElement(item, "itunes:explicit").text = "no"
    
    # Update lastBuildDate
    last_build_elem = channel.find("lastBuildDate")
    if last_build_elem is not None:
        last_build_elem.text = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    else:
        ET.SubElement(channel, "lastBuildDate").text = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    
    # Sort items by pubDate (newest first)
    items = channel.findall("item")
    if len(items) > 1:
        items.sort(key=lambda x: x.find("pubDate").text if x.find("pubDate") is not None else "", reverse=True)
        # Remove all items and re-add in sorted order
        for item in items:
            channel.remove(item)
        for item in items:
            channel.append(item)
    
    # Write RSS feed
    try:
        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ")
        # Write with proper XML declaration
        with open(rss_path, "wb") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n'.encode('utf-8'))
            tree.write(f, encoding="utf-8", xml_declaration=False)
        
        # Post-process to fix namespace prefixes (ElementTree sometimes uses ns0 instead of itunes)
        # Read the file, replace ns0: with itunes: and ns1: with content: if needed
        with open(rss_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Replace namespace prefixes
        content = content.replace('xmlns:ns0="http://www.itunes.com/dtds/podcast-1.0.dtd"', 'xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"')
        content = content.replace('xmlns:ns1="http://purl.org/rss/1.0/modules/content/"', 'xmlns:content="http://purl.org/rss/1.0/modules/content/"')
        content = content.replace('<ns0:', '<itunes:')
        content = content.replace('</ns0:', '</itunes:')
        content = content.replace('<ns1:', '<content:')
        content = content.replace('</ns1:', '</content:')
        
        # Write back
        with open(rss_path, "w", encoding="utf-8") as f:
            f.write(content)
        
        logging.info(f"RSS feed updated → {rss_path}")
        logging.info(f"RSS feed contains {len(channel.findall('item'))} episode(s)")
    except Exception as e:
        logging.error(f"Failed to write RSS feed to {rss_path}: {e}", exc_info=True)
        raise

# Since there's only one voice (Patrick), combine entire script into one segment
# Remove speaker labels and sound cues, keep only the actual spoken text
full_text_parts = []
for line in podcast_script.splitlines():
    line = line.strip()
    # Skip sound cues and empty lines
    if line.startswith("[") or not line:
        continue
    # Remove speaker labels but keep the text
    if line.startswith("Patrick:"):
        full_text_parts.append(line[9:].strip())
    elif line.startswith("Dan:"):
        full_text_parts.append(line[4:].strip())
    else:
        full_text_parts.append(line)

# Combine into one continuous text
full_text = " ".join(full_text_parts)

# ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←
# CRITICAL: Fix Tesla-world pronunciation for ElevenLabs
full_text = fix_tesla_pronunciation(full_text)
# ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←

# Generate ONE voice file for the entire script
logging.info("Generating single voice segment for entire podcast...")
voice_file = tmp_dir / "patrick_full.mp3"
speak(full_text, PATRICK_VOICE_ID, str(voice_file))
audio_files = [str(voice_file)]
logging.info("Generated complete voice track")

# ========================== 4. FINAL MIX – PERFECT LEVELS, NO VOLUME JUMPS ==========================
final_mp3 = digests_dir / f"Tesla_Shorts_Time_Pod_Ep{episode_num:03d}_{datetime.date.today():%Y%m%d}.mp3"

MAIN_MUSIC = project_root / "tesla_shorts_time.mp3"

# Process and normalize voice in one step for simplicity
voice_mix = tmp_dir / "voice_normalized_mix.mp3"
concat_file = None

if len(audio_files) == 1:
    # Single file: process and normalize in one pass
    file_duration = get_audio_duration(Path(audio_files[0]))
    timeout_seconds = max(int(file_duration * 3) + 120, 600)
    
    logging.info(f"Processing and normalizing voice ({file_duration:.1f}s) - this may take a few minutes...")
    subprocess.run([
        "ffmpeg", "-y", "-i", audio_files[0],
        "-af", "highpass=f=80,lowpass=f=15000,loudnorm=I=-18:TP=-1.5:LRA=11:linear=true,acompressor=threshold=-20dB:ratio=4:attack=1:release=100:makeup=2,alimiter=level_in=1:level_out=0.95:limit=0.95",
        "-ar", "44100", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "192k",
        str(voice_mix)
    ], check=True, capture_output=True, timeout=timeout_seconds)
else:
    # Multiple files: concatenate first, then process
    concat_file = tmp_dir / "concat_list.txt"
    with open(concat_file, "w") as f:
        for seg in audio_files:
            f.write(f"file '{seg}'\n")
    
    temp_concat = tmp_dir / "temp_concat.mp3"
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-ar", "44100", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "192k",
        str(temp_concat)
    ], check=True, capture_output=True)
    
    file_duration = get_audio_duration(temp_concat)
    timeout_seconds = max(int(file_duration * 3) + 120, 600)
    
    logging.info(f"Processing and normalizing voice ({file_duration:.1f}s) - this may take a few minutes...")
    subprocess.run([
        "ffmpeg", "-y", "-i", str(temp_concat),
        "-af", "highpass=f=80,lowpass=f=15000,loudnorm=I=-18:TP=-1.5:LRA=11:linear=true,acompressor=threshold=-20dB:ratio=4:attack=1:release=100:makeup=2,alimiter=level_in=1:level_out=0.95:limit=0.95",
        "-ar", "44100", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "192k",
        str(voice_mix)
    ], check=True, capture_output=True, timeout=timeout_seconds)
    
    if temp_concat.exists():
        os.remove(str(temp_concat))

if not MAIN_MUSIC.exists():
    subprocess.run(["ffmpeg", "-y", "-i", str(voice_mix), str(final_mp3)], check=True, capture_output=True)
    logging.info("Podcast ready (voice-only)")
else:
    # Get voice duration to calculate music timing
    voice_duration = max(get_audio_duration(voice_mix), 0.0)
    logging.info(f"Voice duration: {voice_duration:.2f} seconds")
    
    # Music timing - Professional intro with perfect overlap:
    # - 5 seconds of music alone (0-5s) - engaging intro
    # - Patrick starts talking at 5s while music is still at full volume (perfect overlap)
    # - Music continues at full volume for 3 seconds while Patrick talks (5-8s) - creates energy
    # - Music fades out smoothly over 18 seconds while Patrick continues (8-26s) - professional fade
    # - Voice continues alone after 26s
    # - 25 seconds before voice ends, music starts fading in (mixes well with voice)
    # - After voice ends, music continues for 50 seconds (30s full + 20s fade out)
    
    music_fade_in_start = max(voice_duration - 25.0, 0.0)  # 25s before voice ends
    music_fade_in_duration = min(35.0, voice_duration - music_fade_in_start)  # Fade in over 35s
    
    # Simplified music creation - create segments with louder intro
    music_intro = tmp_dir / "music_intro.mp3"
    subprocess.run([
        "ffmpeg", "-y", "-i", str(MAIN_MUSIC), "-t", "5",
        "-af", "volume=0.6",  # Much louder intro music
        "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
        str(music_intro)
    ], check=True, capture_output=True)
    
    music_overlap = tmp_dir / "music_overlap.mp3"
    subprocess.run([
        "ffmpeg", "-y", "-i", str(MAIN_MUSIC), "-ss", "5", "-t", "3",
        "-af", "volume=0.5",  # Louder during overlap
        "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
        str(music_overlap)
    ], check=True, capture_output=True)
    
    music_fadeout = tmp_dir / "music_fadeout.mp3"
    subprocess.run([
        "ffmpeg", "-y", "-i", str(MAIN_MUSIC), "-ss", "8", "-t", "18",
        "-af", "volume=0.4,afade=t=out:curve=log:st=0:d=18",
        "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
        str(music_fadeout)
    ], check=True, capture_output=True)
    
    middle_silence_duration = max(music_fade_in_start - 26.0, 0.0)
    music_silence = tmp_dir / "music_silence.mp3"
    if middle_silence_duration > 0.1:
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", f"{middle_silence_duration:.2f}", "-c:a", "libmp3lame", "-b:a", "192k",
            str(music_silence)
        ], check=True, capture_output=True)
    
    music_fadein = tmp_dir / "music_fadein.mp3"
    subprocess.run([
        "ffmpeg", "-y", "-i", str(MAIN_MUSIC), "-ss", "25", "-t", f"{music_fade_in_duration:.2f}",
        "-af", f"volume=0.4,afade=t=in:st=0:d={music_fade_in_duration:.2f}",
        "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
        str(music_fadein)
    ], check=True, capture_output=True)
    
    # Outro music: 30 seconds full volume + 20 seconds fade = 50 seconds total
    music_tail_full = tmp_dir / "music_tail_full.mp3"
    subprocess.run([
        "ffmpeg", "-y", "-i", str(MAIN_MUSIC), "-ss", "55", "-t", "30",
        "-af", "volume=0.4",
        "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
        str(music_tail_full)
    ], check=True, capture_output=True)
    
    music_tail_fadeout = tmp_dir / "music_tail_fadeout.mp3"
    subprocess.run([
        "ffmpeg", "-y", "-i", str(MAIN_MUSIC), "-ss", "85", "-t", "20",
        "-af", "volume=0.4,afade=t=out:st=0:d=20",
        "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
        str(music_tail_fadeout)
    ], check=True, capture_output=True)
    
    # Concatenate music
    music_concat_list = tmp_dir / "music_timeline.txt"
    with open(music_concat_list, "w", encoding="utf-8") as f:
        f.write(f"file '{music_intro}'\n")
        f.write(f"file '{music_overlap}'\n")
        f.write(f"file '{music_fadeout}'\n")
        if middle_silence_duration > 0.1:
            f.write(f"file '{music_silence}'\n")
        f.write(f"file '{music_fadein}'\n")
        f.write(f"file '{music_tail_full}'\n")
        f.write(f"file '{music_tail_fadeout}'\n")
    
    background_track = tmp_dir / "background_track.mp3"
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(music_concat_list),
        "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
        str(background_track)
    ], check=True, capture_output=True)
    
    # Delay voice to start at 5 seconds
    voice_delayed = tmp_dir / "voice_delayed.mp3"
    subprocess.run([
        "ffmpeg", "-y", "-i", str(voice_mix),
        "-af", "adelay=5000|5000",
        "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
        str(voice_delayed)
    ], check=True, capture_output=True)
    
    # Final mix: voice + music
    logging.info("Mixing voice and music...")
    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(voice_delayed),
        "-i", str(background_track),
        "-filter_complex",
        "[0:a]volume=1.0[a_voice];"
        "[1:a]volume=0.5[a_music];"  # Higher music volume for better presence
        "[a_voice][a_music]amix=inputs=2:duration=longest:dropout_transition=2:weights=2 1[mixed];"
        "[mixed]alimiter=level_in=1:level_out=0.95:limit=0.95[outfinal]",
        "-map", "[outfinal]",
        "-c:a", "libmp3lame",
        "-b:a", "192k",
        str(final_mp3)
    ], check=True, capture_output=True)
    
    logging.info("Podcast created successfully")
    
    # Cleanup music temp files
    for tmp_file in [music_intro, music_overlap, music_fadeout, music_fadein, music_tail_full, music_tail_fadeout, music_concat_list, background_track, voice_delayed]:
        if tmp_file.exists():
            os.remove(str(tmp_file))
    if middle_silence_duration > 0.1 and music_silence.exists():
        os.remove(str(music_silence))
    
    logging.info("BROADCAST-QUALITY PODCAST CREATED – PROFESSIONAL MUSIC TRANSITIONS APPLIED")

# ========================== 5. UPDATE RSS FEED ==========================
if not TEST_MODE and final_mp3.exists():
    try:
        # Get audio duration
        audio_duration = get_audio_duration(final_mp3)
        
        # Create episode title and description
        episode_title = f"Tesla Shorts Time Daily - Episode {episode_num} - {today_str}"
        
        # Extract a summary from the X thread (first 500 chars or first paragraph)
        episode_description = f"Daily Tesla news digest for {today_str}. TSLA price: ${price:.2f} {change_str}. "
        # Get first meaningful paragraph from x_thread
        lines = x_thread.split('\n')
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#') and not line.startswith('**') and len(line) > 50:
                episode_description += line[:400] + "..."
                break
        
        # RSS feed path (save in project root for easy access)
        rss_path = project_root / "podcast.rss"
        
        # MP3 filename relative to digests/digests/ (where files are saved)
        mp3_filename = final_mp3.name
        
        # Update RSS feed
        update_rss_feed(
            rss_path=rss_path,
            episode_num=episode_num,
            episode_title=episode_title,
            episode_description=episode_description,
            episode_date=datetime.date.today(),
            mp3_filename=mp3_filename,
            mp3_duration=audio_duration,
            mp3_path=final_mp3
        )
        logging.info(f"RSS feed updated with Episode {episode_num}")
    except Exception as e:
        logging.error(f"Failed to update RSS feed: {e}", exc_info=True)
        logging.warning("RSS feed update failed, but continuing...")

# Post everything to X in ONE SINGLE POST
if ENABLE_X_POSTING:
    try:
        x_path = digests_dir / f"Tesla_Shorts_Time_{datetime.date.today():%Y%m%d}.md"
        with open(x_path, "r", encoding="utf-8") as f:
            thread_text = f.read().strip()
        
        # Post as one single tweet
        tweet = x_client.create_tweet(text=thread_text)
        tweet_id = tweet.data['id']
        thread_url = f"https://x.com/planetterrian/status/{tweet_id}"
        logging.info(f"DIGEST POSTED → {thread_url}")
    except Exception as e:
        logging.error(f"X post failed: {e}")

# Cleanup temporary files
try:
    for file_path in audio_files:
        if os.path.exists(file_path):
            os.remove(file_path)
    cleanup_files = [voice_mix]
    if concat_file and concat_file.exists():
        cleanup_files.append(concat_file)
    for tmp_file in cleanup_files:
        if tmp_file and Path(tmp_file).exists():
            os.remove(str(tmp_file))
    logging.info("Temporary files cleaned up")
except Exception as e:
    logging.warning(f"Cleanup warning: {e}")

print("\n" + "="*80)
print("TESLA SHORTS TIME — FULLY AUTOMATED RUN COMPLETE")
print(f"X Thread → {x_path}")
print(f"Podcast → {final_mp3}")
print("="*80)
