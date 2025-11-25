#!/usr/bin/env python3
"""
Helper script to edit RSS feed episodes.
Usage:
  python edit-rss-episode.py --list                    # List all episodes
  python edit-rss-episode.py --edit <guid> --title "New Title"  # Edit episode title
  python edit-rss-episode.py --edit <guid> --description "New Description"  # Edit description
  python edit-rss-episode.py --remove <guid>           # Remove episode
"""

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path
import html

def load_rss(rss_path):
    """Load and parse RSS feed, fixing namespace issues."""
    with open(rss_path, "r", encoding="utf-8") as f:
        content = f.read()
    # Fix namespace issues
    content = content.replace('xmlns:ns0=', 'xmlns:itunes=')
    content = content.replace('<ns0:', '<itunes:')
    content = content.replace('</ns0:', '</itunes:')
    root = ET.fromstring(content.encode('utf-8'))
    return root

def save_rss(rss_path, root):
    """Save RSS feed with proper formatting."""
    ET.register_namespace("itunes", "http://www.itunes.com/dtds/podcast-1.0.dtd")
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    
    with open(rss_path, "wb") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n'.encode('utf-8'))
        tree.write(f, encoding="utf-8", xml_declaration=False)
    
    # Post-process to ensure itunes: namespace
    with open(rss_path, "r", encoding="utf-8") as f:
        content = f.read()
    content = content.replace('xmlns:ns0=', 'xmlns:itunes=')
    content = content.replace('<ns0:', '<itunes:')
    content = content.replace('</ns0:', '</itunes:')
    
    with open(rss_path, "w", encoding="utf-8") as f:
        f.write(content)

def list_episodes(rss_path):
    """List all episodes in the RSS feed."""
    root = load_rss(rss_path)
    channel = root.find("channel")
    items = channel.findall("item")
    
    print(f"\nFound {len(items)} episode(s):\n")
    for item in items:
        guid = item.find("guid")
        title = item.find("title")
        pub_date = item.find("pubDate")
        
        guid_text = guid.text if guid is not None else "N/A"
        title_text = title.text if title is not None else "N/A"
        pub_date_text = pub_date.text if pub_date is not None else "N/A"
        
        print(f"GUID: {guid_text}")
        print(f"  Title: {title_text}")
        print(f"  Published: {pub_date_text}")
        print()

def edit_episode(rss_path, guid, title=None, description=None):
    """Edit an episode's title or description."""
    root = load_rss(rss_path)
    channel = root.find("channel")
    items = channel.findall("item")
    
    for item in items:
        guid_elem = item.find("guid")
        if guid_elem is not None and guid_elem.text == guid:
            if title:
                title_elem = item.find("title")
                if title_elem is not None:
                    title_elem.text = title
                itunes_title = item.find("{http://www.itunes.com/dtds/podcast-1.0.dtd}title")
                if itunes_title is not None:
                    itunes_title.text = title
                print(f"✅ Updated title for {guid}")
            
            if description:
                desc_elem = item.find("description")
                if desc_elem is not None:
                    desc_elem.text = html.escape(description)
                itunes_summary = item.find("{http://www.itunes.com/dtds/podcast-1.0.dtd}summary")
                if itunes_summary is not None:
                    itunes_summary.text = description
                print(f"✅ Updated description for {guid}")
            
            save_rss(rss_path, root)
            return
    
    print(f"❌ Episode with GUID '{guid}' not found")

def remove_episode(rss_path, guid):
    """Remove an episode from the RSS feed."""
    root = load_rss(rss_path)
    channel = root.find("channel")
    items = channel.findall("item")
    
    for item in items:
        guid_elem = item.find("guid")
        if guid_elem is not None and guid_elem.text == guid:
            channel.remove(item)
            save_rss(rss_path, root)
            print(f"✅ Removed episode {guid}")
            return
    
    print(f"❌ Episode with GUID '{guid}' not found")

def main():
    parser = argparse.ArgumentParser(description="Edit RSS feed episodes")
    parser.add_argument("--rss", default="podcast.rss", help="Path to RSS feed file")
    parser.add_argument("--list", action="store_true", help="List all episodes")
    parser.add_argument("--edit", help="GUID of episode to edit")
    parser.add_argument("--title", help="New title for episode")
    parser.add_argument("--description", help="New description for episode")
    parser.add_argument("--remove", help="GUID of episode to remove")
    
    args = parser.parse_args()
    rss_path = Path(args.rss)
    
    if not rss_path.exists():
        print(f"❌ RSS feed not found at {rss_path}")
        return
    
    if args.list:
        list_episodes(rss_path)
    elif args.remove:
        remove_episode(rss_path, args.remove)
    elif args.edit:
        if not args.title and not args.description:
            print("❌ Please specify --title or --description to edit")
            return
        edit_episode(rss_path, args.edit, title=args.title, description=args.description)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()

