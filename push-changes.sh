#!/bin/bash
# Helper script to push code changes to git repository
# Usage: ./push-changes.sh "Your commit message"

set -e

# Check if commit message is provided
if [ -z "$1" ]; then
    echo "Usage: ./push-changes.sh 'Your commit message'"
    exit 1
fi

COMMIT_MSG="$1"

# Get the repository root (assuming script is in root)
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

# Show current status
echo "📋 Current git status:"
git status --short

# Ask for confirmation
read -p "Do you want to stage all changes and commit? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 1
fi

# Stage all changes
echo "📦 Staging changes..."
git add .

# Show what will be committed
echo ""
echo "📝 Changes to be committed:"
git diff --cached --stat

# Commit
echo ""
echo "💾 Committing with message: '$COMMIT_MSG'"
git commit -m "$COMMIT_MSG"

# Pull latest changes before pushing (in case GitHub Actions or others pushed)
echo ""
echo "📥 Checking for remote changes..."
if git fetch origin; then
    LOCAL=$(git rev-parse @)
    REMOTE=$(git rev-parse @{u})
    if [ "$LOCAL" != "$REMOTE" ]; then
        echo "⚠️  Remote has new changes. Pulling with rebase..."
        git pull --rebase
    else
        echo "✅ Local is up to date with remote."
    fi
fi

# Push
echo ""
echo "🚀 Pushing to remote..."
if git push; then
    echo ""
    echo "✅ Done! Changes have been pushed to the repository."
else
    echo ""
    echo "❌ Push failed. This might happen if:"
    echo "   - Remote has new changes (try running: git pull --rebase && git push)"
    echo "   - Network issues"
    echo "   - Permission problems"
    exit 1
fi

