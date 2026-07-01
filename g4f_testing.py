import argparse
import time

from g4f.client import Client

# ===========================================
# CONFIG
# ===========================================

API_KEY = "g4f_u_mqpn3r_a5f0c6c0a8bed3d18a51b7ed2155b2b6ee3220a2fc11869d_c466c36b"

# ===========================================


def main():
    parser = argparse.ArgumentParser(description="G4F Model Tester")

    parser.add_argument(
        "prompt",
        nargs="+",
        help="Prompt to send"
    )

    parser.add_argument(
        "-m",
        "--model",
        default="MODEL_NAME",
        help="Model name"
    )

    parser.add_argument(
        "-p",
        "--provider",
        default=None,
        help="Provider name (optional)"
    )

    args = parser.parse_args()

    prompt = " ".join(args.prompt)

    client = Client(api_key=API_KEY)

    print(f"Model    : {args.model}")
    print(f"Provider : {args.provider or 'Auto'}")

    create_args = {
        "model": args.model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "temperature": 0,
    }

    # Only include provider if explicitly supplied
    if args.provider:
        create_args["provider"] = args.provider

    start = time.perf_counter()

    try:
        response = client.chat.completions.create(**create_args)

        print("\n" + "=" * 70)
        print(response.choices[0].message.content)
        print("=" * 70)
        print(f"Latency: {time.perf_counter() - start:.2f}s")

    except Exception as e:
        print("\nFAILED")
        print(f"Latency: {time.perf_counter() - start:.2f}s")
        print(type(e).__name__)
        print(e)


if __name__ == "__main__":
    main()
