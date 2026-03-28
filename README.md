# post_agent

Portable Telegram bot for scheduled channel posts.

The repository is prepared for public use:
- no personal runtime data is tracked
- no API keys are stored in the repo
- prompts live in a separate text file
- AI provider settings live in a separate local JSON file

## What it does

- Publishes one approved post per day on a Telegram channel
- Lets one private owner moderate and publish posts
- Stores runtime state locally in `data/`
- Keeps post prompts separate from code

## Project layout

- `main.py` - bot entry point
- `bot/` - Telegram runtime logic
- `content/posts/posts.json` - post library
- `content/prompts/post_prompt.txt` - editable prompt template for future post generation
- `config/providers.example.json` - example local config for OpenAI, Claude, and Gemini
- `data/` - runtime state and logs, ignored by git

## Quick start

1. Copy `.env.example` to `.env`
2. Add your Telegram bot token to `.env`
3. Optional: copy `config/providers.example.json` to `config/providers.json` and fill in only the provider you want to use
4. Edit `content/prompts/post_prompt.txt`
5. Install dependencies
6. Optional: download images
7. Start the bot

```powershell
python -m pip install -e .
python tools/download_assets.py
python main.py
```

## Local files

- `.env` is for Telegram and runtime settings only
- `config/providers.json` is for local AI keys and model names
- `data/` is created and updated at runtime

None of these files should be committed to a public repository.

## Environment variables

```env
TELEGRAM_BOT_TOKEN=
DEFAULT_CHANNEL_ID=
OWNER_USER_ID=
TIMEZONE=Europe/Kyiv
PUBLISH_TIME=20:30
POST_PROMPT_PATH=content/prompts/post_prompt.txt
AI_PROVIDERS_PATH=config/providers.json
```

## Notes

- The current bot does not call OpenAI, Claude, or Gemini directly yet. The provider file is included so the project can be extended without hardcoding secrets.
- The first private `/start` binds the owner unless `OWNER_USER_ID` is set.
- The first valid channel event binds the channel unless `DEFAULT_CHANNEL_ID` is set.
- Scheduling depends on the running Python process.
