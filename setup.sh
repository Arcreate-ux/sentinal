#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_cmd git
require_cmd gh
require_cmd hf

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Run setup.sh from inside the SENTINEL git repository." >&2
  exit 1
fi

PROJECT_NAME="${PROJECT_NAME:-$(basename "$ROOT_DIR" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9-')}"
GH_REPO_NAME="${GH_REPO_NAME:-$PROJECT_NAME}"
HF_REPO_NAME="${HF_REPO_NAME:-$PROJECT_NAME}"
CURRENT_BRANCH="$(git branch --show-current 2>/dev/null || true)"
CURRENT_BRANCH="${CURRENT_BRANCH:-${BRANCH_NAME:-main}}"
DEPLOY_COMMIT_MESSAGE="${DEPLOY_COMMIT_MESSAGE:-deploy: update ${PROJECT_NAME} $(date -u +%Y-%m-%dT%H:%M:%SZ)}"
HF_TOKEN="${HF_TOKEN:-${HUGGINGFACE_TOKEN:-}}"
HF_SPACE_ID="${HF_SPACE_ID:-}"

stage_deploy_files() {
  git add -A -- \
    .dockerignore \
    .env.example \
    Dockerfile \
    LICENSE \
    README.md \
    bot \
    brain \
    config.py \
    health \
    main.py \
    notion_client \
    requirements.txt \
    scheduler \
    scripts/generate_research_dataset.py \
    sentinel \
    setup.sh \
    state
}

commit_if_needed() {
  stage_deploy_files
  if git diff --cached --quiet; then
    echo "No deployable changes to commit."
    return
  fi

  git commit -m "$DEPLOY_COMMIT_MESSAGE"
}

ensure_github_repo() {
  echo "Checking GitHub authentication..."
  if ! gh auth status -h github.com >/dev/null 2>&1; then
    echo "GitHub CLI is not authenticated. Run: gh auth login -h github.com" >&2
    exit 1
  fi

  if git remote get-url origin >/dev/null 2>&1; then
    echo "GitHub remote already configured: $(git remote get-url origin)"
    return
  fi

  if gh repo view "$GH_REPO_NAME" >/dev/null 2>&1; then
    repo_url="$(gh repo view "$GH_REPO_NAME" --json url --jq .url)"
    git remote add origin "$repo_url"
    echo "Attached existing GitHub repo as origin: $repo_url"
  else
    echo "Creating GitHub repo: $GH_REPO_NAME"
    gh repo create "$GH_REPO_NAME" \
      --private \
      --source . \
      --remote origin \
      --push
  fi
}

ensure_huggingface_space() {
  echo "Checking Hugging Face authentication..."
  if [[ -n "$HF_TOKEN" ]]; then
    hf auth login --token "$HF_TOKEN" --add-to-git-credential >/dev/null
  elif ! hf auth whoami >/dev/null 2>&1; then
    echo "Hugging Face CLI is not authenticated. Set HF_TOKEN or run: hf auth login --token <token> --add-to-git-credential" >&2
    exit 1
  fi

  hf_whoami_out="$(hf auth whoami 2>&1 || true)"
  hf_username="$(echo "$hf_whoami_out" | grep -i 'user' | awk -F'[:=]' '{print $2}' | tr -d ' ')"
  if [[ -z "$hf_username" ]]; then
    echo "Could not determine Hugging Face username from hf auth whoami. Output was: $hf_whoami_out" >&2
    exit 1
  fi

  if [[ -z "$HF_SPACE_ID" ]]; then
    HF_SPACE_ID="$hf_username/$HF_REPO_NAME"
  fi

  echo "Creating or reusing Hugging Face Space: $HF_SPACE_ID"
  if [[ -n "$HF_TOKEN" ]]; then
    hf repo create "$HF_SPACE_ID" \
      --repo-type space \
      --space-sdk docker \
      --private \
      --exist-ok \
      --token "$HF_TOKEN"
  else
    hf repo create "$HF_SPACE_ID" \
      --repo-type space \
      --space-sdk docker \
      --private \
      --exist-ok
  fi

  if ! git remote get-url hf >/dev/null 2>&1; then
    git remote add hf "https://huggingface.co/spaces/$HF_SPACE_ID"
    echo "Added Hugging Face git remote: https://huggingface.co/spaces/$HF_SPACE_ID"
  fi
}

push_branches() {
  echo "Pushing branch '$CURRENT_BRANCH' to GitHub..."
  git push origin "$CURRENT_BRANCH"

  echo "Pushing branch '$CURRENT_BRANCH' to Hugging Face..."
  git push hf "$CURRENT_BRANCH"
}

sync_huggingface_secrets() {
  echo "Syncing secrets to Hugging Face..."
  if [[ -f .env ]]; then
    hf spaces secrets add "$HF_SPACE_ID" --secrets-file .env >/dev/null
    echo "Secrets successfully synced to $HF_SPACE_ID."
  else
    echo "No .env file found. Skipping secrets sync."
  fi
}

echo "Starting SENTINEL deployment bootstrap..."
echo "Project: $PROJECT_NAME"
echo "Branch:  $CURRENT_BRANCH"

commit_if_needed
ensure_github_repo
ensure_huggingface_space
sync_huggingface_secrets
push_branches

echo "Deployment complete."
echo "GitHub: $(git remote get-url origin)"
echo "Hugging Face: $(git remote get-url hf)"
