# GitHub Repository Setup Guide

Your local code is not yet connected to a GitHub repository. Follow these steps to create one and connect it.

## Step 1: Create a GitHub Repository

1. Go to [GitHub.com](https://github.com) and sign in
2. Click the **"+"** icon in the top right → **"New repository"**
3. Fill in:
   - **Repository name**: `tesla-shorts-time` (or any name you prefer)
   - **Description**: "Automated daily Tesla news digest and podcast"
   - **Visibility**: Choose **Private** (recommended) or **Public**
   - **DO NOT** initialize with README, .gitignore, or license (we already have these)
4. Click **"Create repository"**

## Step 2: Connect Your Local Code to GitHub

After creating the repository, GitHub will show you commands. Use these (replace `YOUR_USERNAME` with your GitHub username):

```bash
cd /Users/patricknovak/Documents/Coding/tesla_shorts_time

# Add all files
git add .

# Make initial commit
git commit -m "Initial commit: Tesla Shorts Time automation"

# Add the GitHub repository as remote (replace YOUR_USERNAME and REPO_NAME)
git remote add origin https://github.com/YOUR_USERNAME/REPO_NAME.git

# Push to GitHub
git branch -M main
git push -u origin main
```

## Step 3: Add GitHub Secrets

Once your code is on GitHub:

1. Go to your repository on GitHub
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **"New repository secret"** and add:
   - `GROK_API_KEY`
   - `ELEVENLABS_API_KEY`
   - `X_CONSUMER_KEY` (if X posting enabled)
   - `X_CONSUMER_SECRET` (if X posting enabled)
   - `X_ACCESS_TOKEN` (if X posting enabled)
   - `X_ACCESS_TOKEN_SECRET` (if X posting enabled)

## Step 4: Enable Workflow Permissions

1. In your repository, go to **Settings** → **Actions** → **General**
2. Scroll to **"Workflow permissions"**
3. Select **"Read and write permissions"**
4. Click **Save**

## Step 5: Test the Workflow

1. Go to the **Actions** tab in your repository
2. You should see "Tesla Shorts Time Daily" workflow
3. Click **"Run workflow"** → **"Run workflow"** to test it manually

## Step 6: Find Your Generated Files

After the workflow runs, files will be in:
- **Repository** → `digests/digests/` folder
- Look for commits with message: `"Auto-generated: Tesla Shorts Time YYYY-MM-DD"`

---

**Note**: The workflow will only work once your code is pushed to GitHub and secrets are configured!



