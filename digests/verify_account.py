#!/usr/bin/env python3
"""
Quick script to verify which X account your credentials are for.
"""

import os
import sys
from dotenv import load_dotenv
import tweepy

# Load from parent directory
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

CONSUMER_KEY = os.getenv("X_CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("X_CONSUMER_SECRET")
ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.getenv("X_ACCESS_TOKEN_SECRET")

if not all([CONSUMER_KEY, CONSUMER_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET]):
    print("❌ Missing credentials in .env file")
    sys.exit(1)

try:
    client = tweepy.Client(
        consumer_key=CONSUMER_KEY,
        consumer_secret=CONSUMER_SECRET,
        access_token=ACCESS_TOKEN,
        access_token_secret=ACCESS_TOKEN_SECRET,
    )
    
    me = client.get_me()
    if me.data:
        print(f"\n✅ Current credentials are for:")
        print(f"   Username: @{me.data.username}")
        print(f"   Name: {me.data.name}")
        print(f"   ID: {me.data.id}")
        
        if me.data.username.lower() == "teslashortstime":
            print("\n✅ CORRECT! These are @teslashortstime credentials.")
        else:
            print(f"\n❌ WRONG ACCOUNT! These are for @{me.data.username}, not @teslashortstime")
            print("   Please update your .env file with @teslashortstime credentials.")
    else:
        print("❌ Could not get user info")
        
except Exception as e:
    print(f"❌ Error: {e}")

