#!/usr/bin/env python3
"""
Test script to verify X API authentication credentials.
Run this to check if your X API credentials are working correctly.
"""

import os
import sys
import logging
from dotenv import load_dotenv
import tweepy

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

# Load environment variables (try current directory and parent directory)
env_loaded = load_dotenv()  # Try current directory first
if not env_loaded:
    # Try parent directory (where .env usually is)
    parent_env = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    if os.path.exists(parent_env):
        load_dotenv(parent_env)
        print(f"✅ Loaded .env from parent directory: {parent_env}")
    else:
        # Try root directory
        root_env = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')
        if os.path.exists(root_env):
            load_dotenv(root_env)
            print(f"✅ Loaded .env from root directory: {root_env}")

# Get credentials from environment
CONSUMER_KEY = os.getenv("X_CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("X_CONSUMER_SECRET")
ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.getenv("X_ACCESS_TOKEN_SECRET")
BEARER_TOKEN = os.getenv("X_BEARER_TOKEN")

def test_oauth1():
    """Test OAuth 1.0a authentication."""
    print("\n" + "="*60)
    print("Testing OAuth 1.0a Authentication")
    print("="*60)
    
    if not all([CONSUMER_KEY, CONSUMER_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET]):
        print("❌ Missing OAuth 1.0a credentials:")
        if not CONSUMER_KEY:
            print("   - X_CONSUMER_KEY is missing")
        if not CONSUMER_SECRET:
            print("   - X_CONSUMER_SECRET is missing")
        if not ACCESS_TOKEN:
            print("   - X_ACCESS_TOKEN is missing")
        if not ACCESS_TOKEN_SECRET:
            print("   - X_ACCESS_TOKEN_SECRET is missing")
        return False
    
    try:
        # Create OAuth 1.0a client
        auth = tweepy.OAuth1UserHandler(
            CONSUMER_KEY,
            CONSUMER_SECRET,
            ACCESS_TOKEN,
            ACCESS_TOKEN_SECRET
        )
        client = tweepy.Client(
            consumer_key=CONSUMER_KEY,
            consumer_secret=CONSUMER_SECRET,
            access_token=ACCESS_TOKEN,
            access_token_secret=ACCESS_TOKEN_SECRET,
            wait_on_rate_limit=True
        )
        
        # Test authentication by getting user info
        print("✅ OAuth 1.0a client created successfully")
        print("   Testing authentication by fetching user info...")
        
        try:
            me = client.get_me()
            if me.data:
                print(f"✅ Authentication successful!")
                print(f"   Authenticated as: @{me.data.username} (ID: {me.data.id})")
                print(f"   Name: {me.data.name}")
                return True
            else:
                print("❌ Authentication failed: No user data returned")
                return False
        except tweepy.Unauthorized as e:
            print(f"❌ Authentication failed (401 Unauthorized): {e}")
            print("   This usually means:")
            print("   - Credentials are incorrect or expired")
            print("   - The API keys don't match the access tokens")
            print("   - The app doesn't have the required permissions")
            return False
        except tweepy.Forbidden as e:
            print(f"❌ Authentication failed (403 Forbidden): {e}")
            print("   This usually means the app doesn't have permission to access this resource")
            return False
        except Exception as e:
            print(f"❌ Authentication test failed: {e}")
            return False
            
    except Exception as e:
        print(f"❌ Failed to create OAuth 1.0a client: {e}")
        return False

def test_bearer_token():
    """Test Bearer Token authentication."""
    print("\n" + "="*60)
    print("Testing Bearer Token Authentication")
    print("="*60)
    
    if not BEARER_TOKEN:
        print("⚠️  X_BEARER_TOKEN is not set (optional but recommended)")
        return None
    
    try:
        # Create Bearer Token client
        client = tweepy.Client(
            bearer_token=BEARER_TOKEN,
            wait_on_rate_limit=True
        )
        
        print("✅ Bearer Token client created successfully")
        print("   Testing authentication by fetching user info...")
        
        try:
            # Bearer token can't get user info, so test with a search instead
            print("   Testing with a simple search query...")
            tweets = client.search_recent_tweets(
                query="Tesla -is:retweet lang:en",
                max_results=10,
                tweet_fields=["created_at", "text"]
            )
            
            if tweets.data:
                print(f"✅ Bearer Token authentication successful!")
                print(f"   Found {len(tweets.data)} tweets")
                return True
            else:
                print("⚠️  Bearer Token works but no tweets returned (this is OK)")
                return True
                
        except tweepy.Unauthorized as e:
            print(f"❌ Bearer Token authentication failed (401 Unauthorized): {e}")
            print("   The Bearer Token may be incorrect or expired")
            return False
        except tweepy.Forbidden as e:
            print(f"❌ Bearer Token authentication failed (403 Forbidden): {e}")
            print("   The Bearer Token doesn't have search permissions")
            return False
        except Exception as e:
            print(f"❌ Bearer Token test failed: {e}")
            return False
            
    except Exception as e:
        print(f"❌ Failed to create Bearer Token client: {e}")
        return False

def test_search():
    """Test search functionality (what the main script uses)."""
    print("\n" + "="*60)
    print("Testing Search Functionality")
    print("="*60)
    
    # Try OAuth 1.0a first (what the main script uses)
    if all([CONSUMER_KEY, CONSUMER_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET]):
        try:
            client = tweepy.Client(
                consumer_key=CONSUMER_KEY,
                consumer_secret=CONSUMER_SECRET,
                access_token=ACCESS_TOKEN,
                access_token_secret=ACCESS_TOKEN_SECRET,
                wait_on_rate_limit=True
            )
            
            print("Testing search with OAuth 1.0a...")
            query = "(Tesla OR TSLA OR \"Elon Musk\" OR $TSLA OR \"Tesla FSD\" OR Cybertruck OR Robotaxi) -is:retweet -is:reply lang:en"
            
            tweets = client.search_recent_tweets(
                query=query,
                max_results=10,
                tweet_fields=["created_at", "public_metrics", "author_id", "text"],
                user_fields=["username", "name"],
                expansions=["author_id"]
            )
            
            if tweets.data:
                print(f"✅ Search successful! Found {len(tweets.data)} tweets")
                print(f"   Sample tweet: {tweets.data[0].text[:100]}...")
                return True
            else:
                print("⚠️  Search worked but no tweets returned")
                return True
                
        except tweepy.Unauthorized as e:
            print(f"❌ Search failed (401 Unauthorized): {e}")
            print("   OAuth 1.0a credentials don't have search permissions")
            return False
        except tweepy.Forbidden as e:
            print(f"❌ Search failed (403 Forbidden): {e}")
            print("   The API credentials don't have permission to search")
            return False
        except Exception as e:
            print(f"❌ Search test failed: {e}")
            return False
    else:
        print("❌ Cannot test search: OAuth 1.0a credentials missing")
        return False

def main():
    print("\n" + "="*60)
    print("X API Authentication Test")
    print("="*60)
    print("\nThis script will test your X API credentials to verify they work correctly.")
    print("Make sure your .env file is in the same directory with all credentials set.\n")
    
    # Check if credentials are loaded
    if not any([CONSUMER_KEY, CONSUMER_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET, BEARER_TOKEN]):
        print("❌ No X API credentials found!")
        print("   Please ensure your .env file exists with your X API credentials:")
        print("   X_CONSUMER_KEY=...")
        print("   X_CONSUMER_SECRET=...")
        print("   X_ACCESS_TOKEN=...")
        print("   X_ACCESS_TOKEN_SECRET=...")
        print("   X_BEARER_TOKEN=... (optional)")
        print("\n   The script will look for .env in:")
        print("   - Current directory (digests/)")
        print("   - Parent directory (tesla_shorts_time/)")
        print("   - Root directory")
        return
    
    # Test OAuth 1.0a
    oauth_success = test_oauth1()
    
    # Test Bearer Token
    bearer_success = test_bearer_token()
    
    # Test search (what the main script actually uses)
    search_success = test_search()
    
    # Summary
    print("\n" + "="*60)
    print("Test Summary")
    print("="*60)
    
    if oauth_success:
        print("✅ OAuth 1.0a: Working")
    else:
        print("❌ OAuth 1.0a: Failed")
    
    if bearer_success is True:
        print("✅ Bearer Token: Working")
    elif bearer_success is False:
        print("❌ Bearer Token: Failed")
    else:
        print("⚠️  Bearer Token: Not configured")
    
    if search_success:
        print("✅ Search: Working")
    else:
        print("❌ Search: Failed")
    
    print("\n" + "="*60)
    if oauth_success and search_success:
        print("✅ All critical tests passed! Your X API credentials are working.")
        print("   The main script should be able to fetch X posts successfully.")
    else:
        print("❌ Some tests failed. Please check your credentials:")
        print("   1. Verify all credentials in your .env file")
        print("   2. Make sure you're using credentials for @teslashortstime account")
        print("   3. Check that the API app has 'Read' permissions")
        print("   4. For Premium+ accounts, ensure search is enabled")
        print("   5. Regenerate credentials if they're expired")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()

