# GitHub Actions Setup Guide

This guide will help you set up automated daily runs of the Tesla Shorts Time script using GitHub Actions.

## Prerequisites

1. A GitHub repository with this code
2. All required API keys and tokens

## Step 1: Add GitHub Secrets

Go to your repository → Settings → Secrets and variables → Actions → New repository secret

Add the following secrets:

### Required Secrets:
- `GROK_API_KEY` - Your Grok/X.AI API key
- `ELEVENLABS_API_KEY` - Your ElevenLabs API key for TTS

### Optional (if X posting is enabled):
- `X_CONSUMER_KEY` - Twitter/X API consumer key
- `X_CONSUMER_SECRET` - Twitter/X API consumer secret  
- `X_ACCESS_TOKEN` - Twitter/X API access token
- `X_ACCESS_TOKEN_SECRET` - Twitter/X API access token secret

## Step 2: Add Music File (Optional)

If you want background music in your podcast:
1. Add `tesla_shorts_time.mp3` to the root of your repository
2. The workflow will automatically use it if present

## Step 3: Configure Schedule

Edit `.github/workflows/daily-podcast.yml` to adjust the schedule:

```yaml
schedule:
  - cron: '0 8 * * *'  # 8:00 AM UTC daily
```

Cron format: `minute hour day month day-of-week`
- `0 8 * * *` = 8:00 AM UTC every day
- `0 12 * * *` = 12:00 PM UTC every day
- `0 0 * * 1-5` = Midnight UTC, Monday-Friday only

## Step 4: Test the Workflow

1. Go to Actions tab in your repository
2. Click "Tesla Shorts Time Daily" workflow
3. Click "Run workflow" → "Run workflow" (manual trigger)
4. Watch it run and check for errors

## Step 5: Monitor Results

After each run:
- Generated files are automatically committed to the repository
- **Files are published to:** `digests/` folder in your repository
- Check the `digests/` folder for:
  - `Tesla_Shorts_Time_YYYYMMDD.md` - The X thread/digest
  - `Tesla_Shorts_Time_Pod_EpXXX_YYYYMMDD.mp3` - The podcast audio
  - `podcast_transcript_YYYYMMDD.txt` - The podcast script

**Where to find them on GitHub:**
1. Go to your repository on GitHub
2. Navigate to the `digests/digests/` folder
3. You'll see all the generated files committed by the workflow
4. Each commit will have a message like "Auto-generated: Tesla Shorts Time YYYY-MM-DD"

## Troubleshooting

### Workflow fails with "Missing API key"
- Double-check all secrets are set correctly in GitHub Settings → Secrets

### Audio processing fails
- Ensure ffmpeg is installed (the workflow installs it automatically)
- Check that the music file exists if you're using background music

### X posting fails
- Verify X API credentials are correct
- Check that `ENABLE_X_POSTING = True` in the script

### Files not being committed
- Check that the workflow has write permissions
- Go to Settings → Actions → General → Workflow permissions
- Select "Read and write permissions"

## Manual Run

You can manually trigger the workflow anytime:
1. Go to Actions tab
2. Select "Tesla Shorts Time Daily"
3. Click "Run workflow"
4. Click the green "Run workflow" button

