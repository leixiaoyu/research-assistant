#!/bin/bash
# Migration Script: Upgrade Virtual Environment to Python 3.14
# This script safely migrates to Python 3.14 and installs marker-pdf

set -e  # Exit on error

echo "🔄 ARISP Python 3.14 Migration Script"
echo "======================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if Python 3.14 is available
if ! command -v /opt/homebrew/bin/python3.14 &> /dev/null; then
    echo -e "${RED}❌ Python 3.14 not found at /opt/homebrew/bin/python3.14${NC}"
    echo ""
    echo "Please install Python 3.14 first:"
    echo "  brew install python@3.14"
    exit 1
fi

PYTHON314_PATH="/opt/homebrew/bin/python3.14"
PYTHON_VERSION=$($PYTHON314_PATH --version)
echo -e "${GREEN}✓ Found: $PYTHON_VERSION${NC}"
echo ""

# Step 1: Backup old venv
if [ -d "venv" ]; then
    echo "📦 Step 1: Backing up old virtual environment..."
    BACKUP_NAME="venv_backup_$(date +%Y%m%d_%H%M%S)"
    mv venv "$BACKUP_NAME"
    echo -e "${GREEN}✓ Old venv backed up to: $BACKUP_NAME${NC}"
    echo -e "${YELLOW}  (You can delete this later: rm -rf $BACKUP_NAME)${NC}"
    echo ""
else
    echo -e "${YELLOW}⚠️  No existing venv found, creating fresh...${NC}"
    echo ""
fi

# Step 2: Create new venv with Python 3.14
echo "🏗️  Step 2: Creating new virtual environment with Python 3.14..."
$PYTHON314_PATH -m venv venv
echo -e "${GREEN}✓ Virtual environment created${NC}"
echo ""

# Step 3: Activate venv and upgrade pip
echo "⬆️  Step 3: Activating venv and upgrading pip..."
source venv/bin/activate
python -m pip install --upgrade pip --quiet
echo -e "${GREEN}✓ Pip upgraded to: $(pip --version)${NC}"
echo ""

# Step 4: Install requirements
echo "📦 Step 4: Installing requirements from requirements.txt..."
pip install -r requirements.txt --quiet
echo -e "${GREEN}✓ All requirements installed${NC}"
echo ""

# Step 5: Install marker-pdf
echo "🎯 Step 5: Installing marker-pdf (PDF extraction)..."
pip install marker-pdf --quiet
echo -e "${GREEN}✓ marker-pdf installed${NC}"
echo ""

# Step 6: Verify installation
echo "🔍 Step 6: Verifying installation..."
echo ""
echo "Python version:"
python --version

echo ""
echo "Key packages:"
pip list | grep -E "(pydantic|pytest|marker|anthropic|google)" || true

echo ""
echo "Checking marker-pdf command:"
if command -v marker_single &> /dev/null; then
    echo -e "${GREEN}✓ marker_single is available${NC}"
    marker_single --version 2>&1 | head -3 || echo "  (Version check returned error, but command exists)"
else
    echo -e "${RED}❌ marker_single command not found${NC}"
    echo "  This may require system dependencies. See: https://github.com/VikParuchuri/marker"
fi

echo ""
echo "======================================"
echo -e "${GREEN}🎉 Migration Complete!${NC}"
echo ""
echo "Next steps:"
echo "  1. Activate the new environment: source venv/bin/activate"
echo "  2. Run tests: ./verify.sh"
echo "  3. Test PDF extraction: python -m src.cli run --config config/phase2_e2e_test.yaml"
echo ""
echo "If marker_single command doesn't work, you may need system dependencies:"
echo "  See: https://github.com/VikParuchuri/marker#installation"
echo ""
