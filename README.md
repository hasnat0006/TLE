# TLE - Discord Bot for Codeforces

A Discord bot for competitive programming, focused on Codeforces integration.

## Prerequisites

- Python 3.14 or higher
- Discord Bot Token
- Git (optional, for cloning the repository)

## Setup Instructions

### 1. Clone or Download the Project

```bash
git clone <repository-url>
cd TLE
```

### 2. Set Up Environment Variables

Create a `.env` file in the project root directory and add your Discord bot token:

```
DISCORD_BOT_TOKEN=your_discord_bot_token_here
LOGGING_COG_CHANNEL_ID="XXXXXXXXXXXXXXXXXX"
ALLOW_DUEL_SELF_REGISTER="false"
```

### 3. Create a Virtual Environment

Create a Python virtual environment to isolate project dependencies:

```bash
python -m venv .venv
```

### 4. Activate the Virtual Environment

**On Windows (PowerShell):**
```powershell
.\.venv\Scripts\Activate.ps1
```

**On Windows (Command Prompt):**
```cmd
.venv\Scripts\activate
```

**On Linux/macOS:**
```bash
source .venv/bin/activate
```

### 5. Install Required Packages

Install all project dependencies from `requirements.txt`:

```bash
pip install -r requirements.txt
```

**Note:** The project has been updated to use `discord.py>=2.0.0` for compatibility with Python 3.14+.

### 6. Run the Application

Start the Discord bot:

```bash
python -m tle
```

## Project Structure

```
TLE/
├── tle/                    # Main application package
│   ├── __main__.py        # Entry point
│   ├── constants.py       # Application constants
│   ├── cogs/              # Discord bot commands (cogs)
│   └── util/              # Utility modules
│       ├── codeforces_api.py
│       ├── discord_common.py
│       └── db/            # Database modules
├── extra/                 # Extra resources
├── requirements.txt       # Python dependencies
├── pyproject.toml        # Project configuration
└── README.md             # This file
```

## Configuration

### Discord Bot Setup

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application
3. Go to the "Bot" section and create a bot
4. Copy the bot token and add it to your `.env` file
5. Enable required privileged intents (Message Content Intent recommended)
6. Invite the bot to your server using the OAuth2 URL generator

## Troubleshooting

### Module Not Found Errors

If you encounter `ModuleNotFoundError`, ensure:
- The virtual environment is activated
- All dependencies are installed: `pip install -r requirements.txt`

### Font Download Warnings

The bot may show warnings about failing to download fonts. These are non-critical and won't prevent the bot from running.

### Privileged Intent Warning

If you see "Privileged message content intent is missing", enable the Message Content Intent in your Discord bot settings for full functionality.

## Features

- Codeforces integration
- Contest tracking and notifications
- Problem recommendations
- User handle management
- Rating graphs and statistics
- Duel system for competitive programming

## License

See LICENSE file for details.
