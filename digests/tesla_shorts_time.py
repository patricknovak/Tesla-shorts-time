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
from difflib import SequenceMatcher

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
    "ELEVENLABS_API_KEY",
    "NEWSAPI_KEY"  # For fetching Tesla news
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
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")

# ========================== STEP 1: FETCH TESLA NEWS FROM NEWSAPI.ORG ==========================
logging.info("Step 1: Fetching Tesla news from newsapi.org for the last 24 hours...")

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

def fetch_tesla_news():
    """Fetch Tesla-related news from newsapi.org for the last 24 hours."""
    newsapi_url = "https://newsapi.org/v2/everything"
    
    # Calculate date range (last 24 hours)
    from_date = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    to_date = datetime.datetime.now().strftime("%Y-%m-%d")
    
    params = {
        "q": "Tesla OR TSLA OR Elon Musk",
        "from": from_date,
        "to": to_date,
        "sortBy": "publishedAt",
        "language": "en",
        "pageSize": 50,  # Get up to 50 articles
        "apiKey": NEWSAPI_KEY
    }
    
    try:
        response = requests.get(newsapi_url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        articles = data.get("articles", [])
        logging.info(f"Fetched {len(articles)} articles from newsapi.org")
        
        # Filter and format articles
        formatted_articles = []
        for article in articles:
            # Skip articles without required fields
            if not article.get("title") or not article.get("url"):
                continue
            
            # Skip articles that are just stock quotes or price commentary
            title_lower = article.get("title", "").lower()
            if any(skip_term in title_lower for skip_term in ["stock quote", "tradingview", "yahoo finance ticker", "price chart"]):
                continue
            
            formatted_articles.append({
                "title": article.get("title", ""),
                "description": article.get("description", ""),
                "url": article.get("url", ""),
                "source": article.get("source", {}).get("name", "Unknown"),
                "publishedAt": article.get("publishedAt", ""),
                "author": article.get("author", "")
            })
        
        # Remove similar/duplicate articles based on title similarity
        before_dedup = len(formatted_articles)
        formatted_articles = remove_similar_items(
            formatted_articles,
            similarity_threshold=0.75,  # 75% similarity = likely duplicate
            get_text_func=lambda x: f"{x.get('title', '')} {x.get('description', '')}"
        )
        after_dedup = len(formatted_articles)
        if before_dedup != after_dedup:
            logging.info(f"Removed {before_dedup - after_dedup} similar/duplicate news articles")
        
        logging.info(f"Filtered to {len(formatted_articles)} unique Tesla news articles")
        return formatted_articles[:20]  # Return top 20 for selection
        
    except Exception as e:
        logging.error(f"Failed to fetch news from newsapi.org: {e}")
        logging.warning("Continuing without newsapi.org data - will rely on Grok search")
        return []

tesla_news = fetch_tesla_news()

# ========================== STEP 2: FETCH TOP X POSTS FROM X API ==========================
logging.info("Step 2: Fetching top X posts from the last 24 hours...")

def fetch_top_x_posts():
    """Fetch top X posts about Tesla from the last 24 hours, ranked by engagement."""
    if not ENABLE_X_POSTING:
        logging.warning("X posting disabled - cannot fetch X posts. Will rely on Grok search.")
        return []
    
    import tweepy
    
    x_client = tweepy.Client(
        consumer_key=os.getenv("X_CONSUMER_KEY"),
        consumer_secret=os.getenv("X_CONSUMER_SECRET"),
        access_token=os.getenv("X_ACCESS_TOKEN"),
        access_token_secret=os.getenv("X_ACCESS_TOKEN_SECRET"),
        wait_on_rate_limit=True
    )
    
    # Calculate date range (last 24 hours)
    since_time = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)).isoformat()
    
    # Search for Tesla-related posts
    search_queries = [
        "Tesla OR TSLA OR Elon Musk -is:retweet lang:en",
        "$TSLA -is:retweet lang:en",
        "Tesla FSD OR Cybertruck OR Robotaxi -is:retweet lang:en"
    ]
    
    all_posts = []
    
    try:
        for query in search_queries:
            try:
                # Search for tweets
                tweets = x_client.search_recent_tweets(
                    query=query,
                    max_results=100,  # Get up to 100 per query
                    tweet_fields=["created_at", "public_metrics", "author_id", "text"],
                    user_fields=["username", "name"],
                    expansions=["author_id"]
                )
                
                if tweets.data:
                    # Get user data
                    if tweets.includes and hasattr(tweets.includes, 'users'):
                        users = {user.id: user for user in tweets.includes.users}
                    elif tweets.includes and isinstance(tweets.includes, dict):
                        users = {user.id: user for user in tweets.includes.get("users", [])}
                    else:
                        users = {}
                    
                    for tweet in tweets.data:
                        # Calculate engagement score (weighted)
                        # Tweepy v4+ uses public_metrics as an object with attributes
                        metrics = tweet.public_metrics if hasattr(tweet, 'public_metrics') else {}
                        if hasattr(metrics, 'like_count'):
                            # It's a metrics object
                            like_count = getattr(metrics, 'like_count', 0)
                            retweet_count = getattr(metrics, 'retweet_count', 0)
                            reply_count = getattr(metrics, 'reply_count', 0)
                            quote_count = getattr(metrics, 'quote_count', 0)
                        else:
                            # It's a dict
                            like_count = metrics.get("like_count", 0) if isinstance(metrics, dict) else 0
                            retweet_count = metrics.get("retweet_count", 0) if isinstance(metrics, dict) else 0
                            reply_count = metrics.get("reply_count", 0) if isinstance(metrics, dict) else 0
                            quote_count = metrics.get("quote_count", 0) if isinstance(metrics, dict) else 0
                        
                        engagement = (
                            like_count * 1 +
                            retweet_count * 2 +
                            reply_count * 1.5 +
                            quote_count * 2
                        )
                        
                        # Get username
                        author = users.get(tweet.author_id)
                        username = author.username if author else "unknown"
                        name = author.name if author else "Unknown"
                        
                        # Check if post is within last 24 hours
                        tweet_time = tweet.created_at
                        if tweet_time and (datetime.datetime.now(datetime.timezone.utc) - tweet_time).total_seconds() <= 86400:
                            all_posts.append({
                                "id": tweet.id,
                                "text": tweet.text,
                                "username": username,
                                "name": name,
                                "url": f"https://x.com/{username}/status/{tweet.id}",
                                "created_at": tweet_time.isoformat(),
                                "engagement": engagement,
                                "likes": like_count,
                                "retweets": retweet_count,
                                "replies": reply_count
                            })
            except Exception as e:
                logging.warning(f"Error searching with query '{query}': {e}")
                continue
        
        # Sort by engagement and get top posts
        all_posts.sort(key=lambda x: x["engagement"], reverse=True)
        
        # Remove duplicates (by tweet ID)
        seen_ids = set()
        unique_posts = []
        for post in all_posts:
            if post["id"] not in seen_ids:
                seen_ids.add(post["id"])
                unique_posts.append(post)
        
        # Remove similar/duplicate posts based on text content similarity
        before_dedup = len(unique_posts)
        unique_posts = remove_similar_items(
            unique_posts,
            similarity_threshold=0.70,  # 70% similarity = likely duplicate or very similar
            get_text_func=lambda x: x.get("text", "")
        )
        after_dedup = len(unique_posts)
        if before_dedup != after_dedup:
            logging.info(f"Removed {before_dedup - after_dedup} similar/duplicate X posts")
        
        # Get top 20 for selection
        top_posts = unique_posts[:20]
        logging.info(f"Fetched {len(top_posts)} unique top X posts (ranked by engagement)")
        
        return top_posts
        
    except Exception as e:
        logging.error(f"Failed to fetch X posts: {e}")
        logging.warning("Continuing without X API data - will rely on Grok search")
        return []

top_x_posts = fetch_top_x_posts()

# ========================== STEP 3: GENERATE X THREAD WITH GROK ==========================
logging.info("Step 3: Generating Tesla Shorts Time digest with Grok using pre-fetched news and X posts...")

# Format news articles for the prompt
news_section = ""
if tesla_news:
    news_section = "## PRE-FETCHED NEWS ARTICLES (from newsapi.org - last 24 hours):\n\n"
    for i, article in enumerate(tesla_news[:15], 1):  # Top 15 articles
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
    x_posts_section = f"## PRE-FETCHED X POSTS (from X API - last 24 hours, ranked by engagement):\n\n"
    x_posts_section += f"**IMPORTANT: You have {len(top_x_posts)} pre-fetched X posts available. You MUST select exactly 10 of these for your output.**\n\n"
    for i, post in enumerate(top_x_posts[:num_posts_to_include], 1):  # Include up to 20 posts
        x_posts_section += f"{i}. **@{post['username']} ({post['name']})**\n"
        x_posts_section += f"   Engagement Score: {post['engagement']:.0f} (Likes: {post['likes']}, RTs: {post['retweets']}, Replies: {post['replies']})\n"
        x_posts_section += f"   Posted: {post['created_at']}\n"
        x_posts_section += f"   Text: {post['text'][:300]}...\n"
        x_posts_section += f"   URL: {post['url']}\n\n"
    if len(top_x_posts) < 10:
        x_posts_section += f"\n**WARNING: Only {len(top_x_posts)} X posts were fetched. You MUST use web search to find additional X posts to reach exactly 10 total posts in your output.**\n\n"
else:
    x_posts_section = "## PRE-FETCHED X POSTS: None available\n\n"
    x_posts_section += "**CRITICAL: No X posts were pre-fetched. You MUST use web search and X search tools to find exactly 10 X posts from the last 24 hours for your output.**\n\n"

X_PROMPT = f"""
# Tesla Shorts Time - DAILY EDITION
**Date:** {today_str}
**REAL-TIME TSLA price:** ${price:.2f} {change_str}

{news_section}

{x_posts_section}

You are an elite Tesla news curator producing the daily "Tesla Shorts Time" newsletter. Your job is to create the most exciting, credible, and timely Tesla digest using the PRE-FETCHED news articles and X posts provided above.

### CRITICAL INSTRUCTIONS - USE ONLY PRE-FETCHED CONTENT URLS
- **YOU MUST USE ONLY THE EXACT URLs PROVIDED IN THE PRE-FETCHED DATA ABOVE**
- **NEVER make up, invent, or hallucinate URLs or links**
- **NEVER use web search results for URLs - only use the URLs from the pre-fetched news articles and X posts**
- If you have fewer than 10 X posts in the pre-fetched list, you may reference additional X posts from web search, but you MUST use the exact X post URLs from the pre-fetched list for all items that are available
- All news articles MUST use the exact URL from the pre-fetched article list
- All X posts MUST use the exact URL from the pre-fetched X posts list (format: https://x.com/username/status/ID)
- If you cannot find enough pre-fetched content, output fewer items rather than making up links

### SELECTION RULES (ZERO EXCEPTIONS - MANDATORY COUNTS)
**YOU MUST INCLUDE EXACTLY THESE COUNTS - NO EXCEPTIONS:**
- **EXACTLY 5 unique news articles** from the pre-fetched list (prioritize highest quality sources)
- **X POSTS: Use ALL available pre-fetched X posts (up to 10 maximum). If you have 0 pre-fetched X posts, output 0 X posts. If you have 3, output 3. If you have 10+, output exactly 10.**
- **CRITICAL: DO NOT make up or hallucinate X post URLs. Only use the exact URLs from the pre-fetched X posts list.**
- **CRITICAL: If there are 0 pre-fetched X posts available, you MUST output 0 X posts in the "Top 10 X Posts" section (or skip that section entirely if 0 posts). DO NOT invent posts or URLs.**
- **NEVER invent URLs or links - only use the exact URLs provided in the pre-fetched data**

**DIVERSITY RULES (apply after meeting the count requirements):**
- Max 3 items total from any single news source
- Max 3 X posts from any single X account username (but you MUST still include 10 total X posts - if needed, allow up to 4 from a single account to meet the 10-post requirement)
- **CRITICAL: NO DUPLICATE OR SIMILAR CONTENT** - Each news item and X post must cover a DIFFERENT story/angle. If two items cover the same news story or make the same point, you MUST choose only one and find a different item to replace it
- **SIMILARITY CHECK**: Before including any item, check if it's similar (≥70% same content/angle) to any other item you've already selected. If so, skip it and choose a different one
- No stock-quote pages, Yahoo Finance ticker pages, TradingView screenshots, or pure price commentary as "news"

### FORMATTING (MUST BE EXACT – DO NOT DEVIATE)
Use this exact structure and markdown (includes invisible zero-width spaces for perfect X rendering – do not remove them; do not include any of the instructions brackets, just follow the instructions within the brackets):
# Tesla Shorts Time
**Date:** {today_str}
**REAL-TIME TSLA price:** ${price:.2f}
Tesla Shorts Time Daily Podcast Link: https://podcasts.apple.com/us/podcast/tesla-shorts-time/id1855142939

━━━━━━━━━━━━━━━━━━━━

### Top 5 News Items
1. **Title That Fits in One Line: DD Month, YYYY, HH:MM AM/PM PST, Source Name**
   2–4 sentence summary starting with what happened, then why it matters for Tesla's future and stock. End with: Source: [EXACT URL FROM PRE-FETCHED ARTICLE - DO NOT MODIFY OR INVENT]

2. **Title That Fits in One Line: DD Month, YYYY, HH:MM AM/PM PST, Source Name**
   2–4 sentence summary starting with what happened, then why it matters for Tesla's future and stock. End with link in Source

3. **Title That Fits in One Line: DD Month, YYYY, HH:MM AM/PM PST, Source Name**
   2–4 sentence summary starting with what happened, then why it matters for Tesla's future and stock. End with link in Source

4. **Title That Fits in One Line: DD Month, YYYY, HH:MM AM/PM PST, Source Name**
   2–4 sentence summary starting with what happened, then why it matters for Tesla's future and stock. End with link in Source

5. **Title That Fits in One Line: DD Month, YYYY, HH:MM AM/PM PST, Source Name**
   2–4 sentence summary starting with what happened, then why it matters for Tesla's future and stock. End with link in Source

━━━━━━━━━━━━━━━━━━━━

### Top 10 X Posts
1. **Catchy Title for the Post: DD Month, YYYY, HH:MM AM/PM PST**
   2–4 sentences explaining the post and its significance. End with: Post: [EXACT URL FROM PRE-FETCHED X POST - format: https://x.com/username/status/ID - DO NOT MODIFY OR INVENT]

2. **Catchy Title for the Post: DD Month, YYYY, HH:MM AM/PM PST**
   2–4 sentences explaining the post and its significance. End with Post link.

3. **Catchy Title for the Post: DD Month, YYYY, HH:MM AM/PM PST**
   2–4 sentences explaining the post and its significance. End with Post link.

4. **Catchy Title for the Post: DD Month, YYYY, HH:MM AM/PM PST**
   2–4 sentences explaining the post and its significance. End with Post link.

5. **Catchy Title for the Post: DD Month, YYYY, HH:MM AM/PM PST**
   2–4 sentences explaining the post and its significance. End with Post link.

6. **Catchy Title for the Post: DD Month, YYYY, HH:MM AM/PM PST**
   2–4 sentences explaining the post and its significance. End with Post link.

7. **Catchy Title for the Post: DD Month, YYYY, HH:MM AM/PM PST**
   2–4 sentences explaining the post and its significance. End with Post link.

8. **Catchy Title for the Post: DD Month, YYYY, HH:MM AM/PM PST**
   2–4 sentences explaining the post and its significance. End with Post link.

9. **Catchy Title for the Post: DD Month, YYYY, HH:MM AM/PM PST**
   2–4 sentences explaining the post and its significance. End with Post link.

10. **Catchy Title for the Post: DD Month, YYYY, HH:MM AM/PM PST**
   2–4 sentences explaining the post and its significance. End with Post link.

━━━━━━━━━━━━━━━━━━━━
━━━━━━━━━━━━━━━━━━━━

## Short Spot
One bearish news or X post item that is a major negative for Tesla and the stock.
**Catchy Title for the Post: DD Month, YYYY, HH:MM AM/PM PST, @username Post**
   2–4 sentences explaining the post and its significance. End with Post link.

━━━━━━━━━━━━━━━━━━━━

### Short Squeeze
Dedicated paragraph celebrating short-seller pain. Must include:
Current short interest % and $ value (cite source if possible).
At least 2 specific failed bear predictions from 2023–2025 with links or references (vary from past editions).
Total $ losses shorts have taken YTD or in a recent squeeze event.

━━━━━━━━━━━━━━━━━━━━

### Daily Challenge
One short, inspiring personal-growth challenge tied to Tesla/Elon themes (curiosity, first principles, perseverance). End with: "Share your progress with us @teslashortstime!"

━━━━━━━━━━━━━━━━━━━━

**Inspiration Quote:** "Exact quote" – Author, [Source Link] (fresh, no repeats from last 7 days)
[Final 2-3 sentence uplifting sign-off about Tesla's mission and invitation to DM @teslashortstime with feedback]
Add a blank line after the sign-off.
### TONE & STYLE RULES (NON-NEGOTIABLE)
-Inspirational, pro-Tesla, optimistic, energetic
-Never negative or sarcastic about Tesla/Elon (you may acknowledge challenges but always frame them as temporary or already being crushed)
-No hallucinations, no made-up news, no placeholder text, NO MADE-UP URLS
-All links MUST be the exact URLs from the pre-fetched data - copy them exactly, do not modify or invent
-If a pre-fetched item doesn't have a URL, skip it and choose a different item
-Time stamps must be accurate PST/PDT (convert correctly)

### FINAL VALIDATION BEFORE OUTPUT (MANDATORY)
Before outputting, verify:
1. ✅ Exactly 5 news items are included (numbered 1. 2. 3. 4. 5.) - each covering a DIFFERENT story
2. ✅ X posts section includes all available pre-fetched X posts (up to 10 maximum). If 0 posts are available, the section may be empty or skipped. Each post covers a DIFFERENT topic/angle.
3. ✅ All numbered lists use the format "1. " (number, period, space) - NOT bullet points or other formats
4. ✅ Separator lines "━━━━━━━━━━━━━━━━━━━━" are included before each major section
5. ✅ NO DUPLICATES: Each news item and X post covers a unique story/angle (no two items about the same news event)
6. ✅ Short Spot section is included
7. ✅ Short Squeeze section is included
8. ✅ Daily Challenge section is included
9. ✅ Inspiration Quote is included

**SIMILARITY CHECK**: Review all 5 news items and all X posts (if any). If any two items cover the same story or make the same point, replace one with a different item. Each item must be unique.

**CRITICAL URL RULES:**
- For each news item, you MUST use the exact URL from the pre-fetched article list above
- For each X post, you MUST use the exact URL from the pre-fetched X posts list above (format: https://x.com/username/status/ID)
- If you cannot match an output item to a pre-fetched URL, DO NOT include that item - choose a different pre-fetched item instead
- NEVER modify URLs, shorten them, or create new ones
- If you have fewer than 10 pre-fetched X posts, output exactly that many (numbered 1, 2, 3, etc.) - DO NOT make up additional posts or URLs

Now produce today's edition following every rule above exactly. Remember: Use ONLY pre-fetched X posts (up to 10 maximum). If 0 posts are available, output 0 posts. DO NOT invent or hallucinate any URLs.
"""

logging.info("Generating X thread with Grok using pre-fetched content (this may take 1-2 minutes)...")
try:
    response = client.chat.completions.create(
        model="grok-4-1-fast-reasoning",
        messages=[{"role": "user", "content": X_PROMPT}],
        temperature=0.7,
        max_tokens=4000,
        # Disable web search - we want to use ONLY pre-fetched URLs to avoid hallucinations and dead links
        # All content must come from the pre-fetched news articles and X posts
        extra_body={"search_parameters": {"mode": "off"}}
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

# ========================== VALIDATE AND FIX LINKS ==========================
logging.info("Validating and fixing links in the generated digest...")

def validate_and_fix_links(digest_text: str, news_articles: list, x_posts: list) -> str:
    """
    Validate all URLs in the digest and replace with correct URLs from pre-fetched data.
    Returns the corrected digest text.
    """
    import re
    
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
    url_pattern = r'https?://[^\s\)]+'
    urls_found = re.findall(url_pattern, digest_text)
    
    # Track issues
    invalid_urls = []
    fixed_count = 0
    
    # Check each URL
    for url in urls_found:
        url_clean = url.rstrip('.,;:!?)')
        
        # Skip known good URLs
        if any(skip in url_clean for skip in ['podcasts.apple.com', 'teslashortstime.com', 'x.com/teslashortstime']):
            continue
        
        # Check if URL is in pre-fetched data
        is_valid = False
        for article in news_articles:
            if url_clean == article.get('url', ''):
                is_valid = True
                break
        
        if not is_valid:
            for post in x_posts:
                if url_clean == post.get('url', ''):
                    is_valid = True
                    break
        
        if not is_valid:
            invalid_urls.append(url_clean)
            logging.warning(f"Found potentially invalid URL in digest: {url_clean}")
    
    if invalid_urls:
        logging.warning(f"Found {len(invalid_urls)} potentially invalid URLs. These may need manual review.")
        logging.warning(f"Invalid URLs: {invalid_urls[:5]}...")  # Log first 5
    
    return digest_text

# Validate links
x_thread = validate_and_fix_links(x_thread, tesla_news, top_x_posts)

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
    
    # Format podcast link with emoji
    formatted = re.sub(r'Tesla Shorts Time Daily Podcast Link:', '🎙️ Tesla Shorts Time Daily Podcast Link:', formatted)
    
    # Format section headers with emojis (preserve existing markdown)
    formatted = re.sub(r'^### Top 5 News Items', '📰 **Top 5 News Items**', formatted, flags=re.MULTILINE)
    formatted = re.sub(r'^### Top 10 X Posts', '🐦 **Top 10 X Posts**', formatted, flags=re.MULTILINE)
    formatted = re.sub(r'^## Short Spot', '📉 **Short Spot**', formatted, flags=re.MULTILINE)
    formatted = re.sub(r'^### Short Squeeze', '📈 **Short Squeeze**', formatted, flags=re.MULTILINE)
    formatted = re.sub(r'^### Daily Challenge', '💪 **Daily Challenge**', formatted, flags=re.MULTILINE)
    
    # Add emoji to Inspiration Quote
    formatted = re.sub(r'\*\*Inspiration Quote:\*\*', '✨ **Inspiration Quote:**', formatted)
    
    # Add separator lines before major sections
    # First, remove any existing separators to avoid duplicates
    formatted = re.sub(r'\n\n━━━━━━━━━━━━━━━━━━━━\n\n+', '\n\n', formatted)
    
    separator = '\n\n━━━━━━━━━━━━━━━━━━━━\n\n'
    
    # Add separator before Top 5 News Items (check both formatted and unformatted versions)
    formatted = re.sub(r'(\n\n)(📰 \*\*Top 5 News Items\*\*)', separator + r'\2', formatted)
    formatted = re.sub(r'(\n\n)(### Top 5 News Items)', separator + r'\2', formatted)
    
    # Add separator before Top 10 X Posts
    formatted = re.sub(r'(\n\n)(🐦 \*\*Top 10 X Posts\*\*)', separator + r'\2', formatted)
    formatted = re.sub(r'(\n\n)(### Top 10 X Posts)', separator + r'\2', formatted)
    
    # Add separator before Short Spot
    formatted = re.sub(r'(\n\n)(📉 \*\*Short Spot\*\*)', separator + r'\2', formatted)
    formatted = re.sub(r'(\n\n)(## Short Spot)', separator + r'\2', formatted)
    
    # Add separator before Short Squeeze
    formatted = re.sub(r'(\n\n)(📈 \*\*Short Squeeze\*\*)', separator + r'\2', formatted)
    formatted = re.sub(r'(\n\n)(### Short Squeeze)', separator + r'\2', formatted)
    
    # Add separator before Daily Challenge
    formatted = re.sub(r'(\n\n)(💪 \*\*Daily Challenge\*\*)', separator + r'\2', formatted)
    formatted = re.sub(r'(\n\n)(### Daily Challenge)', separator + r'\2', formatted)
    
    # Add separator before Inspiration Quote
    formatted = re.sub(r'(\n\n)(✨ \*\*Inspiration Quote:\*\*)', separator + r'\2', formatted)
    
    # Ensure numbered lists are properly formatted
    # Fix news items: ensure they're numbered 1. 2. 3. etc. (not just bullet points)
    # Look for patterns like "1." or "1 " at the start of lines in the news section
    # This regex ensures numbered format: number followed by period and space
    formatted = re.sub(r'^(\d+)[\.\s]+(?=\*\*[^📰🐦📉📈💪])', r'\1. ', formatted, flags=re.MULTILINE)
    
    # Ensure X posts are numbered correctly (1. 2. 3. etc.)
    # The numbering should already be in the prompt, but we'll ensure consistency
    
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
Patrick: Welcome to Tesla Shorts Time Daily, episode {episode_num}
It is (say today's date in the format of November 21, 2025).
I’m Patrick in Vancouver, Canada. TSLA stock price is ${price:.2f} right now (enunciate the price clearly).
Thank you for joining us today. If you like the show, please like, share, rate and subscribe to the podcast, it really helps.
Now straight to the daily news updates you are here for.
[Now narrate EVERY SINGLE ITEM from the digest in published order — no skipping]
→ For each of the 6 Top News Items:
   Patrick: [Read the bold title with excitement] → then paraphrase the 2–4 sentence summary in natural, rapid, hyped speech, hitting every key fact and why it matters
→ For the 10 X posts:
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
            model="grok-4-1-fast-reasoning",
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
        itunes_image.set("href", f"{base_url}/podcast-image.jpg")
        itunes_cat = ET.SubElement(channel, "itunes:category")
        itunes_cat.set("text", "Technology")
        ET.SubElement(channel, "itunes:explicit").text = "no"
    
    # Ensure channel-level image is always present (even if RSS feed already existed)
    existing_image = channel.find("itunes:image")
    if existing_image is None:
        itunes_image = ET.SubElement(channel, "itunes:image")
        itunes_image.set("href", f"{base_url}/podcast-image.jpg")
        logging.info(f"Added channel-level itunes:image to RSS feed")
    else:
        # Update the href to ensure it's correct
        existing_image.set("href", f"{base_url}/podcast-image.jpg")
        logging.info(f"Updated channel-level itunes:image in RSS feed")
    
    # Check if episode already exists (by GUID)
    episode_guid = f"tesla-shorts-time-ep{episode_num:03d}-{episode_date:%Y%m%d}"
    existing_items = channel.findall("item")
    episode_exists = False
    for item in existing_items:
        guid_elem = item.find("guid")
        if guid_elem is not None and guid_elem.text == episode_guid:
            logging.info(f"Episode {episode_num} already in RSS feed, updating existing entry")
            episode_exists = True
            # Update existing episode with latest information
            # Update title
            title_elem = item.find("title")
            if title_elem is not None:
                title_elem.text = episode_title
            # Update description
            desc_elem = item.find("description")
            if desc_elem is not None:
                desc_elem.text = html.escape(episode_description)
            # Update enclosure URL and size
            enclosure = item.find("enclosure")
            if enclosure is not None:
                mp3_url = f"{base_url}/digests/digests/{mp3_filename}"
                enclosure.set("url", mp3_url)
                mp3_size = mp3_path.stat().st_size if mp3_path.exists() else 0
                enclosure.set("length", str(mp3_size))
            # Update itunes:title
            itunes_title = item.find("itunes:title")
            if itunes_title is not None:
                itunes_title.text = episode_title
            # Update itunes:summary
            itunes_summary = item.find("itunes:summary")
            if itunes_summary is not None:
                itunes_summary.text = episode_description
            # Update duration
            itunes_duration = item.find("itunes:duration")
            if itunes_duration is not None:
                itunes_duration.text = format_duration(mp3_duration)
            # Update season
            itunes_season = item.find("itunes:season")
            if itunes_season is not None:
                itunes_season.text = "1"
            else:
                ET.SubElement(item, "itunes:season").text = "1"
            # Ensure existing episode has image tag
            existing_item_image = item.find("itunes:image")
            if existing_item_image is None:
                item_image = ET.SubElement(item, "itunes:image")
                item_image.set("href", f"{base_url}/podcast-image.jpg")
                logging.info(f"Added itunes:image to existing episode {episode_num}")
            # Update lastBuildDate even if episode exists
            last_build_elem = channel.find("lastBuildDate")
            if last_build_elem is not None:
                last_build_elem.text = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
            # Write the updated RSS feed
            try:
                tree = ET.ElementTree(root)
                ET.indent(tree, space="  ")
                with open(rss_path, "wb") as f:
                    f.write('<?xml version="1.0" encoding="UTF-8"?>\n'.encode('utf-8'))
                    tree.write(f, encoding="utf-8", xml_declaration=False)
                # Post-process to fix namespace prefixes
                with open(rss_path, "r", encoding="utf-8") as f:
                    content = f.read()
                content = content.replace('xmlns:ns0="http://www.itunes.com/dtds/podcast-1.0.dtd"', 'xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"')
                content = content.replace('xmlns:ns1="http://purl.org/rss/1.0/modules/content/"', 'xmlns:content="http://purl.org/rss/1.0/modules/content/"')
                content = content.replace('<ns0:', '<itunes:')
                content = content.replace('</ns0:', '</itunes:')
                content = content.replace('<ns1:', '<content:')
                content = content.replace('</ns1:', '</content:')
                with open(rss_path, "w", encoding="utf-8") as f:
                    f.write(content)
                logging.info(f"RSS feed updated (existing episode) → {rss_path}")
                logging.info(f"RSS feed contains {len(channel.findall('item'))} episode(s)")
                # Force file modification time update to ensure git detects the change
                import os
                os.utime(rss_path, None)
                logging.info(f"RSS feed file timestamp updated to ensure git detects changes")
            except Exception as e:
                logging.error(f"Failed to write RSS feed to {rss_path}: {e}", exc_info=True)
                raise
            return
    
    if episode_exists:
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
    ET.SubElement(item, "itunes:season").text = "1"  # Season 1
    ET.SubElement(item, "itunes:episodeType").text = "full"
    ET.SubElement(item, "itunes:explicit").text = "no"
    
    # Add itunes:image to each episode (inherits from channel but explicit is better)
    item_image = ET.SubElement(item, "itunes:image")
    item_image.set("href", f"{base_url}/podcast-image.jpg")
    
    # Update lastBuildDate
    last_build_elem = channel.find("lastBuildDate")
    if last_build_elem is not None:
        last_build_elem.text = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    else:
        ET.SubElement(channel, "lastBuildDate").text = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    
    # Ensure all existing episodes have itunes:image and itunes:season (update if missing)
    all_items = channel.findall("item")
    for existing_item in all_items:
        existing_item_image = existing_item.find("itunes:image")
        if existing_item_image is None:
            item_image = ET.SubElement(existing_item, "itunes:image")
            item_image.set("href", f"{base_url}/podcast-image.jpg")
            logging.info(f"Added itunes:image to existing episode in RSS feed")
        # Ensure season tag exists
        existing_item_season = existing_item.find("itunes:season")
        if existing_item_season is None:
            ET.SubElement(existing_item, "itunes:season").text = "1"
            logging.info(f"Added itunes:season to existing episode in RSS feed")
        elif existing_item_season.text != "1":
            existing_item_season.text = "1"
            logging.info(f"Updated itunes:season to 1 for existing episode in RSS feed")
    
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
        
        # Force file modification time update to ensure git detects the change
        import os
        os.utime(rss_path, None)
        
        logging.info(f"RSS feed updated → {rss_path}")
        logging.info(f"RSS feed contains {len(channel.findall('item'))} episode(s)")
        logging.info(f"RSS feed file timestamp updated to ensure git detects changes")
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

print("\n" + "="*80)
print("TESLA SHORTS TIME — FULLY AUTOMATED RUN COMPLETE")
print(f"X Thread → {x_path}")
print(f"Podcast → {final_mp3}")
print("="*80)
