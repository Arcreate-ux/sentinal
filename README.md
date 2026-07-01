# SENTINEL

SENTINEL is an autonomous study decision system for JEE preparation. The same source tree can live on GitHub and run as a Hugging Face Docker Space without changing the app code.

## What you need to deploy

- `main.py`
- `Dockerfile`
- `requirements.txt`
- `README.md`
- `LICENSE`
- `.env.example`
- the runtime packages: `bot/`, `brain/`, `scheduler/`, `state/`, `notion_client/`, `sentinel/`, `health/`

You do not need an `app.py` for this setup. The Dockerfile starts `python main.py` directly.

## Required environment variables

| Variable | Purpose |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from BotFather |
| `NOTION_API_KEY` | Notion integration token |
| `MONGODB_URI` | MongoDB connection string, usually your Atlas cluster |
| one AI key | At least one provider key from the configured fallback chain |

Recommended production variables:

- `TELEGRAM_CHAT_ID`
- `TELEGRAM_ALLOWED_USERS`
- `MONGODB_DB_NAME=sentinel_brain`
- `NOTION_DB1_ID`
- `NOTION_DB2_ID`
- `NOTION_DB3_ID`
- `NOTION_DB4_ID`
- `PORT=8080`

Supported AI provider keys include `GOOGLE_API_KEY`, `GROQ_API_KEY`, `CEREBRAS_API_KEY`, `OPENROUTER_API_KEY`, `COHERE_API_KEY`, `HUGGINGFACE_API_KEY`, `CLOUDFLARE_API_KEY`, `G4F_API_KEY`, and `OLLAMA_API_KEY`.

## Local run

```bash
python main.py
```

If you are running it in Docker:

```bash
docker build -t sentinel .
docker run --env-file .env -p 8080:8080 sentinel
```

## Hugging Face deployment

Use a Docker Space.

1. Create a new Hugging Face Space and choose `Docker`.
2. Connect the same GitHub repo or upload the repository contents.
3. Add your secrets in the Space settings.
4. Leave the `Dockerfile` at the repository root.
5. The Space will start from `python main.py` and bind to the exposed port.

## GitHub deployment

Push the repository normally. GitHub does not need any special wrapper files for this project. The repo layout is already compatible with Docker-based deployment from source.

## License

This project is released under the GNU General Public License v3.0 or later. See [LICENSE](LICENSE).
