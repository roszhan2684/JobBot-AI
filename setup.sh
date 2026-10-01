#!/bin/bash
# JobBot AI — One-command setup script
set -e

echo ""
echo "============================================"
echo "  JobBot AI — Setup"
echo "============================================"
echo ""

# Check Python version
PYTHON_VERSION=$(python3 -c 'import sys; print(sys.version_info.major * 10 + sys.version_info.minor)')
if [ "$PYTHON_VERSION" -lt "310" ]; then
  echo "ERROR: Python 3.10+ is required. You have: $(python3 --version)"
  exit 1
fi

echo "✓ Python $(python3 --version)"

# Create virtual environment
if [ ! -d "venv" ]; then
  echo "→ Creating virtual environment..."
  python3 -m venv venv
fi

# Activate
source venv/bin/activate
echo "✓ Virtual environment activated"

# Install dependencies
echo "→ Installing Python packages..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "✓ Packages installed"

# Install Playwright browsers
echo "→ Installing Playwright Chromium browser..."
playwright install chromium
playwright install-deps chromium 2>/dev/null || true
echo "✓ Playwright ready"

# Create .env if missing
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo ""
  echo "⚠  Created .env — YOU MUST add your ANTHROPIC_API_KEY"
fi

# Create screenshots dir
mkdir -p screenshots cookies logs

echo ""
echo "============================================"
echo "  Setup Complete!"
echo "============================================"
echo ""
echo "NEXT STEPS:"
echo ""
echo "1. Edit config.yaml:"
echo "   - Fill in YOUR name, email, phone, location"
echo "   - Add your RESUME TEXT in the resume_text field"
echo "   - Copy your resume.pdf into this folder"
echo "   - Set your target job titles and keywords"
echo "   - Add credentials for LinkedIn, Indeed, Dice"
echo "   - Choose which job_sources to enable"
echo ""
echo "2. Edit .env:"
echo "   - Set ANTHROPIC_API_KEY=sk-ant-..."
echo ""
echo "3. Run the bot:"
echo "   source venv/bin/activate"
echo "   python scheduler.py          # 24/7 mode (bot + dashboard)"
echo "   python main.py               # Single run"
echo "   python scheduler.py --dash-only  # Dashboard only"
echo ""
echo "4. View dashboard at: http://127.0.0.1:8080"
echo ""
