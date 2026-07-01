import os
import time
from dotenv import load_dotenv
from g4f.client import Client

# Load environment variables from the .env file in the current directory
load_dotenv()

API_KEY = os.environ.get("G4F_API_KEY")

if not API_KEY:
    print("WARNING: G4F_API_KEY not found in .env file!")

print("Testing nemotron-3-ultra with provider ollama.pro...")
# Initialize client with the API key loaded from .env
client = Client(api_key=API_KEY)

start = time.perf_counter()

try:
    response = client.chat.completions.create(
        model="nemotron-3-ultra",
        provider="ollama.pro",
        messages=[{"role": "user", "content": "Hello, are you working?"}]
    )
    print("SUCCESS!")
    print("Response:", response.choices[0].message.content)
    print(f"Latency: {time.perf_counter() - start:.2f}s")
except Exception as e:
    print("\nFAILED")
    print(f"Error: {type(e).__name__} - {e}")
