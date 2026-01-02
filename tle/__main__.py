import argparse
import asyncio
import logging
import os
from logging.handlers import TimedRotatingFileHandler
from os import environ
from pathlib import Path
import threading

import discord
import seaborn as sns
from discord.ext import commands
from matplotlib import pyplot as plt
from dotenv import load_dotenv
from fastapi import FastAPI
import uvicorn

from tle import constants
from tle.util import codeforces_common as cf_common, discord_common, font_downloader


def setup():
    # Make required directories.
    for path in constants.ALL_DIRS:
        os.makedirs(path, exist_ok=True)

    # logging to console and file on daily interval
    logging.basicConfig(
        format='{asctime}:{levelname}:{name}:{message}',
        style='{',
        datefmt='%d-%m-%Y %H:%M:%S',
        level=logging.INFO,
        handlers=[
            logging.StreamHandler(),
            TimedRotatingFileHandler(
                constants.LOG_FILE_PATH, when='D', backupCount=3, utc=True
            ),
        ],
    )

    # matplotlib and seaborn
    plt.rcParams['figure.figsize'] = 7.0, 3.5
    sns.set()
    options = {
        'axes.edgecolor': '#A0A0C5',
        'axes.spines.top': False,
        'axes.spines.right': False,
    }
    sns.set_style('darkgrid', options)

    # Download fonts if necessary
    font_downloader.maybe_download()


def strtobool(value: str) -> bool:
    """
    Convert a string representation of truth to true (1) or false (0).

    True values are y, yes, t, true, on and 1; false values are n, no, f,
    false, off and 0. Raises ValueError if val is anything else.
    """
    value = value.lower()
    if value in ('y', 'yes', 't', 'true', 'on', '1'):
        return True
    if value in ('n', 'no', 'f', 'false', 'off', '0'):
        return False
    raise ValueError(f'Invalid truth value {value!r}.')


def create_web_app():
    """Create FastAPI web application"""
    app = FastAPI(title="TLE Web Service", version="1.0.0", description="TLE Discord Bot Web API")
    
    @app.get("/")
    async def root():
        return {"message": "TLE Web Service is running", "status": "healthy"}
    
    @app.get("/health")
    async def health_check():
        return {"status": "healthy"}
    
    return app


def run_web_service(port: int, host: str = "0.0.0.0"):
    """Run the web service"""
    app = create_web_app()
    uvicorn.run(app, host=host, port=port, log_level="info")


def main():
    # Load environment variables from .env file
    load_dotenv()
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--nodb', action='store_true')
    parser.add_argument('--web-only', action='store_true', help='Run only web service')
    parser.add_argument('--port', type=int, default=8000, help='Port for web service')
    parser.add_argument('--host', default='0.0.0.0', help='Host for web service')
    args = parser.parse_args()

    token = environ.get('BOT_TOKEN')
    
    # Handle web-only mode
    if args.web_only:
        logging.info(f"Starting TLE web service on {args.host}:{args.port}")
        setup()
        run_web_service(args.port, args.host)
        return
    
    if not token:
        logging.error('BOT_TOKEN required for Discord bot mode')
        logging.info('Use --web-only flag to run only the web service')
        return

    allow_self_register = environ.get('ALLOW_DUEL_SELF_REGISTER')
    if allow_self_register:
        constants.ALLOW_DUEL_SELF_REGISTER = strtobool(allow_self_register)

    setup()

    # Start web service in background thread if port is specified
    web_thread = None
    if args.port and not args.web_only:
        logging.info(f"Starting web service on {args.host}:{args.port}")
        web_thread = threading.Thread(target=run_web_service, args=(args.port, args.host), daemon=True)
        web_thread.start()

    intents = discord.Intents.default()
    intents.members = True

    bot = commands.Bot(command_prefix=commands.when_mentioned_or(';'), intents=intents)
    cogs = [file.stem for file in Path('tle', 'cogs').glob('*.py')]
    for extension in cogs:
        bot.load_extension(f'tle.cogs.{extension}')
    logging.info(f'Cogs loaded: {", ".join(bot.cogs)}')

    def no_dm_check(ctx):
        if ctx.guild is None:
            raise commands.NoPrivateMessage('Private messages not permitted.')
        return True

    # Restrict bot usage to inside guild channels only.
    bot.add_check(no_dm_check)

    # cf_common.initialize needs to run first, so it must be set as the bot's
    # on_ready event handler rather than an on_ready listener.
    @discord_common.on_ready_event_once(bot)
    async def init():
        await cf_common.initialize(args.nodb)
        asyncio.create_task(discord_common.presence(bot))

    bot.add_listener(discord_common.bot_error_handler, name='on_command_error')
    
    try:
        bot.run(token)
    except KeyboardInterrupt:
        logging.info("Bot stopped by user")
    finally:
        if web_thread and web_thread.is_alive():
            logging.info("Web service will stop with the main process")


if __name__ == '__main__':
    main()
