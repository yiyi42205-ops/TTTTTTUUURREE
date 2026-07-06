#!/bin/bash

# --- Color Definitions & TTY Detection ---
if [ -t 1 ] && [ ! -z "$TERM" ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    BLUE='\033[0;34m'
    CYAN='\033[0;36m'
    YELLOW='\033[1;33m'
    BOLD='\033[1m'
    NC='\033[0m' # No Color
    clear
else
    RED=''
    GREEN=''
    BLUE=''
    CYAN=''
    YELLOW=''
    BOLD=''
    NC=''
fi

echo -e "${BLUE}${BOLD}=================================================="
echo -e "      Google Maps TrueRating Setup & Runner"
echo -e "==================================================${NC}"
echo -e "This script will help you configure and run the project."
echo

# Helper function to print status
status_info() {
    echo -e "${CYAN}[info]${NC} $1"
}
status_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}
status_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}
status_error() {
    echo -e "${RED}[✗]${NC} $1"
}

# --- 1. Check Core System Requirements ---
status_info "Checking system requirements..."

# Check Node.js
if ! command -v node &> /dev/null; then
    status_error "Node.js is not installed. Please install Node.js (v18+) and try again."
    exit 1
else
    NODE_VER=$(node -v)
    status_success "Node.js is installed ($NODE_VER)"
fi

# Check Python3 (prefer python 3.10 to 3.13, avoiding pre-releases/unsupported like 3.14+)
status_info "Detecting compatible Python 3 version..."
PYTHON_CMD=""
for cmd in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$cmd" &> /dev/null; then
        VER_STR=$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
        major=$(echo "$VER_STR" | cut -d. -f1)
        minor=$(echo "$VER_STR" | cut -d. -f2)
        if [ "$major" -eq 3 ] && [ "$minor" -le 13 ] && [ "$minor" -ge 9 ]; then
            PYTHON_CMD="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    if command -v python3 &> /dev/null; then
        PYTHON_CMD="python3"
        status_warning "No Python 3.9-3.13 installation found. Falling back to default python3: $($PYTHON_CMD --version)"
    else
        status_error "Python 3 is not installed. Please install Python 3 (preferably 3.10-3.13) and try again."
        exit 1
    fi
else
    PYTHON_VER=$($PYTHON_CMD --version)
    status_success "Found compatible Python: $PYTHON_CMD ($PYTHON_VER)"
fi

echo

# --- 2. Interactive Parameters & Configuration ---
echo -e "${BOLD}--- Interactive Configuration ---${NC}"

# Ask for Node dependency installation
read -p "$(echo -e "${YELLOW}Install Node.js dependencies? (Recommended for first run) [Y/n]: ${NC}")" INSTALL_NODE
INSTALL_NODE=${INSTALL_NODE:-Y}

# Ask for Python dependency installation
read -p "$(echo -e "${YELLOW}Install Python scraper dependencies & setup venv? (Required for scraping reviews) [Y/n]: ${NC}")" INSTALL_PYTHON
INSTALL_PYTHON=${INSTALL_PYTHON:-Y}

echo

# --- Gemini API Key Setup ---
# The audit backend (review_scraper/server.py) reads GEMINI_API_KEY from .env at
# startup and refuses to start without it, so make sure one exists before we try
# to launch anything.
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
    fi
    status_warning ".env not found — created from .env.example. A Gemini API key is required to run the AI audit."
    read -p "$(echo -e "${YELLOW}Enter your Gemini API key now (leave blank to edit .env manually later): ${NC}")" GEMINI_KEY_INPUT
    if [ ! -z "$GEMINI_KEY_INPUT" ]; then
        if [[ "$(uname)" == "Darwin" ]]; then
            sed -i '' "s|GEMINI_API_KEY=.*|GEMINI_API_KEY=$GEMINI_KEY_INPUT|" .env
        else
            sed -i "s|GEMINI_API_KEY=.*|GEMINI_API_KEY=$GEMINI_KEY_INPUT|" .env
        fi
        status_success "Gemini API key saved to .env."
    else
        status_warning "Skipped — remember to set GEMINI_API_KEY in .env before starting the scraper backend."
    fi
else
    status_success ".env already exists."
fi

echo

# --- 3. Execution of Setup ---

# Install Node modules if requested
if [[ "$INSTALL_NODE" =~ ^[yY]$ ]]; then
    status_info "Installing Node.js packages..."
    npm install
    if [ $? -eq 0 ]; then
        status_success "Node.js packages installed successfully."
    else
        status_error "Failed to install Node.js packages."
        exit 1
    fi
else
    status_info "Skipping Node.js packages installation."
fi

# Setup Python Virtual Environment and Install Dependencies
if [[ "$INSTALL_PYTHON" =~ ^[yY]$ ]]; then
    status_info "Setting up Python virtual environment..."
    if [ -d "review_scraper/venv" ]; then
        # Check if venv python version matches the selected python version
        VENV_PY_VER=$(review_scraper/venv/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
        SELECTED_PY_VER=$($PYTHON_CMD -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
        if [ "$VENV_PY_VER" != "$SELECTED_PY_VER" ]; then
            status_warning "Python version changed (venv was $VENV_PY_VER, selected is $SELECTED_PY_VER). Recreating virtual environment..."
            rm -rf review_scraper/venv
        fi
    fi
    if [ ! -d "review_scraper/venv" ]; then
        $PYTHON_CMD -m venv review_scraper/venv
    fi
    
    status_info "Installing Python dependencies (requirements.txt)..."
    review_scraper/venv/bin/pip install -r review_scraper/requirements.txt
    
    if [ $? -eq 0 ]; then
        status_success "Python dependencies installed successfully."
    else
        status_error "Failed to install Python dependencies."
        exit 1
    fi
    
    status_info "Installing Playwright chromium browser..."
    review_scraper/venv/bin/playwright install chromium
    if [ $? -eq 0 ]; then
        status_success "Playwright browser installed."
    else
        status_error "Failed to install Playwright browser."
        exit 1
    fi
else
    status_info "Skipping Python venv setup."
fi

echo
echo -e "${GREEN}${BOLD}=================================================="
echo -e "              Setup Completed!"
echo -e "==================================================${NC}"
echo

read -p "$(echo -e "${YELLOW}Would you like to start the application now? [Y/n]: ${NC}")" START_APP
START_APP=${START_APP:-Y}

if [[ "$START_APP" =~ ^[yY]$ ]]; then
    status_info "Starting Flask scraper backend (background) and Vite developer server..."
    echo -e "${BLUE}Press Ctrl+C to stop both.${NC}"
    echo

    npm run dev:scraper &
    SCRAPER_PID=$!
    trap 'status_info "Stopping scraper backend..."; kill $SCRAPER_PID 2>/dev/null' EXIT

    npm run dev
else
    status_info "Setup completed. You can start the app later by running these two commands (in separate terminals):"
    status_info "  ${BOLD}npm run dev:scraper${NC}  (Flask scraper/audit backend, port 5001)"
    status_info "  ${BOLD}npm run dev${NC}          (Vite frontend, proxies /api to the backend)"
fi
