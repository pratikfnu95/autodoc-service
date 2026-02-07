import os
from dotenv import load_dotenv


load_dotenv()


class Config:
    PORT = int(os.getenv("PORT", "5000"))
    GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    ALLOW_UNSIGNED_WEBHOOKS = os.getenv("ALLOW_UNSIGNED_WEBHOOKS", "false").lower() == "true"
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_API_BASE = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com")
    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    CONFLUENCE_BASE_URL = os.getenv("CONFLUENCE_BASE_URL", "")
    CONFLUENCE_EMAIL = os.getenv("CONFLUENCE_EMAIL", "")
    CONFLUENCE_API_TOKEN = os.getenv("CONFLUENCE_API_TOKEN", "")
    CONFLUENCE_SPACE_KEY = os.getenv("CONFLUENCE_SPACE_KEY", "")
    CONFLUENCE_PARENT_PAGE_ID = os.getenv("CONFLUENCE_PARENT_PAGE_ID", "")
    ENABLE_CONFLUENCE = os.getenv("ENABLE_CONFLUENCE", "false").lower() == "true"
