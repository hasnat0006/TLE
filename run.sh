#!/bin/bash

# TLE Bot Complete Setup and Run Script
# This script handles everything: dependencies, setup, and running the bot

set -e  # Exit on any error

echo "🚀 TLE Bot - One Command Setup & Run"
echo "========================================"

# Function to check if system dependencies are installed
check_system_deps() {
    echo "🔍 Checking system dependencies..."
    
    # Check for required packages
    local missing_deps=()
    
    if ! dpkg -l | grep -q "libcairo2-dev"; then missing_deps+=("libcairo2-dev"); fi
    if ! dpkg -l | grep -q "python3-gi"; then missing_deps+=("python3-gi"); fi
    if ! dpkg -l | grep -q "python3-venv"; then missing_deps+=("python3-venv"); fi
    
    if [ ${#missing_deps[@]} -gt 0 ]; then
        echo "📦 Installing missing system dependencies..."
        sudo apt-get update
        sudo apt-get install -y \
            libcairo2-dev \
            libgirepository1.0-dev \
            python3-gi \
            python3-gi-cairo \
            python3-cairo \
            libjpeg-dev \
            zlib1g-dev \
            pkg-config \
            python3 \
            python3-pip \
            python3-venv
        echo "✅ System dependencies installed!"
    else
        echo "✅ System dependencies already installed!"
    fi
}

# Function to setup Python environment
setup_python_env() {
    echo "🔄 Setting up Python environment..."
    
    # Create virtual environment with system site packages if it doesn't exist
    if [ ! -d "venv" ]; then
        echo "📦 Creating virtual environment with system site packages..."
        python3 -m venv --system-site-packages venv
    fi
    
    # Activate virtual environment
    echo "🔄 Activating virtual environment..."
    source venv/bin/activate
    
    # Install/upgrade Python dependencies
    echo "📥 Installing Python dependencies..."
    pip install --upgrade pip
    pip install -e .
    
    echo "✅ Python environment ready!"
}

# Function to check .env file
check_env_file() {
    echo "🔧 Checking configuration..."
    
    if [ ! -f ".env" ]; then
        echo "⚠️ .env file not found!"
        
        if [ -f ".env.example" ]; then
            echo "📝 Copying .env.example to .env"
            cp .env.example .env
            echo "⚠️ Please edit .env file with your Discord bot token!"
            echo "   nano .env  # Edit BOT_TOKEN=your_actual_token_here"
            read -p "Press Enter after updating .env file..."
        else
            echo "📝 Please create a .env file with your Discord bot token:"
            echo "   echo 'BOT_TOKEN=your_discord_token_here' > .env"
            echo "   echo 'LOGGING_COG_CHANNEL_ID=your_channel_id' >> .env"
            exit 1
        fi
    fi
    
    # Check if BOT_TOKEN is set
    source .env 2>/dev/null || true
    if [ -z "$BOT_TOKEN" ] || [ "$BOT_TOKEN" = "your_discord_bot_token_here" ]; then
        echo "❌ BOT_TOKEN not configured in .env file!"
        echo "📝 Please edit .env and set your actual Discord bot token"
        exit 1
    fi
    
    echo "✅ Configuration looks good!"
}

# Function to run the bot
run_bot() {
    echo "🚀 Starting TLE Bot..."
    echo "💡 Press Ctrl+C to stop the bot"
    echo ""
    
    # Activate virtual environment and run bot
    source venv/bin/activate
    python -m tle
}

# Main execution
echo "🔍 Performing complete setup check..."
echo ""

# Check and install system dependencies
check_system_deps
echo ""

# Setup Python environment
setup_python_env
echo ""

# Check configuration
check_env_file
echo ""

# Run the bot
run_bot