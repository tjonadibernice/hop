from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# app/config.py -> parents[0] = app/, [1] = backend/, [2] = hop/ (project root)
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    # env_ignore_empty: a line like GEMINI_REQUESTS_PER_MINUTE= means "not set"
    model_config = SettingsConfigDict(
        env_file=ENV_FILE, extra="ignore", env_ignore_empty=True
    )

    database_url: str
    redis_url: str
    test_database_url: str | None = None

    smtp_host: str = "localhost"
    smtp_port: int = 1025
    mail_from: str = "Hop <no-reply@hop.local>"
    app_base_url: str = "http://localhost:5173"

    session_cookie_name: str = "hop_session"
    session_ttl_seconds: int = 7 * 24 * 60 * 60  # 7 days
    cookie_secure: bool = False  # set to true in production (HTTPS only)

    crawler_user_agent: str = "HopBot/0.1 (+https://github.com/tjonadibernice/hop)"
    crawl_delay_seconds: float = 1.0  # minimum gap between requests to one site
    # Lets the crawler fetch localhost and private addresses. Only for local
    # testing: never turn this on where the crawler can reach real services.
    crawl_allow_private_hosts: bool = False

    # Enrichment: LLM providers, tried in this order. Leave a key empty to skip
    # that provider. Ollama runs locally and needs no key.
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.1-flash-lite"
    gemini_requests_per_minute: int | None = None  # space calls; empty = no limit
    gemini_max_calls_per_day: int | None = 1000  # budget guard for paid tiers
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.6-luna"
    openai_requests_per_minute: int | None = None
    openai_max_calls_per_day: int | None = 1000
    ollama_base_url: str | None = None  # e.g. http://localhost:11434/v1
    ollama_model: str = "llama3.2"

    # Embeddings (optional: without a key, pages are stored without one)
    voyage_api_key: str | None = None
    voyage_model: str = "voyage-4-lite"

    # A/B test: the share of users (0-100) who get the recommender instead of
    # random picks. 0 turns the recommender off; 100 gives it to everyone.
    recommender_percent: int = 50

    # The share of hops (0-100) that are interactive pages (tools, simulations,
    # games, visualizations); the rest are articles. When one kind runs out
    # for a user, the other fills in.
    interactive_percent: int = 70

    # Serve hops from each user's precomputed Redis queue (filled by the
    # worker). False picks every page while the user waits, which is slower;
    # it's there for comparisons like the load test.
    hop_queue_enabled: bool = True

    # The curator agent reviews needs_review pages (app/curator). False leaves
    # them all for a person. The limits cap what one review can cost.
    curator_enabled: bool = True
    curator_max_turns: int = 8  # model calls per review
    curator_max_tool_calls: int = 6

    # Rate limits on sign-up, login, and email confirmation (app/routers/auth.py).
    # Only turn them off for local experiments.
    rate_limit_enabled: bool = True

    # Emails of the people who may use the review screen and remove pages,
    # separated by commas. Empty: nobody (the admin endpoints answer 403).
    admin_emails: str = ""

    def is_admin(self, email: str) -> bool:
        admins = {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}
        return email.strip().lower() in admins

    # Safety check (optional: without a key, pages can't be auto-approved)
    safe_browsing_api_key: str | None = None


settings = Settings()
