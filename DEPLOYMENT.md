# TLE Web Service Deployment Guide

Your TLE Discord bot has been converted to support web service deployment with port configuration. Here are your deployment options:

## Quick Start

### Option 1: Web Service Only
```bash
# Install dependencies
pip install -r requirements.txt

# Run web service only on port 8000
python -m tle --web-only --port 8000
```

### Option 2: Discord Bot + Web Service
```bash
# Create .env file with your BOT_TOKEN
cp .env.example .env
# Edit .env and add your Discord bot token

# Run both Discord bot and web service
python -m tle --port 8000
```

## Available Endpoints

Once running, your web service will be available at `http://localhost:8000` with:

- `GET /` - Service status
- `GET /health` - Health check

## Command Line Options

```bash
python -m tle [options]

Options:
  --web-only          Run only the web service (no Discord bot)
  --port PORT         Port for web service (default: 8000)
  --host HOST         Host for web service (default: 0.0.0.0)
  --nodb             Run without database
```

## Environment Variables

- `BOT_TOKEN` - Discord bot token (required for bot mode)
- `PORT` - Web service port (optional, can use --port instead)
- `HOST` - Web service host (optional, can use --host instead)
- `ALLOW_DUEL_SELF_REGISTER` - Allow self-registration for duels

## Deployment Platforms

### Heroku
1. Add Procfile: `web: python -m tle --web-only --port $PORT`
2. Set environment variables in Heroku dashboard
3. Deploy using Git

### Railway/Render
1. Connect your GitHub repository
2. Set build command: `pip install -r requirements.txt`
3. Set start command: `python -m tle --web-only --port $PORT`

## Production Considerations

1. **Environment Variables**: Use proper secrets management
2. **Database**: Configure persistent storage for data/db
3. **Logs**: Mount logs directory for persistence
4. **Health Checks**: Use `/health` endpoint
4. **Monitoring**: Basic service monitoring

## Testing

Test your deployment:
```bash
curl http://localhost:8000/health
```