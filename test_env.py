import os
from dotenv import load_dotenv

load_dotenv()

print("Checking environment variables:")
print(f"OPENROUTER_API_KEY: {'SET' if os.getenv('OPENROUTER_API_KEY') else 'NOT SET'}")
print(f"OPENROUTER_API_KEY length: {len(os.getenv('OPENROUTER_API_KEY', ''))}")
print(f"OPENROUTER_API_KEY starts with 'sk-or': {os.getenv('OPENROUTER_API_KEY', '').startswith('sk-or')}")

# Test the config
from app.config import Config
print(f"Config.OPENROUTER_API_KEY: {'SET' if Config.OPENROUTER_API_KEY else 'NOT SET'}")
print(f"Config.OPENROUTER_API_KEY length: {len(Config.OPENROUTER_API_KEY or '')}")
