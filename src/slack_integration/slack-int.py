import os
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import dotenv

# Load environment variables from .env file
dotenv.load_dotenv()

# Set your tokens here or load from .env
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")

# Initialize the app
app = App(token=SLACK_APP_TOKEN)

# Respond to @mentions
@app.event("app_mention")
def handle_mention_events(body, say):
    user = body["event"]["user"]
    text = body["event"]["text"]
    print(f"User: {user}, Text: {text}")
    say(f"<@{user}> You said: {text}")

# Start the SocketMode handler
if __name__ == "__main__":
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
