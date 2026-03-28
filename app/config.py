import os
from dotenv import load_dotenv


load_dotenv()


class Config:
    PORT = int(os.getenv("PORT", "5000"))
    GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    ALLOW_UNSIGNED_WEBHOOKS = os.getenv("ALLOW_UNSIGNED_WEBHOOKS", "false").lower() == "true"
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
    JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "https://pratikfnu.atlassian.net")
    JIRA_AUDIT_LIMIT = int(os.getenv("JIRA_AUDIT_LIMIT", "5"))

    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_API_BASE = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com")
    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    DEEPSEEK_CONNECT_TIMEOUT_SEC = float(os.getenv("DEEPSEEK_CONNECT_TIMEOUT_SEC", "10"))
    DEEPSEEK_READ_TIMEOUT_SEC = float(os.getenv("DEEPSEEK_READ_TIMEOUT_SEC", "120"))
    DEEPSEEK_MAX_RETRIES = int(os.getenv("DEEPSEEK_MAX_RETRIES", "2"))
    DEEPSEEK_BACKOFF_BASE_SEC = float(os.getenv("DEEPSEEK_BACKOFF_BASE_SEC", "1.5"))
    DEEPSEEK_MAIN_CONTENT_MAX_CHARS = int(os.getenv("DEEPSEEK_MAIN_CONTENT_MAX_CHARS", "60000"))
    DEEPSEEK_RELATED_FILE_MAX_CHARS = int(os.getenv("DEEPSEEK_RELATED_FILE_MAX_CHARS", "8000"))
    DEEPSEEK_MAX_RELATED_FILES = int(os.getenv("DEEPSEEK_MAX_RELATED_FILES", "5"))
    DEEPSEEK_PATCH_MAX_CHARS = int(os.getenv("DEEPSEEK_PATCH_MAX_CHARS", "12000"))

    CONFLUENCE_BASE_URL = os.getenv("CONFLUENCE_BASE_URL", "")
    CONFLUENCE_EMAIL = os.getenv("CONFLUENCE_EMAIL", "")
    CONFLUENCE_API_TOKEN = os.getenv("CONFLUENCE_API_TOKEN", "")
    CONFLUENCE_SPACE_KEY = os.getenv("CONFLUENCE_SPACE_KEY", "")
    CONFLUENCE_PARENT_PAGE_ID = os.getenv("CONFLUENCE_PARENT_PAGE_ID", "")
    ENABLE_CONFLUENCE = os.getenv("ENABLE_CONFLUENCE", "false").lower() == "true"
