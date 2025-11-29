#!/usr/bin/env python3
"""
Test script for retrieving relevant Tesla X posts.
This script tests the X API integration to fetch Tesla-related posts from trusted accounts.
"""

import os
import sys
import logging
import datetime
from typing import List, Dict
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

# Trusted usernames to fetch posts from
# Focused on top high-engagement accounts optimized to fit within 512 character query limit
# Query uses 472 chars, leaving 40 chars buffer (18 accounts total)
TRUSTED_USERNAMES = [
    # Highest Engagement Accounts
    "elonmusk",  # Highest engagement, Tesla CEO
    
    # Official Tesla Accounts (High Engagement)
    "Tesla", "Tesla_AI", "TeslaCharging", "cybertruck", "teslaenergy",
    "GigaTexas", "GigaBerlin",  # Factory accounts with high engagement
    
    # Top Tesla Influencers (High Engagement)
    "SawyerMerritt", "WholeMarsBlog", "TeslaRaj",
    
    # Tesla Analysts & Investors (High Engagement)
    "GaryBlack00", "TroyTeslike", "RossGerber",
    
    # Top Tesla Media Outlets (High Engagement)
    "Teslarati", "ElectrekCo", "InsideEVs", "CleanTechnica",
]

# Tesla-related keywords for content filtering (case-insensitive)
TESLA_CONTENT_KEYWORDS = [
    "tesla", "tsla", "model 3", "model y", "model s", "model x", "cybertruck",
    "roadster", "semi", "robotaxi", "optimus", "fsd", "full self-driving",
    "autopilot", "supercharger", "giga", "gigafactory", "gigatexas", "gigaberlin",
    "gigashanghai", "4680", "lfp", "hw4", "hw5", "ai5", "tesla energy",
    "powerwall", "megapack", "solar roof", "tesla charging"
]


def is_tesla_related(text: str) -> bool:
    """
    Check if post text contains Tesla-related keywords.
    Returns True if the post is about Tesla, False otherwise.
    """
    if not text:
        return False
    
    text_lower = text.lower()
    
    # Check if any Tesla keyword appears in the text
    for keyword in TESLA_CONTENT_KEYWORDS:
        if keyword.lower() in text_lower:
            return True
    
    return False


def fetch_top_x_posts_from_trusted_accounts() -> tuple[List[Dict], List[Dict]]:
    """
    Fetch Tesla-related posts from trusted X accounts using the X API.
    Only includes posts that are actually about Tesla (content-filtered).
    Prioritizes original posts (excludes retweets).
    Returns: (top_posts, raw_posts) tuple
    """
    logging.info("Fetching Tesla posts from trusted accounts (Tesla content only, original posts, retweets excluded)...")

    end_time = datetime.datetime.now(datetime.timezone.utc)
    start_time = end_time - datetime.timedelta(hours=48)  # 48h window

    all_posts = []
    raw_posts = []

    # Build query for Tesla-related content
    # Shortened keywords to stay under 512 char limit
    tesla_keywords = "(Tesla OR TSLA OR Model OR Cybertruck OR FSD OR Supercharger OR Giga OR Optimus OR Robotaxi OR 4680)"
    # X usernames can contain letters, numbers, and underscores - filter to allow those
    from_part = " OR ".join([f"from:{u}" for u in TRUSTED_USERNAMES if all(c.isalnum() or c == '_' for c in u)])
    # Prioritize original posts, exclude retweets
    # Simplified query - keywords only applied once to reduce length
    query = f"{from_part} ({tesla_keywords}) -is:reply -is:retweet lang:en"
    
    # Validate query length (X API limit is 512 chars)
    if len(query) > 512:
        logging.warning(f"Query too long ({len(query)} chars), using simplified version...")
        # Fallback: Use only top priority accounts
        priority_accounts = ["elonmusk", "Tesla", "Tesla_AI", "SawyerMerritt"]
        from_part = " OR ".join([f"from:{u}" for u in priority_accounts])
        query = f"{from_part} ({tesla_keywords}) -is:reply -is:retweet lang:en"
    
    logging.info(f"Query length: {len(query)} characters (limit: 512)")

    try:
        import tweepy
        
        # Check for bearer token
        bearer_token = os.getenv("X_BEARER_TOKEN")
        if not bearer_token:
            logging.error("X_BEARER_TOKEN not found in environment variables!")
            return [], []
        
        # Initialize X API client
        x_client = tweepy.Client(
            bearer_token=bearer_token,
            wait_on_rate_limit=True
        )
        
        logging.info(f"Searching X with query: {query[:100]}...")
        logging.info(f"Time range: {start_time} to {end_time}")
        
        # Fetch tweets - try to get more results with pagination if needed
        all_tweets = []
        response = x_client.search_recent_tweets(
            query=query,
            max_results=100,  # Max allowed per request
            start_time=start_time,
            tweet_fields=['created_at', 'public_metrics', 'author_id', 'text', 'referenced_tweets'],
            user_fields=['username', 'name'],
            expansions=['author_id', 'referenced_tweets.id']
        )
        
        if response.data:
            all_tweets.extend(response.data)
            logging.info(f"First batch: {len(response.data)} tweets")
        
        # Try to get more results if we have a next_token (pagination)
        if hasattr(response, 'meta') and response.meta and 'next_token' in response.meta:
            try:
                next_response = x_client.search_recent_tweets(
                    query=query,
                    max_results=100,
                    start_time=start_time,
                    next_token=response.meta['next_token'],
                    tweet_fields=['created_at', 'public_metrics', 'author_id', 'text', 'referenced_tweets'],
                    user_fields=['username', 'name'],
                    expansions=['author_id', 'referenced_tweets.id']
                )
                if next_response.data:
                    all_tweets.extend(next_response.data)
                    logging.info(f"Second batch: {len(next_response.data)} tweets")
            except Exception as e:
                logging.debug(f"Could not fetch second page: {e}")
        
        # Use combined tweets
        tweets_to_process = all_tweets if all_tweets else (response.data if response.data else [])
        
        if not tweets_to_process:
            logging.warning("No tweets found matching criteria.")
            return [], []
            
        # Create user lookup map (from first response, should have all users)
        users = {u.id: u for u in response.includes['users']} if response.includes and 'users' in response.includes else {}
        
        logging.info(f"Found {len(tweets_to_process)} tweets from API, processing and filtering...")
        
        filtered_count = 0
        retweet_count = 0
        total_processed = 0
        
        for post in tweets_to_process:
            total_processed += 1
            # Check if this is a retweet (should be filtered by query, but double-check)
            # In tweepy, referenced_tweets is a list of ReferencedTweet objects
            refs = post.referenced_tweets or []
            is_retweet = any(getattr(ref, 'type', None) == 'retweeted' for ref in refs)
            
            # Skip retweets (prioritize original posts)
            # Note: Quote tweets are allowed (they're original content with a reference)
            if is_retweet:
                retweet_count += 1
                logging.debug(f"Skipping retweet: {post.id}")
                continue
            
            # Filter: Only include posts that are actually about Tesla
            # For official Tesla accounts, be slightly more lenient (they're likely Tesla-related)
            author_data = users.get(post.author_id) if post.author_id else None
            author_username = author_data.username if author_data else "unknown"
            author_lower = author_username.lower()
            
            # Official Tesla accounts are more likely to be Tesla-related even without explicit keywords
            is_official_account = author_lower in ["tesla", "tesla_ai", "cybertruck", "teslacharging", "teslaenergy", "optimustesla", "gigatexas", "gigaberlin"]
            
            if not is_tesla_related(post.text):
                # For official accounts, be more lenient - include if it's from a Tesla account
                if not is_official_account:
                    filtered_count += 1
                    logging.debug(f"Skipping non-Tesla post from @{author_username}: {post.text[:50]}...")
                    continue
                else:
                    logging.debug(f"Including post from official Tesla account @{author_username} (lenient filtering)")
            
            metrics = post.public_metrics or {}
            engagement = (
                metrics.get('like_count', 0) * 1.0 +
                metrics.get('retweet_count', 0) * 3.0 +
                metrics.get('reply_count', 0) * 1.2 +
                metrics.get('quote_count', 0) * 2.5
            )

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

            # Boost original posts (non-retweets get additional priority)
            # Since we're filtering retweets, all posts here are original
            original_post_boost = 1.5  # Give original posts a boost

            score = engagement * recency * boost * original_post_boost

            post_data = {
                "id": str(post.id),
                "text": post.text,
                "username": author_username,
                "name": author_name,
                "url": f"https://x.com/{author_username}/status/{post.id}",
                "created_at": created_at.isoformat(),
                "likes": metrics.get('like_count', 0),
                "retweets": metrics.get('retweet_count', 0),
                "replies": metrics.get('reply_count', 0),
                "quotes": metrics.get('quote_count', 0),
                "final_score": round(score, 2),
                "is_retweet": False,  # All posts here are original (retweets filtered)
                "hours_old": round(hours_old, 1)
            }
            
            all_posts.append(post_data)

        logging.info(f"Processing summary:")
        logging.info(f"  - Total tweets from API: {total_processed}")
        logging.info(f"  - Retweets filtered out: {retweet_count}")
        logging.info(f"  - Non-Tesla content filtered out: {filtered_count}")
        logging.info(f"  - Tesla-related posts kept: {len(all_posts)}")
        
        if len(all_posts) < 10:
            logging.warning(f"⚠️  Only {len(all_posts)} posts found. Possible reasons:")
            logging.warning(f"    1. Limited Tesla content in the last 48 hours from these accounts")
            logging.warning(f"    2. Many posts might be retweets (excluded)")
            logging.warning(f"    3. Posts might not contain explicit Tesla keywords")
            logging.warning(f"    4. Query might be too restrictive")
            logging.warning(f"    Consider: Expanding time window, relaxing filters, or checking account activity")

    except ImportError:
        logging.error("tweepy not installed. Install it with: pip install tweepy")
        return [], []
    except Exception as e:
        logging.error(f"Error fetching X posts: {e}")
        import traceback
        traceback.print_exc()
        return [], []

    if not all_posts:
        return [], []

    # Sort by score
    all_posts.sort(key=lambda x: x['final_score'], reverse=True)
    
    # Remove duplicates by ID
    seen = set()
    unique = [p for p in all_posts if p['id'] not in seen and (seen.add(p['id']) or True)]

    # Limit posts per username (special case: TeslaCharging max 1, others max 4)
    MAX_POSTS_PER_USERNAME = 4
    MAX_POSTS_TESLACHARGING = 1
    username_counts = {}
    limited_posts = []
    
    for post in unique:
        username = post['username'].lower()
        count = username_counts.get(username, 0)
        
        # Special limit for TeslaCharging
        if username == "teslacharging":
            max_posts = MAX_POSTS_TESLACHARGING
        else:
            max_posts = MAX_POSTS_PER_USERNAME
        
        if count < max_posts:
            limited_posts.append(post)
            username_counts[username] = count + 1
        else:
            logging.debug(f"Skipping post from @{post['username']} (already have {max_posts} posts from this account)")

    top_25 = limited_posts[:25]
    raw_posts = all_posts.copy()

    logging.info(f"Returning {len(top_25)} best Tesla posts (from {len(raw_posts)} total, max {MAX_POSTS_PER_USERNAME} per username, max {MAX_POSTS_TESLACHARGING} for TeslaCharging)")

    return top_25, raw_posts


def print_posts_summary(top_posts: List[Dict], raw_posts: List[Dict]):
    """Print a formatted summary of the retrieved posts."""
    print("\n" + "="*80)
    print("TESLA X POSTS RETRIEVAL TEST RESULTS")
    print("="*80)
    print(f"\nTotal posts retrieved: {len(raw_posts)} (Tesla-related original posts only)")
    print(f"  - Retweets excluded")
    print(f"  - Non-Tesla content filtered out")
    print(f"  - Max 4 posts per username (max 1 for TeslaCharging)")
    print(f"Top posts (top 25): {len(top_posts)}")
    print("\n" + "-"*80)
    
    if top_posts:
        print("\nTOP POSTS (sorted by score):\n")
        for i, post in enumerate(top_posts[:10], 1):  # Show top 10
            print(f"{i}. @{post['username']} ({post['name']})")
            print(f"   Score: {post['final_score']}")
            print(f"   Engagement: {post['likes']} likes, {post['retweets']} retweets, {post['replies']} replies, {post.get('quotes', 0)} quotes")
            print(f"   Age: {post['hours_old']} hours old")
            print(f"   URL: {post['url']}")
            # Show first 150 chars of text
            text_preview = post['text'][:150] + "..." if len(post['text']) > 150 else post['text']
            print(f"   Text: {text_preview}")
            print()
    else:
        print("\nNo posts retrieved.")
    
    print("-"*80)
    print("\nPosts by account (in top results, max 4 per account):")
    account_counts = {}
    for post in top_posts:
        username = post['username']
        account_counts[username] = account_counts.get(username, 0) + 1
    
    if account_counts:
        for username, count in sorted(account_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  @{username}: {count} posts")
    else:
        print("  (no posts in top results)")
    
    print("\nTotal posts by account (before limiting):")
    all_account_counts = {}
    for post in raw_posts:
        username = post['username']
        all_account_counts[username] = all_account_counts.get(username, 0) + 1
    
    for username, count in sorted(all_account_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  @{username}: {count} posts")
    
    print("\n" + "="*80)


def main():
    """Main test function."""
    print("Testing Tesla X Posts Retrieval...")
    print(f"Trusted accounts: {', '.join(TRUSTED_USERNAMES)}")
    
    # Check for bearer token
    bearer_token = os.getenv("X_BEARER_TOKEN")
    if not bearer_token:
        print("\n❌ ERROR: X_BEARER_TOKEN not found in environment variables!")
        print("Please set X_BEARER_TOKEN in your .env file or environment.")
        sys.exit(1)
    
    print(f"✓ Bearer token found (length: {len(bearer_token)} chars)")
    
    # Fetch posts
    top_posts, raw_posts = fetch_top_x_posts_from_trusted_accounts()
    
    # Print summary
    print_posts_summary(top_posts, raw_posts)
    
    # Return success/failure
    if top_posts:
        print("\n✅ Test successful! Posts retrieved.")
        return 0
    else:
        print("\n⚠️  Warning: No posts were retrieved.")
        return 1


if __name__ == "__main__":
    sys.exit(main())

