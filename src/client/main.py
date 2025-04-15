# import asyncio
# from support_agent_antropic import Chat

# if __name__ == "__main__":
#     print("🚀 Starting chat agent")
#     chat = Chat()
#     asyncio.run(chat.run())

import asyncio
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the chat agent")
    parser.add_argument("--provider", choices=["anthropic", "openai"], required=True, help="Select the chat provider")
    args = parser.parse_args()

    if args.provider == "anthropic":
        from antropic_client import Chat
    elif args.provider == "openai":
        from openai_client import Chat

    print(f"🚀 Starting chat agent with {args.provider.capitalize()}")
    chat = Chat()
    asyncio.run(chat.run())
