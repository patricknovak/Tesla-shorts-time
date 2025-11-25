#!/usr/bin/env python3
"""
One-time script to add itunes:image tags to all existing episodes in the RSS feed.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

# Path to RSS feed
rss_path = Path(__file__).parent / "podcast.rss"
base_url = "https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main"

# Register namespace
ET.register_namespace("itunes", "http://www.itunes.com/dtds/podcast-1.0.dtd")

# Read RSS feed
with open(rss_path, "r", encoding="utf-8") as f:
    content = f.read()

# Fix namespace issues
content = content.replace('xmlns:ns0=', 'xmlns:itunes=')
content = content.replace('<ns0:', '<itunes:')
content = content.replace('</ns0:', '</itunes:')

# Parse
root = ET.fromstring(content.encode('utf-8'))
channel = root.find("channel")

# Ensure channel-level image exists
existing_channel_image = channel.find("itunes:image")
if existing_channel_image is None:
    itunes_image = ET.SubElement(channel, "itunes:image")
    itunes_image.set("href", f"{base_url}/podcast-image.jpg")
    print("Added channel-level itunes:image")
else:
    existing_channel_image.set("href", f"{base_url}/podcast-image.jpg")
    print("Updated channel-level itunes:image")

# Add image to all episodes
items = channel.findall("item")
updated_count = 0
for item in items:
    existing_image = item.find("itunes:image")
    if existing_image is None:
        item_image = ET.SubElement(item, "itunes:image")
        item_image.set("href", f"{base_url}/podcast-image.jpg")
        updated_count += 1
        title_elem = item.find("title")
        title = title_elem.text if title_elem is not None else "Unknown"
        print(f"Added itunes:image to: {title}")

print(f"\nUpdated {updated_count} episode(s) with itunes:image tags")

# Write back
tree = ET.ElementTree(root)
ET.indent(tree, space="  ")

with open(rss_path, "wb") as f:
    f.write('<?xml version="1.0" encoding="UTF-8"?>\n'.encode('utf-8'))
    tree.write(f, encoding="utf-8", xml_declaration=False)

# Post-process to fix namespace prefixes
with open(rss_path, "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace('xmlns:ns0="http://www.itunes.com/dtds/podcast-1.0.dtd"', 'xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"')
content = content.replace('<ns0:', '<itunes:')
content = content.replace('</ns0:', '</itunes:')

with open(rss_path, "w", encoding="utf-8") as f:
    f.write(content)

print(f"\nRSS feed updated: {rss_path}")

