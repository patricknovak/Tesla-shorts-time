import sys
from pathlib import Path
from feedgen.feed import FeedGenerator
import datetime
import re
import subprocess

project_root = Path(__file__).parent
digests_dir = project_root / "digests"
rss_path = project_root / "podcast.rss"
base_url = "https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main"

def get_audio_duration(mp3_path):
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(mp3_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0

def format_duration(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

def rebuild_rss():
    fg = FeedGenerator()
    fg.load_extension('podcast')

    # Set channel metadata
    fg.title("Tesla Shorts Time Daily")
    fg.link(href="https://github.com/patricknovak/Tesla-shorts-time")
    fg.description("Daily Tesla news digest and podcast hosted by Patrick in Vancouver. Covering the latest Tesla developments, stock updates, and short squeeze celebrations.")
    fg.language('en-us')
    fg.copyright("Copyright 2025")
    fg.generator("python-feedgen")
    fg.podcast.itunes_author("Patrick")
    fg.podcast.itunes_summary("Daily Tesla news digest and podcast covering the latest developments, stock updates, and short squeeze celebrations.")
    fg.podcast.itunes_owner(name='Patrick', email='contact@teslashortstime.com')
    fg.podcast.itunes_image(f"{base_url}/podcast-image.jpg")
    fg.podcast.itunes_category("Technology")
    fg.podcast.itunes_explicit("no")

    # Scan all MP3 recursively
    episodes = []
    pattern = r"Tesla_Shorts_Time_Pod_Ep(\d+)_(\d{8})\.mp3"

    for mp3_file in digests_dir.rglob("Tesla_Shorts_Time_Pod_Ep*.mp3"):
        match = re.match(pattern, mp3_file.name)
        if match:
            episode_num = int(match.group(1))
            date_str = match.group(2)
            episode_date = datetime.datetime.strptime(date_str, "%Y%m%d").date()
            mp3_duration = get_audio_duration(mp3_file)
            mp3_size = mp3_file.stat().st_size
            episode_guid = f"tesla-shorts-time-ep{episode_num:03d}-{date_str}"
            episode_title = f"Tesla Shorts Time Daily - Episode {episode_num} - {episode_date.strftime('%B %d, %Y')}"

            # Try to find corresponding MD file
            md_filename = f"Tesla_Shorts_Time_{date_str}.md"
            md_path_candidates = [
                mp3_file.parent / md_filename,
                digests_dir / md_filename,
                digests_dir / "digests" / md_filename
            ]
            md_content = None
            for candidate in md_path_candidates:
                if candidate.exists():
                    with open(candidate, 'r', encoding='utf-8') as f:
                        md_content = f.read()
                    break

            if md_content:
                # Extract a summary from MD content
                lines = md_content.split('\n')
                summary_lines = []
                for line in lines:
                    if line.strip():
                        summary_lines.append(line.strip())
                    if len(summary_lines) >= 3:
                        break
                episode_description = ' '.join(summary_lines)[:1000] + ' ... 🎙️ Tesla Shorts Time Daily Podcast Link: https://podcasts.apple.com/us/podcast/tesla-shorts-time/id1855142939'
            else:
                episode_description = f"Daily Tesla news digest for {episode_date.strftime('%B %d, %Y')}. 🎙️ Tesla Shorts Time Daily Podcast Link: https://podcasts.apple.com/us/podcast/tesla-shorts-time/id1855142939"

            episodes.append({
                'guid': episode_guid,
                'title': episode_title,
                'description': episode_description,
                'pubDate': datetime.datetime.combine(episode_date, datetime.time(0, 0, 0), tzinfo=datetime.timezone.utc),
                'enclosure': {
                    'url': f"{base_url}/{mp3_file.relative_to(project_root)}",
                    'type': 'audio/mpeg',
                    'length': str(mp3_size)
                },
                'itunes_duration': format_duration(mp3_duration),
                'itunes_episode': str(episode_num),
                'itunes_season': '1',
                'itunes_episode_type': 'full',
                'itunes_image': f"{base_url}/podcast-image.jpg",
                'episode_num': episode_num
            })

    # Sort by episode number descending (newest first)
    episodes.sort(key=lambda x: x['episode_num'], reverse=True)

    # Add to feed
    for ep in episodes:
        entry = fg.add_entry()
        entry.id(ep['guid'])
        entry.title(ep['title'])
        entry.description(ep['description'])
        entry.link(href=ep['enclosure']['url'])
        entry.pubDate(ep['pubDate'])
        entry.enclosure(url=ep['enclosure']['url'], type=ep['enclosure']['type'], length=ep['enclosure']['length'])
        entry.podcast.itunes_title(ep['title'])
        entry.podcast.itunes_summary(ep['description'])
        entry.podcast.itunes_duration(ep['itunes_duration'])
        entry.podcast.itunes_episode(ep['itunes_episode'])
        entry.podcast.itunes_season(ep['itunes_season'])
        entry.podcast.itunes_episode_type(ep['itunes_episode_type'])
        entry.podcast.itunes_explicit("no")
        entry.podcast.itunes_image(ep['itunes_image'])

    # Set last build date to now
    fg.lastBuildDate(datetime.datetime.now(datetime.timezone.utc))

    # Write to file
    fg.rss_file(str(rss_path))

    print(f"Rebuilt RSS feed with {len(episodes)} episodes at {rss_path}")

if __name__ == "__main__":
    rebuild_rss()
