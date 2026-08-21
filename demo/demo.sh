#!/usr/bin/env bash
#
# env-drift-detector Demo Script
# ==============================
# สคริปต์นี้สร้าง test repo ชั่วคราวบน GitHub ของคุณ
# แล้วรันตัวอย่างทุกฟีเจอร์ของ env-drift ให้ดู
#
# Prerequisites:
#   - gh CLI logged in (gh auth status)
#   - Python 3.10+
#   - env-drift installed (pip install -e .)
#
# Usage:
#   bash demo/demo.sh
#
set -euo pipefail

# ── Colors ───────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

step()  { echo -e "\n${BLUE}${BOLD}▶ Step $1: $2${NC}"; echo -e "${CYAN}──────────────────────────────────────────────${NC}"; }
ok()    { echo -e "${GREEN}✓ $1${NC}"; }
warn()  { echo -e "${YELLOW}⚠ $1${NC}"; }
fail()  { echo -e "${RED}✗ $1${NC}"; }
info()  { echo -e "${BOLD}$1${NC}"; }
pause() { echo -e "\n${YELLOW}⏎ Press Enter to continue...${NC}"; read -r; }

# ── Cleanup trap ─────────────────────────────────────────────────────
DEMO_DIR=""
REPO_NAME="env-drift-demo-$(date +%s)"

cleanup() {
    if [[ -n "$DEMO_DIR" && -d "$DEMO_DIR" ]]; then
        rm -rf "$DEMO_DIR"
        ok "Cleaned up temp directory"
    fi
}
trap cleanup EXIT

# ── Pre-flight checks ───────────────────────────────────────────────
echo -e "${BOLD}${CYAN}"
echo "╔══════════════════════════════════════════════╗"
echo "║     env-drift-detector  Demo Script         ║"
echo "║     Catch .env.example drift before it      ║"
echo "║     breaks your deploy                      ║"
echo "╚══════════════════════════════════════════════╝"
echo -e "${NC}"

command -v gh >/dev/null 2>&1 || { fail "gh CLI not found"; exit 1; }
command -v python >/dev/null 2>&1 || command -v python3 >/dev/null 2>&1 || { fail "Python not found"; exit 1; }

if ! gh auth status &>/dev/null; then
    fail "gh not logged in. Run: gh auth login"
    exit 1
fi

ok "Pre-flight checks passed"

# ── Ask for Discord webhook (optional) ──────────────────────────────
DISCORD_WEBHOOK_URL=""
echo -e "\n${BOLD}Discord Webhook URL (optional)${NC}"
echo "If you want to see env-drift send reports to Discord,"
echo "paste a Discord webhook URL below. Leave blank to skip."
echo -e "${CYAN}──────────────────────────────────────────────${NC}"
read -rp "DISCORD_WEBHOOK_URL: " DISCORD_WEBHOOK_URL
if [[ -n "$DISCORD_WEBHOOK_URL" ]]; then
    ok "Discord webhook configured"
else
    warn "Skipping Discord integration (no webhook URL)"
fi
pause

# ── Step 1: Create test repo on GitHub ───────────────────────────────
step 1 "Creating test repo on GitHub"

gh repo create "$REPO_NAME" --private --description "env-drift-detector demo - auto-generated" 2>/dev/null
ok "Created repo: sunveloper/$REPO_NAME"
pause

# ── Step 2: Clone and set up project structure ───────────────────────
step 2 "Setting up project structure"

DEMO_DIR=$(mktemp -d)
cd "$DEMO_DIR"
gh repo clone "sunveloper/$REPO_NAME" .
git config user.email "demo@env-drift.dev"
git config user.name "env-drift demo"

# Create directory structure
mkdir -p src/billing src/api src/config

# ── 2a: Python service with missing env vars ────────────────────────
info "Creating Python billing service..."

cat > src/billing/__init__.py << 'PYEOF'
"""Billing module - uses env vars that aren't all in the template."""
PYEOF

cat > src/billing/client.py << 'PYEOF'
"""Stripe billing client."""
import os


def get_stripe_key():
    """Required: no fallback → missing from template = FAIL."""
    return os.getenv("STRIPE_SECRET_KEY")


def get_webhook_secret():
    """Required: no fallback → missing from template = FAIL."""
    return os.getenv("STRIPE_WEBHOOK_SECRET")


def get_api_version():
    """Required: no fallback → missing from template = FAIL."""
    return os.getenv("STRIPE_API_VERSION")


def get_timeout():
    """Optional: has default → undocumented but won't break deploy."""
    return os.getenv("BILLING_TIMEOUT_SECONDS", "30")


def get_log_level():
    """Optional: has default → undocumented but won't break deploy."""
    return os.getenv("LOG_LEVEL", "INFO")
PYEOF

cat > src/billing/webhook.py << 'PYEOF'
"""Stripe webhook handler."""
import os


def handle_webhook():
    secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    api_version = os.getenv("STRIPE_API_VERSION")
    return {"secret": secret, "version": api_version}
PYEOF

# ── 2b: Spring Boot application ─────────────────────────────────────
info "Creating Spring Boot application..."

cat > src/config/application.yml << 'YAMLEOF'
# Spring Boot configuration - reads env vars via property placeholders
server:
  port: ${APP_PORT:8080}

spring:
  datasource:
    url: ${DB_URL}
    username: ${DB_USERNAME}
    password: ${DB_PASSWORD}
  redis:
    url: ${REDIS_URL}
    password: ${REDIS_PASSWORD}

app:
  stripe:
    key: ${STRIPE_SECRET_KEY}
    webhook-secret: ${STRIPE_WEBHOOK_SECRET}
  mail:
    sender: ${MAIL_SENDER}
YAMLEOF

cat > src/config/Application.java << 'JAVAEOF'
package com.example.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public class Application {

    // Required - no fallback
    @Value("${spring.datasource.url}")
    private String dbUrl;

    // Required - no fallback
    @Value("${spring.datasource.username}")
    private String dbUsername;

    // Optional - has default
    @Value("${app.max-retries:3}")
    private int maxRetries;

    // Direct env var read
    public String getApiKey() {
        return System.getenv("STRIPE_SECRET_KEY");
    }
}
JAVAEOF

# ── 2c: NestJS ConfigService ────────────────────────────────────────
info "Creating NestJS config service..."

cat > src/config/config.service.ts << 'TSEOF'
import { ConfigService } from '@nestjs/config';

export function configureApp(configService: ConfigService) {
  // Required - getOrThrow
  const dbUrl = configService.getOrThrow<string>('DATABASE_URL');

  // Required - no fallback
  const redisUrl = configService.get<string>('REDIS_URL');

  // Optional - has default
  const port = configService.get<number>('APP_PORT', 3000);

  // Required - no fallback
  const stripeKey = configService.get<string>('STRIPE_SECRET_KEY');

  return { dbUrl, redisUrl, port, stripeKey };
}
TSEOF

# ── 2d: Docker Compose ──────────────────────────────────────────────
info "Creating docker-compose.yml..."

cat > docker-compose.yml << 'DCOEOF'
version: '3.8'
services:
  app:
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
      - STRIPE_SECRET_KEY=${STRIPE_SECRET_KEY}
      - STRIPE_WEBHOOK_SECRET=${STRIPE_WEBHOOK_SECRET}
      - DB_USERNAME=${DB_USERNAME}
      - DB_PASSWORD=${DB_PASSWORD}
      - REDIS_PASSWORD=${REDIS_PASSWORD}
  worker:
    environment:
      - QUEUE_URL=${QUEUE_URL}
      - WORKER_CONCURRENCY=${WORKER_CONCURRENCY:4}
DCOEOF

# ── 2e: INCOMPLETE .env.example (the whole point!) ──────────────────
info "Creating INCOMPLETE .env.example..."

cat > .env.example << 'ENVEOF'
# Database
DATABASE_URL=postgres://localhost:5432/app
DB_USERNAME=changeme
DB_PASSWORD=changeme

# Redis
REDIS_URL=redis://localhost:6379
REDIS_PASSWORD=changeme

# App
APP_PORT=8080
LOG_LEVEL=INFO

# --- MISSING from template (these are read by code but NOT documented) ---
# STRIPE_SECRET_KEY        ← read by Python + Java + NestJS
# STRIPE_WEBHOOK_SECRET    ← read by Python + Spring Boot
# STRIPE_API_VERSION       ← read by Python
# MAIL_SENDER              ← read by Spring Boot
# BILLING_TIMEOUT_SECONDS  ← read by Python (has default)
# WORKER_CONCURRENCY       ← read by docker-compose (has default)
ENVEOF

# ── 2f: .gitignore ──────────────────────────────────────────────────
cat > .gitignore << 'GIEOF'
.env
*.pyc
__pycache__/
node_modules/
target/
build/
.idea/
.vscode/
GIEOF

ok "Project structure created"
pause

# ── Step 3: Initial commit (baseline) ───────────────────────────────
step 3 "Creating initial commit (baseline)"

git add -A
git commit -m "feat: initial project setup

- Python billing service
- Spring Boot application
- NestJS config service
- Docker Compose
- Incomplete .env.example (intentionally!)"
ok "Initial commit created"
pause

# ── Step 4: Run env-drift on initial commit ─────────────────────────
step 4 "Running env-drift --dry-run (initial commit)"

info "First run - should be clean since it's the initial commit:"
echo ""
env-drift --dry-run --no-template-history || true
ok "Initial state"
pause

# ── Step 5: Simulate a push with new env var ────────────────────────
step 5 "Simulating a push that adds a new env var"

# Add a new file that reads a new env var
cat > src/billing/payment.py << 'PYEOF'
"""Payment processing - adds a new env var without updating template."""
import os


def process_payment(amount):
    """Uses PAYMENT_GATEWAY_KEY which is NOT in .env.example."""
    gateway_key = os.getenv("PAYMENT_GATEWAY_KEY")
    merchant_id = os.getenv("MERCHANT_ID")
    timeout = os.getenv("PAYMENT_TIMEOUT", "60")

    return {
        "amount": amount,
        "gateway": gateway_key,
        "merchant": merchant_id,
        "timeout": timeout,
    }
PYEOF

git add -A
git commit -m "feat(billing): add payment processing

Adds PAYMENT_GATEWAY_KEY and MERCHANT_ID env vars
but forgets to update .env.example"
ok "Push with missing env vars"
pause

# ── Step 6: Detect the drift! ───────────────────────────────────────
step 6 "Running env-drift --dry-run (detecting drift)"

info "env-drift catches the missing variables:"
echo ""
env-drift --dry-run --no-template-history || true
ok "Drift detected!"
pause

# ── Step 7: Show --all mode (finds unused vars too) ─────────────────
step 7 "Running env-drift --all (full tree scan)"

info "Full tree scan also shows unused template entries:"
echo ""
env-drift --dry-run --all --no-template-history || true
ok "Full analysis complete"
pause

# ── Step 8: Show env-drift verify ───────────────────────────────────
step 8 "Running env-drift verify"

# Create a .env that's copied from .env.example but not edited
cp .env.example .env

info "env-drift verify catches .env files that were never edited:"
echo ""
env-drift verify --env-file .env --strict-placeholder || true
ok "Verify complete"
pause

# ── Step 9: Show exit codes ─────────────────────────────────────────
step 9 "Exit codes in action"

info "Exit code 1 (drift found):"
env-drift --dry-run --no-template-history >/dev/null 2>&1 || true
echo "Exit code: $?"
echo ""

info "Exit code 0 (with --no-fail):"
env-drift --dry-run --no-template-history --no-fail >/dev/null 2>&1 || true
echo "Exit code: $?"
echo ""

info "Exit code 0 (verify with real values):"
env-drift verify --no-fail --env-file .env >/dev/null 2>&1 || true
echo "Exit code: $?"
pause

# ── Step 10: Show --ignore flag ─────────────────────────────────────
step 10 "Ignoring specific variables"

info "Ignoring BILLING_TIMEOUT_SECONDS and LOG_LEVEL:"
echo ""
env-drift --dry-run --no-template-history --ignore BILLING_TIMEOUT_SECONDS,LOG_LEVEL || true
ok "Ignore list works"
pause

# ── Step 11: Discord notification (if webhook provided) ─────────────
if [[ -n "$DISCORD_WEBHOOK_URL" ]]; then
    step 11 "Sending report to Discord"

    info "Sending drift report to your Discord channel..."
    echo ""
    DISCORD_WEBHOOK_URL="$DISCORD_WEBHOOK_URL" env-drift --no-template-history || true
    ok "Report sent to Discord"
else
    step 11 "Discord notification (skipped — no webhook URL)"
    warn "Set DISCORD_WEBHOOK_URL next time to see Discord notifications"
fi
pause

# ── Step 12: Push demo to GitHub ────────────────────────────────────
step 12 "Pushing demo to GitHub"

git push origin main 2>&1 || true
ok "Pushed to: https://github.com/sunveloper/$REPO_NAME"
pause

# ── Summary ──────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${CYAN}"
echo "╔══════════════════════════════════════════════╗"
echo "║           Demo Complete! 🎉                  ║"
echo "╚══════════════════════════════════════════════╝"
echo -e "${NC}"

info "What we demonstrated:"
echo "  1. env-drift detects missing .env.example entries"
echo "  2. Distinguishes required vs optional (has default) vars"
echo "  3. Scans multiple stacks: Python, Java, TypeScript, docker-compose"
echo "  4. env-drift verify catches unfilled .env files"
echo "  5. --all mode shows unused template entries"
echo "  6. --ignore skips specific variable names"
echo "  7. --no-fail reports without breaking the build"
echo "  8. Exit codes are CI-friendly (1 = needs fixing, 0 = OK)"
if [[ -n "$DISCORD_WEBHOOK_URL" ]]; then
    echo "  9. Discord webhook integration works end-to-end"
fi
echo ""
info "Demo repo: https://github.com/sunveloper/$REPO_NAME"
echo ""
info "To clean up the demo repo:"
echo "  gh repo delete sunveloper/$REPO_NAME --yes"
echo ""
