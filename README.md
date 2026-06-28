# SENTINEL

An autonomous, agentic accountability system for JEE preparation.

## Startup Checklist

Before booting `main.py` for the first time, ensure you have completed the following:

1. **Environment Variables**: Copy `.env.example` to `.env` and fill in all the API keys.
2. **MongoDB**: Ensure MongoDB is running locally (`systemctl start mongod` or via Docker). The system will automatically ping it on boot and crash if it is unreachable.
3. **Notion Databases**: Ensure you have created all four databases in Notion and shared them with your Notion Integration:
   - DB1: Event Timeline
   - DB2: Revision Backlog
   - DB3: Master Concepts
   - DB4: System Audit Log
4. **Telegram Bot**: Start a chat with your bot on Telegram and get your Chat ID.

## Running the System

```bash
python3 main.py
```
