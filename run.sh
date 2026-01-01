#!/bin/bash

# TLE Bot Comprehensive Setup and Run Script
set -e

# Function to check Python version compatibility
check_python_version() {
    python3 -c "
import sys
version = sys.version_info
if version < (3, 9):
    print('❌ Python 3.9+ required. Current:', f'{version.major}.{version.minor}.{version.micro}')
    sys.exit(1)
elif version >= (3, 13):
    print('❌ Python 3.13+ has compatibility issues with discord.py dependencies.')
    print('   The cgi module was removed in Python 3.13, breaking aiohttp.')
    print(f'   Current: {version.major}.{version.minor}.{version.micro}')
    print('   ✅ Recommended: Python 3.9-3.12')
    sys.exit(1)
else:
    print(f'✅ Python version {version.major}.{version.minor}.{version.micro} is compatible')
"
}

# Function to install system dependencies (Linux only)
install_system_deps() {
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        echo "🎨 Installing system graphics libraries..."
        
        # Check if running in a container/cloud environment
        if [ -f /.dockerenv ] || [ -n "$RENDER" ] || [ -n "$HEROKU" ]; then
            echo "📦 Cloud environment detected, skipping system package installation"
            echo "   Make sure your platform has cairo, pango, and graphics libraries installed"
            return 0
        fi
        
        # Try to install system dependencies
        if command -v apt-get >/dev/null 2>&1; then
            sudo apt-get update || echo "⚠️  Could not update package list"
            sudo apt-get install -y \
                libcairo2-dev \
                libgirepository1.0-dev \
                python3-gi \
                python3-gi-cairo \
                python3-cairo \
                libjpeg-dev \
                zlib1g-dev \
                pkg-config \
                python3-venv || echo "⚠️  Some system packages may not have been installed"
        else
            echo "⚠️  apt-get not found. Please install system graphics libraries manually:"
            echo "   - cairo development libraries"
            echo "   - pango development libraries" 
            echo "   - python3 gobject introspection"
        fi
    else
        echo "📦 Non-Linux OS detected, skipping system package installation"
    fi
}

# Function to setup Python environment
setup_python_env() {
    echo "🐍 Setting up Python environment..."
    
    # Check if we're in a cloud environment
    if [ -n "$RENDER" ] || [ -n "$HEROKU" ] || [ -n "$RAILWAY" ]; then
        echo "☁️  Cloud deployment detected"
        # In cloud environments, often dependencies are installed differently
        if [ ! -d ".venv" ]; then
            python3 -m venv .venv
        fi
        source .venv/bin/activate
    else
        # Local development setup
        if [ ! -d "venv" ]; then
            echo "📦 Creating virtual environment with system site packages..."
            python3 -m venv --system-site-packages venv
        fi
        source venv/bin/activate
    fi
    
    echo "📥 Installing/updating Python dependencies..."
    pip install --upgrade pip
    pip install -r requirements.txt
}

# Function to check environment configuration
check_config() {
    if [ ! -f ".env" ]; then
        if [ -f ".env.example" ]; then
            echo "⚠️  .env file not found! Creating from example..."
            cp .env.example .env
            echo "📝 Please edit .env with your Discord bot token and other settings"
            echo "   Required: BOT_TOKEN=your_discord_bot_token_here"
            if [ -z "$BOT_TOKEN" ]; then
                echo "❌ BOT_TOKEN environment variable not set and no .env file configured"
                echo "   Please set BOT_TOKEN in .env file or as environment variable"
                return 1
            fi
        else
            echo "❌ No .env file found and no BOT_TOKEN environment variable set"
            echo "📝 Please create a .env file with:"
            echo "   BOT_TOKEN=your_discord_bot_token_here"
            echo "   LOGGING_COG_CHANNEL_ID=your_channel_id"
            return 1
        fi
    fi
    
    # Load environment variables from .env if it exists
    if [ -f ".env" ]; then
        set -a
        source .env
        set +a
    fi
    
    # Check if BOT_TOKEN is set
    if [ -z "$BOT_TOKEN" ]; then
        echo "❌ BOT_TOKEN not found in environment or .env file"
        return 1
    fi
    
    echo "✅ Configuration validated"
}

# Function to run the bot
run_bot() {
    echo ""
    echo "🚀 Starting TLE Bot..."
    echo "💡 Press Ctrl+C to stop the bot"
    echo ""
    
    # Activate the appropriate environment
    if [ -n "$RENDER" ] || [ -n "$HEROKU" ] || [ -n "$RAILWAY" ]; then
        if [ -f ".venv/bin/activate" ]; then
            source .venv/bin/activate
        fi
    else
        if [ -f "venv/bin/activate" ]; then
            source venv/bin/activate
        fi
    fi
    
    python -m tle
}

# Main execution
main() {
    echo "🚀 TLE Bot Setup and Run Script"
    echo ""
    
    # Check Python version
    check_python_version
    
    # Install system dependencies (only for local Linux)
    if [ -z "$RENDER" ] && [ -z "$HEROKU" ] && [ -z "$RAILWAY" ]; then
        install_system_deps
    fi
    
    # Setup Python environment
    setup_python_env
    
    # Check configuration
    if ! check_config; then
        exit 1
    fi
    
    # Run the bot
    run_bot
}

# Run main function
main "$@"