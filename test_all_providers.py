import g4f
from g4f.models import gpt_4o_mini
import time

prompt = "Reply with exactly 'Yes'."

providers = gpt_4o_mini.best_provider.providers if hasattr(gpt_4o_mini.best_provider, 'providers') else [gpt_4o_mini.best_provider]

for provider in providers:
    name = provider.__name__
    print(f"\nTesting provider: {name}")
    start = time.perf_counter()
    try:
        response = g4f.ChatCompletion.create(
            model=gpt_4o_mini,
            messages=[{"role": "user", "content": prompt}],
            provider=provider
        )
        latency = time.perf_counter() - start
        print(f"Status : SUCCESS")
        print(f"Latency: {latency:.2f}s")
        print(f"Output : {response.strip()}")
    except Exception as e:
        latency = time.perf_counter() - start
        print(f"Status : FAILED")
        print(f"Latency: {latency:.2f}s")
        print(f"Error  : {type(e).__name__} - {str(e)[:100]}")
