import asyncio
import os
from pymongo import AsyncMongoClient
from dotenv import load_dotenv

load_dotenv()
mongo_uri = os.getenv("MONGODB_URI")
if not mongo_uri:
    print("No MONGODB_URI found")
    exit(1)

async def wipe():
    client = AsyncMongoClient(mongo_uri)
    db = client.get_database("sentinel_brain")
    print(f"Wiping database: sentinel_brain")
    await client.drop_database("sentinel_brain")
    print("Database wiped successfully!")
    await client.close()

asyncio.run(wipe())
