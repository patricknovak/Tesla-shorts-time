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
import json
import xml.etree.ElementTree as ET
from feedgen.feed import FeedGenerator
from pathlib import Path
from dotenv import load_dotenv
import yfinance as yf
from openai import OpenAI
from difflib import SequenceMatcher
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont
import feedparser
from typing import List, Dict, Any
import tweepy

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

# Set to False to disable podcast generation and RSS feed updates
ENABLE_PODCAST = True

# Set to False to disable link validation (useful for testing if validation is necessary)
ENABLE_LINK_VALIDATION = False  # Set to False to skip link validation


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

def generate_episode_thumbnail(base_image_path, episode_num, date_str, output_path):
    img = Image.open(base_image_path)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 48)
    except IOError:
        font = ImageFont.load_default()
    draw.text((50, 50), f"Episode {episode_num}", font=font, fill=(255, 255, 255))
    draw.text((50, 100), date_str, font=font, fill=(255, 255, 255))
    img.save(output_path, "PNG")

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
    # NEWSAPI_KEY no longer required - using RSS feeds instead
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
# Get current date and time in PST
pst_tz = ZoneInfo("America/Los_Angeles")
now_pst = datetime.datetime.now(pst_tz)
today_str = now_pst.strftime("%B %d, %Y at %I:%M %p PST")   # November 19, 2025 at 02:30 PM PST
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
digests_dir = project_root / "digests"
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
# NEWSAPI_KEY no longer needed - using RSS feeds instead


# ========================== STEP 1: FETCH TESLA NEWS FROM RSS FEEDS ==========================
logging.info("Step 1: Fetching Tesla news from RSS feeds for the last 24 hours...")

def calculate_similarity(text1: str, text2: str) -> float:
    """Calculate similarity ratio between two texts (0.0 to 1.0)."""
    if not text1 or not text2:
        return 0.0
    # Normalize: lowercase, remove extra whitespace
    text1_norm = ' '.join(text1.lower().split())
    text2_norm = ' '.join(text2.lower().split())
    return SequenceMatcher(None, text1_norm, text2_norm).ratio()

def remove_similar_items(items, similarity_threshold=0.7, get_text_func=None):
    """
    Remove similar items from a list based on text similarity.
    
    Args:
        items: List of items to filter
        similarity_threshold: Similarity ratio above which items are considered duplicates (0.0-1.0)
        get_text_func: Function to extract text from item for comparison (default: uses 'title' or 'text' key)
    
    Returns:
        Filtered list with similar items removed (keeps first occurrence)
    """
    if not items:
        return items
    
    if get_text_func is None:
        # Default: try 'title', then 'text', then 'description'
        def get_text_func(item):
            if isinstance(item, dict):
                return item.get('title', '') or item.get('text', '') or item.get('description', '')
            return str(item)
    
    filtered = []
    for item in items:
        item_text = get_text_func(item)
        if not item_text:
            continue
        
        # Check similarity against already accepted items
        is_similar = False
        for accepted_item in filtered:
            accepted_text = get_text_func(accepted_item)
            similarity = calculate_similarity(item_text, accepted_text)
            if similarity >= similarity_threshold:
                is_similar = True
                logging.debug(f"Filtered similar item (similarity: {similarity:.2f}): {item_text[:50]}...")
                break
        
        if not is_similar:
            filtered.append(item)
    
    return filtered

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((requests.RequestException, requests.Timeout))
)
def fetch_tesla_news():
    """Fetch Tesla-related news from RSS feeds of Tesla news sites for the last 24 hours.
    Returns tuple: (filtered_articles, raw_articles) for saving raw data."""
    import feedparser
    
    # Tesla news site RSS feeds
    rss_feeds = [
        "https://whatsuptesla.com/feed",
        "https://www.thedrive.com/category/tesla-news/feed",
        "https://www.tesery.com/en-in/blogs/news.atom",
        "https://driveteslacanada.ca/feed/",
        "http://feeds.feedburner.com/teslanorth",
        "https://in.mashable.com/tesla.xml",
        "https://teslainvestor.blogspot.com/feeds/posts/default",
        "https://www.teslasiliconvalley.com/blog?format=rss",
        "https://www.teslarati.com/feed/",
        "https://www.notateslaapp.com/news/rss",
        "https://insideevs.com/rss/",
    ]
    
    # Calculate cutoff time (last 24 hours)
    cutoff_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
    
    all_articles = []
    raw_articles = []
    
    # Tesla-related keywords to filter articles
    tesla_keywords = [
        "tesla", "tsla", "model 3", "model y", "model s", "model x", 
        "cybertruck", "roadster", "semi", "robotaxi", "optimus",
        "fsd", "full self-driving", "autopilot", "supercharger",
        "gigafactory", "powerwall", "solar roof", "4680", "ai5"
    ]
    
    logging.info(f"Fetching Tesla news from {len(rss_feeds)} RSS feeds...")
    
    for feed_url in rss_feeds:
        # Initialize source_name before the try block
        source_name = "Unknown"
        try:
            # Parse RSS feed
            feed = feedparser.parse(feed_url)
            
            if feed.bozo and feed.bozo_exception:
                logging.warning(f"Failed to parse RSS feed {feed_url}: {feed.bozo_exception}")
                continue
            
            # Extract source name from feed (before processing entries)
            source_name = feed.feed.get("title", "Unknown")
            if "whatsuptesla" in feed_url.lower():
                source_name = "What's Up Tesla"
            elif "thedrive" in feed_url.lower():
                source_name = "The Drive"
            elif "tesery" in feed_url.lower():
                source_name = "Tesery"
            elif "driveteslacanada" in feed_url.lower() or "drivetesla" in feed_url.lower():
                source_name = "Drive Tesla Canada"
            elif "teslanorth" in feed_url.lower() or "feedburner" in feed_url.lower():
                source_name = "Tesla North"
            elif "mashable" in feed_url.lower():
                source_name = "Mashable"
            elif "teslainvestor" in feed_url.lower() or "blogspot" in feed_url.lower():
                source_name = "Tesla Investor"
            elif "teslasiliconvalley" in feed_url.lower():
                source_name = "Tesla Silicon Valley"
            elif "teslarati" in feed_url.lower():
                source_name = "Teslarati"
            elif "notateslaapp" in feed_url.lower():
                source_name = "Not a Tesla App"
            elif "insideevs" in feed_url.lower():
                source_name = "InsideEVs"
            
            feed_articles = []
            for entry in feed.entries:
                # Parse published date
                published_time = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    try:
                        published_time = datetime.datetime(*entry.published_parsed[:6], tzinfo=datetime.timezone.utc)
                    except (ValueError, TypeError):
                        pass
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    try:
                        published_time = datetime.datetime(*entry.updated_parsed[:6], tzinfo=datetime.timezone.utc)
                    except (ValueError, TypeError):
                        pass
                
                # Skip if older than 24 hours
                if published_time and published_time < cutoff_time:
                    continue
                
                # Get title and description
                title = entry.get("title", "").strip()
                description = entry.get("description", "").strip() or entry.get("summary", "").strip()
                link = entry.get("link", "").strip()
                
                if not title or not link:
                    continue
                
                # Check if article is Tesla-related
                title_desc_lower = (title + " " + description).lower()
                if not any(keyword in title_desc_lower for keyword in tesla_keywords):
                    continue
                
                # Skip stock quotes/price commentary
                if any(skip_term in title_desc_lower for skip_term in ["stock quote", "tradingview", "yahoo finance ticker", "price chart"]):
                    continue
                
                # Format article
                article = {
                    "title": title,
                    "description": description,
                    "url": link,
                    "source": source_name,
                    "publishedAt": published_time.isoformat() if published_time else datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "author": entry.get("author", "")
                }
                
                feed_articles.append(article)
                raw_articles.append(article)
            
            logging.info(f"Fetched {len(feed_articles)} articles from {source_name}")
            all_articles.extend(feed_articles)
            
        except Exception as e:
            # Don't reference source_name in exception handler to avoid scoping issues
            logging.warning(f"Failed to fetch RSS feed {feed_url}: {e}")
            continue
    
    logging.info(f"Fetched {len(all_articles)} total articles from RSS feeds")
    
    if not all_articles:
        logging.warning("No articles found from RSS feeds")
        return [], []
    
    # Remove similar/duplicate articles based on title similarity
    before_dedup = len(all_articles)
    formatted_articles = remove_similar_items(
        all_articles,
        similarity_threshold=0.75,  # 75% similarity = likely duplicate
        get_text_func=lambda x: f"{x.get('title', '')} {x.get('description', '')}"
    )
    after_dedup = len(formatted_articles)
    if before_dedup != after_dedup:
        logging.info(f"Removed {before_dedup - after_dedup} similar/duplicate news articles")
    
    # Sort by published date (newest first)
    formatted_articles.sort(key=lambda x: x.get("publishedAt", ""), reverse=True)
    
    logging.info(f"Filtered to {len(formatted_articles)} unique Tesla news articles")
    filtered_result = formatted_articles[:30]  # Return top 30 for selection
    return filtered_result, raw_articles

tesla_news, raw_news_articles = fetch_tesla_news()

# ========================== STEP 2: FETCH TOP X POSTS FROM X API ==========================
# Initialize variables at module level to ensure they're always defined
top_x_posts = []
raw_x_posts = []
import datetime
import logging
from typing import List, Dict, Any

TRUSTED_USERNAMES = [
    "elonmusk", "Tesla", "Tesla_AI", "cybertruck", "TeslaCharging", "teslaenergy",
    "OptimusTesla", "GigaTexas", "GigaBerlin", "SawyerMerritt"
]

def fetch_x_posts_nitter(usernames: List[str]) -> tuple[List[Dict], List[Dict]]:
    """Fetch X posts using Nitter scraping (Free fallback)."""
    try:
        from ntscraper import Nitter
        logging.info("Using Nitter scraper as fallback...")
    except ImportError:
        logging.warning("ntscraper not installed. Cannot use free Nitter scraping.")
        return [], []

    scraper = Nitter(log_level=1, skip_instance_check=False)
    all_posts = []
    
    # Limit to top accounts to save time and reduce failure chance
    priority_accounts = [u for u in usernames if u.lower() in ["elonmusk", "tesla", "sawyermerritt", "tesla_ai"]]
    if not priority_accounts:
        priority_accounts = usernames[:5]
    
    for username in priority_accounts:
        try:
            logging.info(f"Scraping tweets for @{username}...")
            tweets_data = scraper.get_tweets(username, mode='user', number=5)
            
            if not tweets_data or 'tweets' not in tweets_data:
                continue
                
            for tweet in tweets_data['tweets']:
                if tweet.get('is_pinned', False):
                    continue
                
                text = tweet.get('text', '')
                likes = tweet['stats'].get('likes', 0)
                retweets = tweet['stats'].get('retweets', 0)
                comments = tweet['stats'].get('comments', 0)
                
                score = (likes * 1.0) + (retweets * 3.0) + (comments * 1.5)
                if username.lower() == 'elonmusk':
                    score *= 3.0
                    
                all_posts.append({
                    "id": tweet['link'].split('/')[-1] if 'link' in tweet else '',
                    "text": text,
                    "username": username,
                    "name": tweet['user']['name'],
                    "url": tweet['link'],
                    "created_at": tweet['date'],
                    "likes": likes,
                    "retweets": retweets,
                    "replies": comments,
                    "final_score": score,
                    "is_elon_or_sawyer_repost": False,
                    "hours_old": 0
                })
        except Exception as e:
            logging.warning(f"Failed to scrape {username}: {e}")
            continue

    all_posts.sort(key=lambda x: x['final_score'], reverse=True)
    return all_posts[:25], all_posts

def fetch_top_x_posts_from_trusted_accounts() -> tuple[List[Dict], List[Dict]]:
    """
    100% free, maximum variety & quality.
    Captures:
    - All official Tesla product/regional accounts
    - Elon + Sawyer's reposts & quote tweets (intelligently)
    - Only high-signal community voices
    """
    logging.info("Fetching Tesla posts from 30+ official + trusted accounts (incl. reposts/quotes)")

    end_time = datetime.datetime.now(datetime.timezone.utc)
    start_time = end_time - datetime.timedelta(hours=48)  # 48h = never miss weekend news

    all_posts = []
    raw_posts = []

    # 1. Original posts from trusted accounts
    from_part = " OR ".join([f"from:{u}" for u in TRUSTED_USERNAMES if u.isalnum()])
    repost_part = "retweets_of:elonmusk OR retweets_of:SawyerMerritt"
    query = f"({from_part}) OR ({repost_part}) -is:reply lang:en"

    try:
        import tweepy
        
        # Initialize X API client
        x_client = tweepy.Client(
            bearer_token=os.getenv("X_BEARER_TOKEN"),
            wait_on_rate_limit=True
        )
        
        logging.info(f"Searching X with query: {query[:100]}...")
        
        # Fetch tweets
        response = x_client.search_recent_tweets(
            query=query,
            max_results=100,  # Max allowed per request
            start_time=start_time,
            tweet_fields=['created_at', 'public_metrics', 'author_id', 'text', 'referenced_tweets'],
            user_fields=['username', 'name'],
            expansions=['author_id', 'referenced_tweets.id']
        )
        
        if not response.data:
            logging.warning("No tweets found matching criteria.")
            return [], []
            
        # Create user lookup map
        users = {u.id: u for u in response.includes['users']} if response.includes and 'users' in response.includes else {}
        
        for post in response.data:
            metrics = post.public_metrics or {}
            engagement = (
                metrics.get('like_count', 0) * 1.0 +
                metrics.get('retweet_count', 0) * 3.0 +
                metrics.get('reply_count', 0) * 1.2 +
                metrics.get('quote_count', 0) * 2.5
            )

            # Fix: post.created_at is already a datetime object in tweepy
            created_at = post.created_at
            
            hours_old = (end_time - created_at).total_seconds() / 3600
            recency = 2.5 if hours_old <= 8 else (1.8 if hours_old <= 24 else 1.0)

            # Get author info from includes
            author_id = post.author_id
            author_data = users.get(author_id)
            author_username = author_data.username if author_data else "unknown"
            author_name = author_data.name if author_data else "Unknown"
            
            author_lower = author_username.lower()
            
            boost = 4.0 if author_lower == "elonmusk" else \
                    3.0 if author_lower in ["tesla", "tesla_ai", "cybertruck", "optimustelsa"] else \
                    2.5 if author_lower == "sawyermerritt" else 1.5

            # Bonus if it's a repost/quote from Elon or Sawyer
            # referenced_tweets is a list of objects in tweepy
            refs = post.referenced_tweets or []
            is_signal_repost = False
            # We can't easily check the author of referenced tweets without more complex lookups
            # For now, check if the query targeted reposts implies it
            
            # Simple check if it's a retweet (though we filtered out retweets in query? No, we kept them for specific accounts maybe? 
            # The query has "retweets_of:..." but usually search_recent_tweets excludes retweets by default or we treat them as tweets.
            # Actually, standard search includes retweets unless -is:retweet.
            # The query has "-is:reply" but NOT "-is:retweet".
            
            if is_signal_repost:
                boost *= 1.8

            score = engagement * recency * boost

            all_posts.append({
                "id": str(post.id),
                "text": post.text,
                "username": author_username,
                "name": author_name,
                "url": f"https://x.com/{author_username}/status/{post.id}",
                "created_at": created_at.isoformat(),
                "likes": metrics.get('like_count', 0),
                "retweets": metrics.get('retweet_count', 0),
                "replies": metrics.get('reply_count', 0),
                "final_score": score,
                "is_elon_or_sawyer_repost": is_signal_repost,
                "hours_old": round(hours_old, 1)
            })

        logging.info(f"Fetched & scored {len(all_posts)} posts from Tesla ecosystem")

    except Exception as e:
        logging.warning(f"Search failed: {e}")
        logging.info("Attempting fallback to Nitter scraping...")
        return fetch_x_posts_nitter(TRUSTED_USERNAMES)

    if not all_posts:
        return [], []

    # 2. Free fallback using Nitter (if authenticated fetch failed or returned few results)
    if len(all_posts) < 8:
        logging.info("Few X posts found via API. Attempting fallback to Nitter scraping for more posts...")
        nitter_top, nitter_raw = fetch_x_posts_nitter(TRUSTED_USERNAMES)
        
        # Merge results (avoiding duplicates by ID)
        existing_ids = {p['id'] for p in all_posts}
        for post in nitter_raw:
            if post['id'] not in existing_ids:
                all_posts.append(post)
                
    # Sort + dedupe
    all_posts.sort(key=lambda x: x['final_score'], reverse=True)
    seen = set()
    unique = [p for p in all_posts if p['id'] not in seen and (seen.add(p['id']) or True)]

    top_25 = unique[:25]
    # Populate raw_posts with all fetched posts (before filtering to top 25)
    raw_posts = all_posts.copy()

    logging.info(f"Returning {len(top_25)} best Tesla posts "
                 f"(Elon/Sawyer reposts: {sum(1 for p in top_25 if p['is_elon_or_sawyer_repost'])})")

    return top_25, raw_posts

# Call the function to fetch X posts
logging.info("Step 2: Fetching top X posts from trusted accounts...")
try:
    top_x_posts, raw_x_posts = fetch_top_x_posts_from_trusted_accounts()
    if len(top_x_posts) < 8:
        logging.warning(f"⚠️  Only {len(top_x_posts)} X posts were fetched (minimum 8 recommended). Continuing anyway - Grok will skip X posts section if needed.")
except Exception as e:
    logging.error(f"Failed to fetch X posts: {e}")
    logging.warning("Continuing without X posts data")
    top_x_posts = []
    raw_x_posts = []

# ========================== SAVE RAW DATA AND GENERATE HTML PAGE ==========================
logging.info("Saving raw data and generating HTML page for raw news and X posts...")

def save_raw_data_and_generate_html(raw_news, raw_x_posts_data, output_dir):
    """Save raw data to JSON and generate HTML page for GitHub Pages."""
    today = datetime.date.today()
    date_str = today.strftime("%Y-%m-%d")
    
    # Prepare raw data structure
    raw_data = {
        "date": date_str,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "rss_feeds": {
            "total_articles": len(raw_news),
            "articles": raw_news
        },
        "x_api": {
            "total_posts": len(raw_x_posts_data),
            "posts": raw_x_posts_data
        }
    }
    
    # Save JSON file
    json_path = output_dir / f"raw_data_{date_str}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, indent=2, ensure_ascii=False)
    logging.info(f"Raw data saved to {json_path}")
    
    # Generate HTML page
    html_content = generate_raw_data_html(raw_data, output_dir)
    
    # Save date-specific HTML
    html_path = output_dir / f"raw_data_{date_str}.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    logging.info(f"HTML page generated at {html_path}")
    
    # Also update index.html to point to latest
    index_path = output_dir / "raw_data_index.html"
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    logging.info(f"Index HTML updated at {index_path}")
    
    return json_path, html_path

def generate_raw_data_html(raw_data, output_dir):
    """Generate HTML page displaying raw news and X posts."""
    date_str = raw_data["date"]
    formatted_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %d, %Y")
    
    # Find all existing JSON files to build archive
    json_files = sorted(output_dir.glob("raw_data_*.json"), reverse=True)
    archive_dates = []
    for json_file in json_files[:30]:  # Last 30 days
        date_part = json_file.stem.replace("raw_data_", "")
        try:
            archive_date = datetime.datetime.strptime(date_part, "%Y-%m-%d")
            archive_dates.append({
                "date": date_part,
                "formatted": archive_date.strftime("%B %d, %Y")
            })
        except:
            pass
    
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Raw Tesla News & X Posts - {formatted_date} | Tesla Shorts Time</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            line-height: 1.6;
            color: #333;
            background: #f5f5f5;
            padding: 20px;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #e31937;
            margin-bottom: 10px;
            font-size: 2.5em;
        }}
        .subtitle {{
            color: #666;
            margin-bottom: 30px;
            font-size: 1.1em;
        }}
        .archive {{
            background: #f9f9f9;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 30px;
        }}
        .archive h2 {{
            font-size: 1.2em;
            margin-bottom: 10px;
            color: #333;
        }}
        .archive-links {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
        }}
        .archive-link {{
            padding: 5px 12px;
            background: #e31937;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            font-size: 0.9em;
        }}
        .archive-link:hover {{
            background: #c0152d;
        }}
        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }}
        .stat-card {{
            background: linear-gradient(135deg, #e31937 0%, #c0152d 100%);
            color: white;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
        }}
        .stat-number {{
            font-size: 2.5em;
            font-weight: bold;
            margin-bottom: 5px;
        }}
        .stat-label {{
            font-size: 0.9em;
            opacity: 0.9;
        }}
        .section {{
            margin-bottom: 40px;
        }}
        .section h2 {{
            color: #e31937;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #e31937;
        }}
        .article, .post {{
            background: #f9f9f9;
            padding: 20px;
            margin-bottom: 15px;
            border-radius: 5px;
            border-left: 4px solid #e31937;
        }}
        .article:hover, .post:hover {{
            background: #f0f0f0;
            transform: translateX(5px);
            transition: all 0.2s;
        }}
        .article-title, .post-text {{
            font-weight: bold;
            font-size: 1.1em;
            margin-bottom: 10px;
            color: #333;
        }}
        .article-meta, .post-meta {{
            color: #666;
            font-size: 0.9em;
            margin-bottom: 10px;
        }}
        .article-link, .post-link {{
            color: #e31937;
            text-decoration: none;
            font-weight: bold;
        }}
        .article-link:hover, .post-link:hover {{
            text-decoration: underline;
        }}
        .engagement {{
            display: inline-block;
            background: #e31937;
            color: white;
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 0.85em;
            margin-left: 10px;
        }}
        .description {{
            color: #555;
            margin-top: 10px;
            line-height: 1.5;
        }}
        @media (max-width: 768px) {{
            .container {{
                padding: 15px;
            }}
            h1 {{
                font-size: 1.8em;
            }}
            .stats {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🚗⚡ Tesla Shorts Time - Raw Data</h1>
        <p class="subtitle">Daily Raw News & X Posts Archive - {formatted_date}</p>
        
        <div class="archive">
            <h2>📅 Archive</h2>
            <div class="archive-links">
                <a href="raw_data_index.html" class="archive-link">Today</a>
"""
    
    # Add archive links
    for archive_date in archive_dates:
        if archive_date["date"] != date_str:
            html_content += f'                <a href="raw_data_{archive_date["date"]}.html" class="archive-link">{archive_date["formatted"]}</a>\n'
    
    html_content += """            </div>
        </div>
        
        <div class="stats">
            <div class="stat-card">
                <div class="stat-number">""" + str(raw_data["rss_feeds"]["total_articles"]) + """</div>
                <div class="stat-label">News Articles</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">""" + str(raw_data["x_api"]["total_posts"]) + """</div>
                <div class="stat-label">X Posts</div>
            </div>
        </div>
        
        <div class="section">
            <h2>📰 RSS Feed Articles (Raw)</h2>
"""
    
    # Add news articles
    for i, article in enumerate(raw_data["rss_feeds"]["articles"], 1):
        title = html.escape(str(article.get("title") or "No title"))
        description = html.escape(str(article.get("description") or "No description"))
        url = html.escape(str(article.get("url") or "#"))
        source = html.escape(article.get("source", {}).get("name", "Unknown") if isinstance(article.get("source"), dict) else str(article.get("source", "Unknown")))
        published = article.get("publishedAt", "Unknown")
        author = html.escape(str(article.get("author") or "Unknown"))
        
        html_content += f"""            <div class="article">
                <div class="article-title">{i}. {title}</div>
                <div class="article-meta">
                    Source: {source} | Author: {author} | Published: {published}
                </div>
                <div class="description">{description}</div>
                <a href="{url}" target="_blank" class="article-link">Read Article →</a>
            </div>
"""
    
    html_content += """        </div>
        
        <div class="section">
            <h2>🐦 X Posts (Raw)</h2>
"""
    
    # Add X posts
    for i, post in enumerate(raw_data["x_api"]["posts"], 1):
        text = html.escape(str(post.get("text") or "No text"))
        username = html.escape(str(post.get("username") or "unknown"))
        name = html.escape(str(post.get("name") or "Unknown"))
        url = html.escape(str(post.get("url") or "#"))
        created_at = post.get("created_at", "Unknown")
        engagement = post.get("engagement", 0)
        likes = post.get("likes", 0)
        retweets = post.get("retweets", 0)
        replies = post.get("reply_count", 0)
        
        html_content += f"""            <div class="post">
                <div class="post-text">{i}. {text}</div>
                <div class="post-meta">
                    @{username} ({name}) | {created_at} | 
                    ❤️ {likes} | 🔄 {retweets} | 💬 {replies}
                    <span class="engagement">Engagement: {engagement:.0f}</span>
                </div>
                <a href="{url}" target="_blank" class="post-link">View Post →</a>
            </div>
"""
    
    html_content += """        </div>
        
        <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; text-align: center; color: #666;">
            <p>Generated automatically by Tesla Shorts Time Daily</p>
            <p><a href="https://github.com/patricknovak/Tesla-shorts-time" style="color: #e31937;">View on GitHub</a></p>
        </div>
    </div>
</body>
</html>"""
    
    return html_content

# Save raw data and generate HTML
raw_json_path, raw_html_path = save_raw_data_and_generate_html(
    raw_news_articles, 
    raw_x_posts, 
    digests_dir
)

# ========================== STEP 3: GENERATE X THREAD WITH GROK ==========================
logging.info("Step 3: Generating Tesla Shorts Time digest with Grok using pre-fetched news and X posts...")

# Format news articles for the prompt
news_section = ""
if tesla_news:
    news_section = "## PRE-FETCHED NEWS ARTICLES (from RSS feeds - last 24 hours):\n\n"
    for i, article in enumerate(tesla_news[:20], 1):  # Top 20 articles
        news_section += f"{i}. **{article['title']}**\n"
        news_section += f"   Source: {article['source']}\n"
        news_section += f"   Published: {article['publishedAt']}\n"
        if article.get('description'):
            news_section += f"   Description: {article['description'][:200]}...\n"
        news_section += f"   URL: {article['url']}\n\n"
else:
    news_section = "## PRE-FETCHED NEWS ARTICLES: None available (you may need to search for news)\n\n"

# Format X posts for the prompt
x_posts_section = ""
if top_x_posts:
    # Include all available posts (up to 20) to give Grok more options
    num_posts_to_include = min(len(top_x_posts), 20)
    x_posts_section = f"## PRE-FETCHED X POSTS (from X API - last 24 hours, ranked by recency + engagement):\n\n"
    x_posts_section += f"**IMPORTANT: You have {len(top_x_posts)} pre-fetched X posts available. Select UP TO 10 from these pre-fetched posts. If you have fewer than 10, output only what exists. NEVER invent, make up, or hallucinate X post URLs - only use the exact URLs provided below. If you cannot find enough posts, output fewer items rather than inventing URLs.**\n\n"
    for i, post in enumerate(top_x_posts[:num_posts_to_include], 1):  # Include up to 20 posts
        x_posts_section += f"{i}. **@{post['username']} ({post['name']})**\n"
        x_posts_section += f"   Likes: {post['likes']}, RTs: {post['retweets']}\n"
        x_posts_section += f"   Posted: {post['created_at']}\n"
        x_posts_section += f"   Text: {post['text'][:300]}...\n"
        x_posts_section += f"   URL: {post['url']}\n\n"
else:
    # This should never happen due to the check above, but handle gracefully
    x_posts_section = "## PRE-FETCHED X POSTS: None available\n\n"


X_PROMPT = f"""
# Tesla Shorts Time - DAILY EDITION
**Date:** {today_str}
**REAL-TIME TSLA price:** ${price:.2f} {change_str}

{news_section}

{x_posts_section}

You are an elite Tesla news curator producing the daily "Tesla Shorts Time" newsletter. Use ONLY the pre-fetched news and X posts above. Do NOT hallucinate, invent, or search for new content/URLs—stick to exact provided links. NEVER invent X post URLs - if you don't have enough pre-fetched posts, output fewer items (e.g., if only 8 X posts, number them 1-8). If you have zero pre-fetched X posts, completely remove the "Top X Posts" section from your output. Prioritize diversity: No duplicates/similar stories (≥70% overlap in angle/content); max 3 from one source/account.

### MANDATORY SELECTION & COUNTS
- **News**: Select EXACTLY 10 unique articles (if <10 available, use all). Prioritize high-quality sources; each must cover a DIFFERENT Tesla story/angle.
- **X Posts**: Select UP TO 10 unique posts from pre-fetched list. If fewer than 10 are available, output only what exists. NEVER invent, make up, or hallucinate X post URLs - only use exact URLs from the pre-fetched list. If you cannot find enough posts, output fewer items (e.g., if only 8 posts, number them 1-8). Each must cover a DIFFERENT angle; max 3 per username.
- **CRITICAL URL RULE**: NEVER invent X post URLs. If you don't have enough pre-fetched posts, output fewer items rather than making up URLs. All URLs must be exact matches from the pre-fetched list above for the news and X posts.
- **Diversity Check**: Before finalizing, verify no similar content for the news and X posts; replace if needed from pre-fetched pool for the news and X posts.

### FORMATTING (EXACT—USE MARKDOWN AS SHOWN)
# Tesla Shorts Time
**Date:** {today_str}
**REAL-TIME TSLA price:** ${price:.2f} {change_str}
🎙️ Tesla Shorts Time Daily Podcast Link: https://podcasts.apple.com/us/podcast/tesla-shorts-time/id1855142939

━━━━━━━━━━━━━━━━━━━━
### Top 10 News Items
1. **Title (One Line): DD Month, YYYY, HH:MM AM/PM PST, Source Name**  
   2–4 sentences: Start with what happened, then why it matters for Tesla's future/stock. End with: Source: [EXACT URL FROM PRE-FETCHED—no mods]
2. [Repeat format for 3-10; if <10 items, stop at available count, add a blank line after each item and the last item]

━━━━━━━━━━━━━━━━━━━━
### Top X Posts
1. **Catchy Title: DD Month, YYYY, HH:MM AM/PM PST**  
   2–4 sentences: Explain post & significance (pro-Tesla angle). End with: Post: [EXACT URL FROM PRE-FETCHED—https://x.com/username/status/ID]
2. [Repeat for remaining posts; use only pre-fetched posts, never invent URLs. If fewer than 10 available, output only what exists (e.g., if 8 posts, number 1-8), add a blank line after each item and the last item]

━━━━━━━━━━━━━━━━━━━━
## Short Spot
One bearish item from pre-fetched (news or X post) that's negative for Tesla/stock.  
**Catchy Title: DD Month, YYYY, HH:MM AM/PM PST, @username/Source**  
2–4 sentences explaining it & why it's temporary/overblown (frame optimistically). End with: Source/Post: [EXACT URL]

━━━━━━━━━━━━━━━━━━━━
### Short Squeeze
Dedicated paragraph on short-seller pain:
Add specific failed bear predictions (2020–2025, with references and links from past).

━━━━━━━━━━━━━━━━━━━━
### Daily Challenge
One short, inspiring challenge tied to Tesla/Elon themes (curiosity, first principles, perseverance). End with: "Share your progress with us @teslashortstime!"

━━━━━━━━━━━━━━━━━━━━
**Inspiration Quote:** "Exact quote" – Author, [Source Link] (fresh, no repeats from last 7 days)

[2-3 sentence uplifting sign-off on Tesla's mission + invite to DM @teslashortstime with feedback.]

(Add blank line after sign-off.)

### TONE & STYLE
- Inspirational, pro-Tesla, optimistic, energetic.
- Timestamps: Accurate PST/PDT (convert from pre-fetched).
- No stock-quote pages/pure price commentary as "news."

### FINAL VALIDATION CHECKLIST (DO THIS BEFORE OUTPUT)
- ✅ Exactly 10 news items (or all if <10): Numbered 1-10, unique stories.
- ✅ Exactly 10 X posts (or all if <10): Numbered 1-10, unique angles.
- ✅ Podcast link: Full URL as shown.
- ✅ Lists: "1. " format (number, period, space)—no bullets.
- ✅ Separators: "━━━━━━━━━━━━━━━━━━━━" before each major section.
- ✅ No duplicates: All items unique (review pairwise).
- ✅ All sections included: Short Spot, Short Squeeze, Daily Challenge, Quote, sign-off.
- ✅ URLs: Exact from pre-fetched; valid format; no inventions.
- If any fail, adjust selections and re-check.

Output today's edition exactly as formatted.
"""

logging.info("Generating X thread with Grok using pre-fetched content (this may take 1-2 minutes)...")

# CRITICAL: Always disable web search to prevent hallucinations and ensure we only use pre-fetched URLs
enable_web_search = False
search_params = {"mode": "off"}
logging.info("✅ Web search disabled - using only pre-fetched content to avoid hallucinations")

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((Exception,))
)
def generate_digest_with_grok():
    """Generate digest with retry logic"""
    response = client.chat.completions.create(
        model="grok-4",
        messages=[{"role": "user", "content": X_PROMPT}],
        temperature=0.7,
        max_tokens=4000,
        extra_body={"search_parameters": search_params}
    )
    return response

try:
    response = generate_digest_with_grok()
    x_thread = response.choices[0].message.content.strip()
    
    # Log token usage and cost
    if hasattr(response, 'usage') and response.usage:
        usage = response.usage
        logging.info(f"Grok API - Tokens used: {usage.total_tokens} (prompt: {usage.prompt_tokens}, completion: {usage.completion_tokens})")
        # Estimate cost (Grok pricing may vary, using approximate $0.01 per 1M tokens)
        estimated_cost = (usage.total_tokens / 1000000) * 0.01
        logging.info(f"Estimated cost: ${estimated_cost:.4f}")
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

# Validate counts - check if we have exactly 10 news and 10 X posts
import re
news_count = len(re.findall(r'^[1-9]|10[️⃣\.]\s+\*\*', x_thread, re.MULTILINE))
x_posts_count = len(re.findall(r'^[1-9]|10[️⃣\.]\s+\*\*', x_thread, re.MULTILINE))
# Also check for numbered lists without emojis
if news_count < 10:
    news_count = len(re.findall(r'^([1-9]|10)\.\s+\*\*', x_thread, re.MULTILINE))
if x_posts_count < 10:
    x_posts_count = len(re.findall(r'^([1-9]|10)\.\s+\*\*', x_thread, re.MULTILINE))

if news_count != 10:
    logging.warning(f"⚠️  WARNING: Found {news_count} news items instead of 10. Grok may not have followed instructions.")
if x_posts_count != 10:
    logging.warning(f"⚠️  WARNING: Found {x_posts_count} X posts instead of 10. Grok may not have followed instructions.")

# ========================== VALIDATE AND FIX LINKS ==========================
# Only run if enabled (can be disabled for testing)
if ENABLE_LINK_VALIDATION:
    logging.info("Validating and fixing links in the generated digest...")
else:
    logging.info("⚠️  Link validation is DISABLED - skipping validation step")

def validate_x_post_url(url: str) -> bool:
    """
    Validate that an X post URL is in the correct format and appears to be real.
    Format: https://x.com/username/status/ID or https://twitter.com/username/status/ID
    Returns True if valid, False otherwise.
    """
    import re
    
    # Clean URL - remove markdown link syntax if present
    url_clean = url.rstrip('.,;:!?)').strip()
    # Remove markdown link syntax like ](url or ](https://... if it got included
    url_clean = re.sub(r'\]\(.*$', '', url_clean).strip()
    # Remove any trailing brackets or parentheses that might be from markdown
    url_clean = url_clean.rstrip('])').strip()
    
    # Check format: https://x.com/username/status/ID or https://twitter.com/username/status/ID
    x_pattern = r'https?://(x\.com|twitter\.com)/([a-zA-Z0-9_]+)/status/(\d+)'
    match = re.match(x_pattern, url_clean)
    
    if not match:
        return False
    
    # Extract components
    domain, username, status_id = match.groups()
    
    # Validate username (X usernames are 1-15 alphanumeric/underscore)
    if not re.match(r'^[a-zA-Z0-9_]{1,15}$', username):
        return False
    
    # Validate status ID (should be numeric, typically 19-20 digits)
    if not re.match(r'^\d{15,20}$', status_id):
        return False
    
    # Check for suspicious patterns - real X status IDs are usually not round numbers
    # Status IDs ending in many zeros are likely fake
    if status_id.endswith('0000000000') or status_id.endswith('000000000'):
        logging.warning(f"⚠️  Suspicious X post URL with round number status ID: {url_clean}")
        return False
    
    return True

def validate_and_fix_links(digest_text: str, news_articles: list, x_posts: list) -> str:
    """
    Validate all URLs in the digest and remove invalid ones.
    CRITICAL: Only accepts URLs from pre-fetched data. All other URLs are removed.
    Returns the corrected digest text with invalid URLs removed.
    """
    import re
    
    # We always require pre-fetched X posts (minimum 8), so this should always be True
    has_prefetched_x_posts = len(x_posts) > 0
    
    # Create URL mapping from pre-fetched data
    news_url_map = {}
    for article in news_articles:
        title_key = article.get('title', '').lower().strip()[:50]  # First 50 chars of title
        news_url_map[title_key] = article.get('url', '')
        # Also map by source name
        source_key = article.get('source', '').lower().strip()
        if source_key:
            news_url_map[source_key] = article.get('url', '')
    
    x_url_map = {}
    for post in x_posts:
        username_key = post.get('username', '').lower().strip()
        x_url_map[username_key] = post.get('url', '')
        # Also map by post text snippet
        text_snippet = post.get('text', '').lower().strip()[:50]
        if text_snippet:
            x_url_map[text_snippet] = post.get('url', '')
    
    # Find all URLs in the digest
    # Also handle markdown link syntax like [text](url)
    url_pattern = r'https?://[^\s\)\]]+'
    urls_found = re.findall(url_pattern, digest_text)
    
    # Also find markdown links and extract the URL part
    markdown_link_pattern = r'\[([^\]]+)\]\((https?://[^\s\)]+)\)'
    markdown_links = re.findall(markdown_link_pattern, digest_text)
    for text, url in markdown_links:
        if url not in urls_found:
            urls_found.append(url)
    
    # Track issues
    invalid_urls = []
    removed_count = 0
    
    # Check each URL
    for url in urls_found:
        url_clean = url.rstrip('.,;:!?)')
        
        # Skip known good URLs
        if any(skip in url_clean for skip in ['podcasts.apple.com', 'teslashortstime.com', 'x.com/teslashortstime']):
            continue
        
        # Check if URL is in pre-fetched data
        is_valid = False
        
        # Check news articles
        for article in news_articles:
            if url_clean == article.get('url', ''):
                is_valid = True
                break
        
        # Check X posts - we always require pre-fetched ones (minimum 8)
        if not is_valid:
            for post in x_posts:
                if url_clean == post.get('url', ''):
                    is_valid = True
                    break
        
        # CRITICAL: Only accept URLs from pre-fetched data. Reject everything else.
        # Since we always require at least 8 pre-fetched X posts, we should never reach here
        # for X post URLs, but if we do, reject them.
        if not is_valid:
            if 'x.com' in url_clean or 'twitter.com' in url_clean:
                logging.warning(f"❌ X post URL not found in pre-fetched data - removing: {url_clean}")
            else:
                logging.warning(f"❌ URL not found in pre-fetched data - removing: {url_clean}")
        
        # If still not valid, mark for removal
        if not is_valid:
            invalid_urls.append(url_clean)
            # Remove the invalid URL from the digest
            # Remove URL and any trailing punctuation
            url_pattern_escaped = re.escape(url_clean)
            # Remove URL with optional trailing punctuation
            digest_text = re.sub(url_pattern_escaped + r'[.,;:!?)]*', '[URL REMOVED - INVALID]', digest_text)
            removed_count += 1
    
    if invalid_urls:
        logging.warning(f"⚠️  Found and removed {removed_count} invalid URLs from digest")
        logging.warning(f"Invalid URLs removed: {invalid_urls[:10]}...")  # Log first 10
        
        # Count X post URLs in the digest to check if we removed too many
        x_url_count = len([url for url in invalid_urls if 'x.com' in url or 'twitter.com' in url])
        if x_url_count > 5:
            logging.error(f"❌ WARNING: Removed {x_url_count} invalid X post URLs. This suggests hallucinations. The digest may have fewer X posts than expected.")
    else:
        logging.info("✅ All URLs validated successfully")
    
    return digest_text

# Validate links (only if enabled)
if ENABLE_LINK_VALIDATION:
    x_thread = validate_and_fix_links(x_thread, tesla_news, top_x_posts)
    logging.info("✅ Link validation completed")
else:
    logging.info("⚠️  Link validation skipped (ENABLE_LINK_VALIDATION = False)")

# ========================== STEP 4: FORMAT DIGEST FOR BEAUTIFUL X POST ==========================
logging.info("Step 4: Formatting digest for beautiful X post...")

def format_digest_for_x(digest: str) -> str:
    """
    Format the digest beautifully for a long X post with emojis, proper spacing, and visual appeal.
    X supports up to 25,000 characters for long posts.
    """
    import re
    
    formatted = digest
    
    # Add emoji to main header (only if it's the first line)
    formatted = re.sub(r'^# Tesla Shorts Time', '🚗⚡ **Tesla Shorts Time**', formatted, flags=re.MULTILINE)
    
    # Format date line with emoji
    formatted = re.sub(r'\*\*Date:\*\*', '📅 **Date:**', formatted)
    
    # Format price line with emoji
    formatted = re.sub(r'\*\*REAL-TIME TSLA price:\*\*', '💰 **REAL-TIME TSLA price:**', formatted)
    
    # Ensure podcast link is always present with full URL (add it if missing or incomplete)
    podcast_url = 'https://podcasts.apple.com/us/podcast/tesla-shorts-time/id1855142939'
    podcast_link_md = f'🎙️ **Tesla Shorts Time Daily Podcast Link:** {podcast_url}'
    
    # Check if the full URL is present (not just the text)
    if podcast_url not in formatted:
        # If podcast link missing, force add it at the top after price line
        # Match lines that mention podcast but don't contain the full URL
        lines = formatted.split('\n')
        cleaned_lines = []
        for line in lines:
            # If line mentions podcast but doesn't have the full URL, skip it
            if ('podcast' in line.lower() or '🎙️' in line) and podcast_url not in line:
                continue
            cleaned_lines.append(line)
        formatted = '\n'.join(cleaned_lines)
        
        # Add after the header/price block
        # Look for the last line of the header block (usually price or date)
        header_end_pos = 0
        lines = formatted.split('\n')
        for i, line in enumerate(lines[:10]):
            if line.strip() and (line.startswith('💰') or line.startswith('📅') or line.startswith('**') or line.startswith('#')):
                header_end_pos = i
        
        # Insert after the header block
        lines.insert(header_end_pos + 1, '')
        lines.insert(header_end_pos + 2, podcast_link_md)
        lines.insert(header_end_pos + 3, '')
        formatted = '\n'.join(lines)
    else:
        # URL is present, ensure it has the emoji prefix
        formatted = re.sub(
            r'(?<!🎙️ )(?<!\*\*)Tesla Shorts Time Daily Podcast Link:\s*' + re.escape(podcast_url),
            podcast_link_md,
            formatted,
            flags=re.IGNORECASE
        )
    
    # Format section headers with emojis (preserve existing markdown)
    formatted = re.sub(r'^### Top 10 News Items', '📰 **Top 10 News Items**', formatted, flags=re.MULTILINE)
    formatted = re.sub(r'^### Top 10 X Posts', '🐦 **Top 10 X Posts**', formatted, flags=re.MULTILINE)
    formatted = re.sub(r'^## Short Spot', '📉 **Short Spot**', formatted, flags=re.MULTILINE)
    formatted = re.sub(r'^### Short Squeeze', '📈 **Short Squeeze**', formatted, flags=re.MULTILINE)
    formatted = re.sub(r'^### Daily Challenge', '💪 **Daily Challenge**', formatted, flags=re.MULTILINE)
    
    # Add emoji to Inspiration Quote
    formatted = re.sub(r'\*\*Inspiration Quote:\*\*', '✨ **Inspiration Quote:**', formatted)
    
    # Add separator lines before major sections
    separator = '\n\n━━━━━━━━━━━━━━━━━━━━\n\n'
    
    # First, remove any existing separators to avoid duplicates
    formatted = re.sub(r'\n\n━━━━━━━━━━━━━━━━━━━━\n\n+', '\n\n', formatted)
    
    # Add separator before Top 10 News Items (check multiple patterns)
    formatted = re.sub(r'(\n\n?)(📰 \*\*Top 10 News Items\*\*)', separator + r'\2', formatted)
    formatted = re.sub(r'(\n\n?)(### Top 10 News Items)', separator + r'\2', formatted)
    # Also match after podcast link
    formatted = re.sub(r'(Podcast Link:.*?\n)(📰|\*\*Top 10 News|### Top 10 News)', separator + r'\2', formatted, flags=re.DOTALL)
    
    # Add separator before Top 10 X Posts
    formatted = re.sub(r'(\n\n?)(🐦 \*\*Top 10 X Posts\*\*)', separator + r'\2', formatted)
    formatted = re.sub(r'(\n\n?)(### Top 10 X Posts)', separator + r'\2', formatted)
    # Also match after last news item (10.)
    formatted = re.sub(r'(10[️⃣\.]\s+.*?\n)(🐦|\*\*Top 10 X Posts|### Top 10 X Posts)', separator + r'\2', formatted, flags=re.DOTALL)
    
    # Add separator before Short Spot
    formatted = re.sub(r'(\n\n?)(📉 \*\*Short Spot\*\*)', separator + r'\2', formatted)
    formatted = re.sub(r'(\n\n?)(## Short Spot)', separator + r'\2', formatted)
    # Also match after last X post (10.)
    formatted = re.sub(r'(10[️⃣\.]\s+.*?\n)(📉|\*\*Short Spot|## Short Spot)', separator + r'\2', formatted, flags=re.DOTALL)
    
    # Add separator before Short Squeeze
    formatted = re.sub(r'(\n\n?)(📈 \*\*Short Squeeze\*\*)', separator + r'\2', formatted)
    formatted = re.sub(r'(\n\n?)(### Short Squeeze)', separator + r'\2', formatted)
    
    # Add separator before Daily Challenge
    formatted = re.sub(r'(\n\n?)(💪 \*\*Daily Challenge\*\*)', separator + r'\2', formatted)
    formatted = re.sub(r'(\n\n?)(### Daily Challenge)', separator + r'\2', formatted)
    
    # Add separator before Inspiration Quote
    formatted = re.sub(r'(\n\n?)(✨ \*\*Inspiration Quote:\*\*)', separator + r'\2', formatted)
    formatted = re.sub(r'(\n\n?)(\*\*Inspiration Quote:\*\*)', separator + r'\2', formatted)
    
    # Add emoji to numbered list items for news (1️⃣, 2️⃣, etc.)
    emoji_numbers = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟']
    
    # Find the news section and apply emojis
    if '📰' in formatted or 'Top 10 News' in formatted:
        news_section_match = re.search(r'(📰.*?Top 10 News Items.*?)(🐦|Top 10 X Posts|━━)', formatted, re.DOTALL)
        if news_section_match:
            news_section = news_section_match.group(1)
            for i in range(1, 11):
                emoji_num = emoji_numbers[i-1]
                # Replace numbered items in news section
                news_section = re.sub(
                    rf'^(\s*){i}\.\s+',
                    lambda m: m.group(1) + emoji_num + ' ',
                    news_section,
                    flags=re.MULTILINE
                )
            formatted = formatted.replace(news_section_match.group(1), news_section)
    
    # Add emoji to numbered list items for X posts (1️⃣, 2️⃣, etc.)
    if '🐦' in formatted or 'Top 10 X Posts' in formatted:
        x_section_match = re.search(r'(🐦.*?Top 10 X Posts.*?)(📉|Short Spot|━━)', formatted, re.DOTALL)
        if x_section_match:
            x_section = x_section_match.group(1)
            for i in range(1, 11):
                emoji_num = emoji_numbers[i-1] if i <= 10 else f'{i}.'
                # Replace numbered items in X posts section
                x_section = re.sub(
                    rf'^(\s*){i}\.\s+',
                    lambda m: m.group(1) + emoji_num + ' ',
                    x_section,
                    flags=re.MULTILINE
                )
            formatted = formatted.replace(x_section_match.group(1), x_section)
    
    # Clean up excessive newlines (more than 3 consecutive becomes 2)
    formatted = re.sub(r'\n{4,}', '\n\n', formatted)
    
    # Ensure proper spacing: add a blank line before numbered items if missing
    formatted = re.sub(r'\n(\d+\.)', r'\n\n\1', formatted)
    
    # Clean up: remove any triple newlines that might have been created
    formatted = re.sub(r'\n{3,}', '\n\n', formatted)
    
    # Clean up any markdown code blocks if any (they don't render well on X)
    formatted = re.sub(r'```[^`]*```', '', formatted, flags=re.DOTALL)
    
    # Ensure the post ends nicely if it doesn't already
    formatted = formatted.strip()
    if formatted and not formatted[-1] in '!?.':
        # Check if it ends with a quote or sign-off
        last_lines = formatted.split('\n')[-3:]
        last_text = ' '.join(last_lines).strip()
        if not any(word in last_text.lower() for word in ['feedback', 'dm', 'accelerating', 'electric', 'mission']):
            formatted += '\n\n⚡ Keep accelerating!'
    
    # Final cleanup: normalize whitespace
    # Replace multiple spaces with single space (but preserve intentional formatting)
    lines = formatted.split('\n')
    cleaned_lines = []
    for line in lines:
        # Preserve lines that are mostly spaces (intentional spacing)
        if line.strip() == '':
            cleaned_lines.append('')
        else:
            # Clean up excessive spaces but preserve markdown formatting
            cleaned_line = re.sub(r'[ \t]{2,}', ' ', line)
            cleaned_lines.append(cleaned_line)
    formatted = '\n'.join(cleaned_lines)
    
    # Final newline cleanup
    formatted = re.sub(r'\n{3,}', '\n\n', formatted)
    formatted = formatted.strip()
    
    # Check character limit (X allows 25,000 characters for long posts)
    max_chars = 25000
    if len(formatted) > max_chars:
        logging.warning(f"Formatted digest is {len(formatted)} characters, truncating to {max_chars}")
        # Try to truncate at a natural break point
        truncate_at = formatted[:max_chars-100].rfind('\n\n')
        if truncate_at > max_chars * 0.8:  # Only if we can keep at least 80% of content
            formatted = formatted[:truncate_at] + "\n\n... (content truncated for length)"
        else:
            formatted = formatted[:max_chars-50] + "\n\n... (truncated for length)"
    
    return formatted

# Format the digest
x_thread_formatted = format_digest_for_x(x_thread)
logging.info(f"Digest formatted for X ({len(x_thread_formatted)} characters)")

# Save both versions (original and formatted)
x_path = digests_dir / f"Tesla_Shorts_Time_{datetime.date.today():%Y%m%d}.md"
x_path_formatted = digests_dir / f"Tesla_Shorts_Time_{datetime.date.today():%Y%m%d}_formatted.md"

with open(x_path, "w", encoding="utf-8") as f:
    f.write(x_thread)
logging.info(f"Original X thread saved → {x_path}")

with open(x_path_formatted, "w", encoding="utf-8") as f:
    f.write(x_thread_formatted)
logging.info(f"Formatted X thread saved → {x_path_formatted}")

# Use the formatted version for posting
x_thread = x_thread_formatted

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
        bearer_token=os.getenv("X_BEARER_TOKEN"),
        wait_on_rate_limit=True
    )
    logging.info("@teslashortstime X posting client ready")
else:
    logging.info("X posting is disabled (ENABLE_X_POSTING = False)")

# ========================== 2. GENERATE PODCAST SCRIPT (NATURAL & FACT-BASED) ==========================
if not ENABLE_PODCAST:
    logging.info("Podcast generation is disabled (ENABLE_PODCAST = False). Skipping podcast script generation, audio processing, and RSS feed updates.")
    final_mp3 = None
else:
    # Simplified podcast prompt - use only the final formatted digest
    POD_PROMPT = f"""You are writing an 8–11 minute (1950–2600 words) solo podcast script for "Tesla Shorts Time Daily" Episode {episode_num}.

HOST: Patrick in Vancouver - Canadian, scientist, newscaster. Voice like a solo Podcaster breaking Tesla news, not robotic.

RULES:
- Start every line with "Patrick:"
- Don't read URLs aloud - mention source names naturally
- Use natural dates ("today", "this morning") not exact timestamps
- Enunciate all numbers, dollar amounts, percentages clearly
- Use ONLY information from the digest below - nothing else

SCRIPT STRUCTURE:
[Intro music - 10 seconds]
Patrick: Welcome to Tesla Shorts Time Daily, episode {episode_num}. It is {today_str}. I'm Patrick in Vancouver, Canada. TSLA stock price is ${price:.2f} right now{' in after-hours trading' if info.get("marketState") == "POST" else ''}. Thank you for joining us today. If you like the show, please like, share, rate and subscribe to the podcast, it really helps. Now straight to the daily news updates you are here for.

[Narrate EVERY item from the digest in order - no skipping]
- For each news item: Read the title with excitement, then paraphrase the summary naturally
- For each X post: Read the title with maximum hype, then paraphrase the post in excited speech
- Short Squeeze: Paraphrase with glee, calling out specific failed predictions and dollar losses
- Daily Challenge + Quote: Read the quote verbatim, then the challenge verbatim, add one encouraging sentence

[Closing]
Patrick: That's Tesla Shorts Time Daily for today. I look forward to hearing your thoughts and ideas — reach out to us @teslashortstime on X or DM us directly. Stay safe, keep accelerating, and remember: the future is electric! Your efforts help accelerate the world's transition to sustainable energy… and beyond. We'll catch you tomorrow on Tesla Shorts Time Daily!

Here is today's complete formatted digest. Use ONLY this content:
"""

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((Exception,))
    )
    def generate_podcast_script_with_grok():
        """Generate podcast script with retry logic"""
        return client.chat.completions.create(
            model="grok-4",
            messages=[
                {"role": "system", "content": "You are the world's best Tesla podcast writer. Make it feel like two real Canadian friends losing their minds (in a good way) over real Tesla news."},
                {"role": "user", "content": f"{POD_PROMPT}\n\n{x_thread}"}
            ],
            temperature=0.9,  # higher = more natural energy
            max_tokens=4000
        )
    
    logging.info("Generating podcast script with Grok (this may take 1-2 minutes)...")
    try:
        # Use only the final formatted digest - much simpler and more reliable
        podcast_response = generate_podcast_script_with_grok()
        podcast_script = podcast_response.choices[0].message.content.strip()
        
        # Log token usage if available
        if hasattr(podcast_response, 'usage') and podcast_response.usage:
            usage = podcast_response.usage
            logging.info(f"Podcast script generation - Tokens used: {usage.total_tokens} (prompt: {usage.prompt_tokens}, completion: {usage.completion_tokens})")
            # Estimate cost (Grok pricing may vary, using approximate)
            estimated_cost = (usage.total_tokens / 1000000) * 0.01  # Rough estimate
            logging.info(f"Estimated cost: ${estimated_cost:.4f}")
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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.RequestException, requests.Timeout))
    )
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


def scan_existing_episodes_from_files(digests_dir: Path, base_url: str) -> list:
    """Scan digests directory for all existing MP3 files and return episode data."""
    episodes = []
    pattern = r"Tesla_Shorts_Time_Pod_Ep(\d+)_(\d{8})\.mp3"
    
    for mp3_file in digests_dir.glob("Tesla_Shorts_Time_Pod_Ep*.mp3"):
        match = re.match(pattern, mp3_file.name)
        if match:
            episode_num = int(match.group(1))
            date_str = match.group(2)
            try:
                episode_date = datetime.datetime.strptime(date_str, "%Y%m%d").date()
                mp3_duration = get_audio_duration(mp3_file)
                
                # Create episode data
                # GUID based on date AND time to allow multiple episodes per day
                # Get time from mp3 file modification time or default to 000000
                try:
                    mtime = datetime.datetime.fromtimestamp(mp3_file.stat().st_mtime)
                    time_str = mtime.strftime("%H%M%S")
                except:
                    time_str = "000000"
                
                episode_guid = f"tesla-shorts-time-ep{episode_num:03d}-{date_str}-{time_str}"
                episode_title = f"Tesla Shorts Time Daily - Episode {episode_num} - {episode_date.strftime('%B %d, %Y')}"
                
                episodes.append({
                    'guid': episode_guid,
                    'title': episode_title,
                    'description': f"Daily Tesla news digest for {episode_date.strftime('%B %d, %Y')}.",
                    'link': f"{base_url}/digests/{mp3_file.name}",
                    'pubDate': datetime.datetime.combine(episode_date, datetime.time(8, 0, 0), tzinfo=datetime.timezone.utc),
                    'enclosure': {
                        'url': f"{base_url}/digests/{mp3_file.name}",
                        'type': 'audio/mpeg',
                        'length': str(mp3_file.stat().st_size)
                    },
                    'itunes_title': episode_title,
                    'itunes_summary': f"Daily Tesla news digest for {episode_date.strftime('%B %d, %Y')}.",
                    'itunes_duration': format_duration(mp3_duration),
                    'itunes_episode': str(episode_num),
                    'itunes_season': '1',
                    'itunes_episode_type': 'full',
                    'itunes_image': f"{base_url}/podcast-image.jpg",
                    'mp3_path': mp3_file,
                    'episode_num': episode_num,
                    'episode_date': episode_date
                })
            except Exception as e:
                logging.warning(f"Could not process {mp3_file.name}: {e}")
                continue
    
    # Sort by episode number (newest first for RSS)
    episodes.sort(key=lambda x: x['episode_num'], reverse=True)
    return episodes


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
    """Update or create RSS feed with new episode, preserving all existing episodes."""
    fg = FeedGenerator()
    fg.load_extension('podcast')
    
    # Parse existing RSS feed to preserve all episodes
    existing_episodes = []
    channel_metadata = {}
    existing_guids = set()
    
    if rss_path.exists():
        try:
            # Parse existing RSS XML
            tree = ET.parse(str(rss_path))
            root = tree.getroot()
            
            # Extract channel metadata
            channel = root.find('channel')
            if channel is not None:
                for elem in channel:
                    if elem.tag in ['title', 'link', 'description', 'language', 'copyright']:
                        channel_metadata[elem.tag] = elem.text
                    elif elem.tag == '{http://www.itunes.com/dtds/podcast-1.0.dtd}author':
                        channel_metadata['itunes_author'] = elem.text
                    elif elem.tag == '{http://www.itunes.com/dtds/podcast-1.0.dtd}summary':
                        channel_metadata['itunes_summary'] = elem.text
                    elif elem.tag == '{http://www.itunes.com/dtds/podcast-1.0.dtd}owner':
                        name_elem = elem.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}name')
                        email_elem = elem.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}email')
                        if name_elem is not None and email_elem is not None:
                            channel_metadata['itunes_owner'] = {'name': name_elem.text, 'email': email_elem.text}
                    elif elem.tag == '{http://www.itunes.com/dtds/podcast-1.0.dtd}image':
                        channel_metadata['itunes_image'] = elem.get('href')
                    elif elem.tag == '{http://www.itunes.com/dtds/podcast-1.0.dtd}category':
                        channel_metadata['itunes_category'] = elem.get('text')
                
                # Extract all existing episodes
                items = channel.findall('item')
                for item in items:
                    episode_data = {}
                    for elem in item:
                        if elem.tag == 'title':
                            episode_data['title'] = elem.text or ''
                        elif elem.tag == 'description':
                            episode_data['description'] = elem.text or ''
                        elif elem.tag == 'link':
                            episode_data['link'] = elem.text or ''
                        elif elem.tag == 'guid':
                            # GUID is typically the text content
                            if elem.text:
                                episode_data['guid'] = elem.text.strip()
                            # Some feeds might use guid as an attribute, but we'll use text primarily
                        elif elem.tag == 'pubDate':
                            episode_data['pubDate'] = elem.text or ''
                        elif elem.tag == 'enclosure':
                            episode_data['enclosure'] = {
                                'url': elem.get('url', ''),
                                'type': elem.get('type', 'audio/mpeg'),
                                'length': elem.get('length', '0')
                            }
                        elif elem.tag == '{http://www.itunes.com/dtds/podcast-1.0.dtd}title':
                            episode_data['itunes_title'] = elem.text or ''
                        elif elem.tag == '{http://www.itunes.com/dtds/podcast-1.0.dtd}summary':
                            episode_data['itunes_summary'] = elem.text or ''
                        elif elem.tag == '{http://www.itunes.com/dtds/podcast-1.0.dtd}duration':
                            episode_data['itunes_duration'] = elem.text or ''
                        elif elem.tag == '{http://www.itunes.com/dtds/podcast-1.0.dtd}episode':
                            episode_data['itunes_episode'] = elem.text or ''
                        elif elem.tag == '{http://www.itunes.com/dtds/podcast-1.0.dtd}season':
                            episode_data['itunes_season'] = elem.text or ''
                        elif elem.tag == '{http://www.itunes.com/dtds/podcast-1.0.dtd}episodeType':
                            episode_data['itunes_episode_type'] = elem.text or ''
                        elif elem.tag == '{http://www.itunes.com/dtds/podcast-1.0.dtd}image':
                            episode_data['itunes_image'] = elem.get('href', '')
                    
                    if episode_data.get('guid'):
                        existing_episodes.append(episode_data)
            
            logging.info(f"Loaded {len(existing_episodes)} existing episodes from RSS feed")
        except Exception as e:
            logging.warning(f"Could not parse existing RSS feed: {e}, creating new one")
            existing_episodes = []
    
    # Also scan file system for MP3 files to ensure we don't miss any episodes
    # This is important if the RSS feed was recreated or is missing episodes
    file_episodes = scan_existing_episodes_from_files(mp3_path.parent, base_url)
    
    # Merge episodes from RSS and file system, preferring RSS data but adding missing ones
    existing_guids = {ep.get('guid') for ep in existing_episodes if ep.get('guid')}
    file_guids = {fep.get('guid') for fep in file_episodes if fep.get('guid')}
    added_from_files = 0
    for file_ep in file_episodes:
        if file_ep.get('guid') not in existing_guids:
            logging.info(f"Found episode in file system but not in RSS: {file_ep.get('guid')} - adding it")
            existing_episodes.append(file_ep)
            existing_guids.add(file_ep.get('guid'))
            added_from_files += 1
    
    logging.info(f"Total episodes to include: {len(existing_episodes)} (from RSS: {len(existing_episodes) - added_from_files}, added from files: {added_from_files})")
    
    # Set channel metadata
    fg.title(channel_metadata.get('title', "Tesla Shorts Time Daily"))
    fg.link(href=channel_metadata.get('link', "https://github.com/patricknovak/Tesla-shorts-time"))
    fg.description(channel_metadata.get('description', "Daily Tesla news digest and podcast hosted by Patrick in Vancouver. Covering the latest Tesla developments, stock updates, and short squeeze celebrations."))
    fg.language(channel_metadata.get('language', 'en-us'))
    fg.copyright(channel_metadata.get('copyright', f"Copyright {datetime.date.today().year}"))
    fg.podcast.itunes_author(channel_metadata.get('itunes_author', "Patrick"))
    fg.podcast.itunes_summary(channel_metadata.get('itunes_summary', "Daily Tesla news digest and podcast covering the latest developments, stock updates, and short squeeze celebrations."))
    
    owner = channel_metadata.get('itunes_owner', {'name': 'Patrick', 'email': 'contact@teslashortstime.com'})
    fg.podcast.itunes_owner(name=owner.get('name', 'Patrick'), email=owner.get('email', 'contact@teslashortstime.com'))
    
    # Set image URL - ensure it's properly formatted for Apple Podcasts Connect
    image_url = channel_metadata.get('itunes_image', f"{base_url}/podcast-image.jpg")
    fg.podcast.itunes_image(image_url)
    
    category = channel_metadata.get('itunes_category', 'Technology')
    fg.podcast.itunes_category(category)
    fg.podcast.itunes_explicit("no")
    
    # Add all existing episodes
    # We no longer skip based on GUID match because we want to keep all episodes, even for same day
    # But we should check for exact duplicate GUIDs to avoid duplicates if run on same file
    
    # Generate GUID for the new episode based on current time to ensure uniqueness
    current_time_str = datetime.datetime.now().strftime("%H%M%S")
    new_episode_guid = f"tesla-shorts-time-ep{episode_num:03d}-{episode_date:%Y%m%d}-{current_time_str}"
    
    for ep_data in existing_episodes:
        # Skip if exact same GUID (should typically not happen with time-based GUIDs unless run very fast)
        if ep_data.get('guid') == new_episode_guid:
            continue
        
        # Re-add existing episode
        entry = fg.add_entry()
        entry.id(ep_data.get('guid', ''))
        entry.title(ep_data.get('title', ''))
        entry.description(ep_data.get('description', ''))
        if ep_data.get('link'):
            entry.link(href=ep_data['link'])
        
        # Parse and set pubDate
        if ep_data.get('pubDate'):
            try:
                # Handle both string dates (from RSS) and datetime objects (from file scan)
                if isinstance(ep_data['pubDate'], datetime.datetime):
                    entry.pubDate(ep_data['pubDate'])
                else:
                    from email.utils import parsedate_to_datetime
                    pub_date = parsedate_to_datetime(ep_data['pubDate'])
                    entry.pubDate(pub_date)
            except Exception:
                pass
        
        # Set enclosure
        if ep_data.get('enclosure'):
            enc = ep_data['enclosure']
            entry.enclosure(url=enc.get('url', ''), type=enc.get('type', 'audio/mpeg'), length=enc.get('length', '0'))
        
        # Set iTunes tags
        if ep_data.get('itunes_title'):
            entry.podcast.itunes_title(ep_data['itunes_title'])
        if ep_data.get('itunes_summary'):
            entry.podcast.itunes_summary(ep_data['itunes_summary'])
        if ep_data.get('itunes_duration'):
            entry.podcast.itunes_duration(ep_data['itunes_duration'])
        if ep_data.get('itunes_episode'):
            entry.podcast.itunes_episode(ep_data['itunes_episode'])
        if ep_data.get('itunes_season'):
            entry.podcast.itunes_season(ep_data['itunes_season'])
        if ep_data.get('itunes_episode_type'):
            entry.podcast.itunes_episode_type(ep_data['itunes_episode_type'])
        entry.podcast.itunes_explicit("no")
        # Set image for each episode (Apple Podcasts Connect requirement)
        # Use episode-specific image if available, otherwise use channel image
        episode_image = ep_data.get('itunes_image', image_url)
        entry.podcast.itunes_image(episode_image)
    
    # Add or update the new episode
    entry = fg.add_entry()
    entry.id(new_episode_guid)
    entry.title(episode_title)
    entry.description(episode_description)
    entry.link(href=f"{base_url}/digests/{mp3_filename}")
    pub_date = datetime.datetime.combine(episode_date, datetime.time(8, 0, 0), tzinfo=datetime.timezone.utc)
    entry.pubDate(pub_date)
    
    # Enclosure
    mp3_url = f"{base_url}/digests/{mp3_filename}"
    mp3_size = mp3_path.stat().st_size if mp3_path.exists() else 0
    entry.enclosure(url=mp3_url, type="audio/mpeg", length=str(mp3_size))
    
    # iTunes tags
    entry.podcast.itunes_title(episode_title)
    entry.podcast.itunes_summary(episode_description)
    entry.podcast.itunes_duration(format_duration(mp3_duration))
    entry.podcast.itunes_episode(str(episode_num))
    entry.podcast.itunes_season("1")
    entry.podcast.itunes_episode_type("full")
    entry.podcast.itunes_explicit("no")
    # Set image for the episode (Apple Podcasts Connect requirement)
    entry.podcast.itunes_image(image_url)
    
    # Update lastBuildDate
    fg.lastBuildDate(datetime.datetime.now(datetime.timezone.utc))
    
    # Write RSS feed
    fg.rss_file(str(rss_path), pretty=True)
    total_episodes = len(fg.entry())
    logging.info(f"RSS feed updated → {rss_path} ({total_episodes} episode(s) total)")

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
if ENABLE_PODCAST and not TEST_MODE and final_mp3 and final_mp3.exists():
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
        
        # MP3 filename relative to digests/ (where files are saved)
        mp3_filename = final_mp3.name
        
        # Generate thumbnail
        thumbnail_filename = f"Tesla_Shorts_Time_Thumbnail_Ep{episode_num:03d}_{datetime.date.today():%Y%m%d}.png"
        thumbnail_path = digests_dir / thumbnail_filename
        base_image_path = project_root / "podcast-image.jpg"
        generate_episode_thumbnail(base_image_path, episode_num, today_str, thumbnail_path)
        episode_image_url = f"{base_url}/digests/{thumbnail_filename}"
        
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
        # Use the formatted version that's already in memory (from Step 4)
        thread_text = x_thread.strip()
        
        # Post as one single tweet (X supports long posts up to 25,000 characters)
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

# ========================== CLEANUP TEMPORARY FILES ==========================
logging.info("Cleaning up temporary files...")
try:
    # Clean up all temp files in tmp_dir
    if tmp_dir.exists():
        for tmp_file in tmp_dir.glob("*"):
            try:
                if tmp_file.is_file():
                    tmp_file.unlink()
                    logging.debug(f"Removed temp file: {tmp_file}")
            except Exception as e:
                logging.warning(f"Could not remove temp file {tmp_file}: {e}")
    logging.info("Temporary files cleaned up")
except Exception as e:
    logging.warning(f"Error during temp file cleanup: {e}")

print("\n" + "="*80)
print("TESLA SHORTS TIME — FULLY AUTOMATED RUN COMPLETE")
print(f"X Thread → {x_path}")
print(f"Podcast → {final_mp3}")
print("="*80)

# Add at the end of the file, before the final print statements
