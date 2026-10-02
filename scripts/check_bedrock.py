"""Report which Claude models this AWS account can call on Amazon Bedrock.

    python scripts/check_bedrock.py --region us-east-1

Uses your local AWS credentials. Exits 0 if at least one model answers. The
app tries the same models in the same order at run time, so whatever answers
here is what the deployed assistant will use.
"""
import argparse
import sys

import anthropic
from anthropic import AnthropicBedrockMantle

MODELS = ["anthropic.claude-opus-5-5", "anthropic.claude-opus-4-8", "anthropic.claude-haiku-4-5"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    client = AnthropicBedrockMantle(aws_region=args.region, timeout=60, max_retries=1)
    working = []
    for model in MODELS:
        try:
            message = client.messages.create(
                model=model,
                max_tokens=1024,
                messages=[{"role": "user", "content": "Reply with the single word: ready"}],
            )
            text = next((b.text for b in message.content if b.type == "text"), "").strip()
            print(f"  OK    {model}  ->  {text[:40]!r}")
            working.append(model)
        except anthropic.APIStatusError as err:
            print(f"  --    {model}  ->  HTTP {err.status_code}: {str(err)[:160]}")
        except anthropic.APIConnectionError as err:
            print(f"  --    {model}  ->  could not connect: {str(err)[:160]}")
        except Exception as err:  # missing credentials, unknown region, ...
            print(f"  --    {model}  ->  {type(err).__name__}: {str(err)[:160]}")

    if not working:
        print("\nNo Claude model is available to this account in this region yet.")
        return 1
    print(f"\nThe assistant will use: {working[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
