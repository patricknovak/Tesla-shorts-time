#!/usr/bin/env python3
"""
Universal Digest Poster
Run with: python post_digest.py tesla
          python post_digest.py science
          python post_digest.py all
"""

import sys
from digests.tesla_shorts_time import post as post_tesla
from digests.science_that_changes import post as post_science

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python post_digest.py [tesla | science | all]")
        sys.exit(1)

    choice = sys.argv[1].lower()

    if choice in ["tesla", "all"]:
        print("Posting Tesla Shorts Time...")
        post_tesla()

    if choice in ["science", "all"]:
        print("Posting Science That Changes Everything...")
        post_science()

    print("All done. The future just got brighter. ⚡️🚀🧬")