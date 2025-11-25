# GitHub Pages Setup Guide

This guide will help you set up GitHub Pages to host your podcast player publicly.

## Quick Setup Steps

### 1. Push the Files to GitHub

The following files are already created and ready:
- `index.html` - Main podcast player page
- `podcast-player.html` - Alternative page (same content)

Make sure these files are committed and pushed to your repository.

### 2. Enable GitHub Pages

1. Go to your GitHub repository: `https://github.com/patricknovak/Tesla-shorts-time`
2. Click on **Settings** (top menu)
3. Scroll down to **Pages** in the left sidebar
4. Under **Source**, select:
   - **Branch**: `main` (or `master`)
   - **Folder**: `/ (root)`
5. Click **Save**

### 3. Wait for Deployment

- GitHub Pages will take 1-2 minutes to deploy
- You'll see a green checkmark when it's ready
- Your site will be available at: `https://patricknovak.github.io/Tesla-shorts-time/`

### 4. Custom Domain (Optional)

If you want to use a custom domain (e.g., `teslashortstime.com`):

1. In the GitHub Pages settings, add your custom domain
2. Update your DNS records to point to GitHub Pages
3. GitHub will automatically configure HTTPS for your domain

## Features

The podcast player includes:

✅ **Auto-loading episodes** from your RSS feed  
✅ **Beautiful, responsive design** that works on all devices  
✅ **Play/pause controls** with progress bar  
✅ **Seek functionality** - click anywhere on the progress bar  
✅ **Auto-refresh** - checks for new episodes every 5 minutes  
✅ **Episode metadata** - titles, dates, descriptions, durations  
✅ **Links to** RSS feed, Apple Podcasts, and GitHub  

## Troubleshooting

### Site Not Loading
- Wait 2-3 minutes after enabling Pages
- Check that `index.html` exists in the root directory
- Verify the branch is set to `main` (or `master`)

### Episodes Not Showing
- Check that `podcast.rss` is accessible at the raw GitHub URL
- Verify the RSS feed is valid XML
- Check browser console for JavaScript errors

### Audio Not Playing
- Verify MP3 files are accessible via the raw GitHub URLs
- Check browser console for CORS or network errors
- Some browsers may block autoplay - users need to click play

## Updating the Player

The player automatically reads from your RSS feed, so:
- **No manual updates needed** - new episodes appear automatically
- The page refreshes every 5 minutes to check for new episodes
- Users can manually refresh the page to see updates immediately

## Public Access

Once enabled, your podcast player will be publicly accessible at:
- `https://patricknovak.github.io/Tesla-shorts-time/`
- Anyone can visit and listen to your podcasts
- No login or authentication required
- Works on desktop, tablet, and mobile devices

