"""Configuration management via environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Application configuration loaded from environment variables."""

    # Project paths
    project_root: Path = field(
        default_factory=lambda: Path(__file__).parent.parent.parent
    )

    # YouTube API
    youtube_api_key: str = field(
        default_factory=lambda: os.environ.get("YOUTUBE_API_KEY", "")
    )
    channel_id: str = field(
        default_factory=lambda: os.environ.get("CHANNEL_ID", "")
    )
    channel_name: str = field(
        default_factory=lambda: os.environ.get("CHANNEL_NAME", "空想ロマンス")
    )

    # AI provider: auto | ollama | openai | claude | none
    ai_provider: str = field(
        default_factory=lambda: os.environ.get("AI_PROVIDER", "auto")
    )

    # Ollama
    ollama_base_url: str = field(
        default_factory=lambda: os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    )
    ollama_model: str = field(
        default_factory=lambda: os.environ.get("OLLAMA_MODEL", "llama3.2")
    )

    # OpenAI compatible
    openai_api_key: str = field(
        default_factory=lambda: os.environ.get("OPENAI_API_KEY", "")
    )
    openai_base_url: str = field(
        default_factory=lambda: os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    )
    openai_model: str = field(
        default_factory=lambda: os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    )

    # Claude
    claude_api_key: str = field(
        default_factory=lambda: os.environ.get("CLAUDE_API_KEY", "")
    )
    claude_model: str = field(
        default_factory=lambda: os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
    )

    # Member names for mention analysis
    member_names: list[str] = field(
        default_factory=lambda: [
            name.strip()
            for name in os.environ.get("MEMBER_NAMES", "").split(",")
            if name.strip()
        ]
    )

    # Analysis thresholds
    buzz_threshold: float = field(
        default_factory=lambda: float(os.environ.get("BUZZ_THRESHOLD", "2.0"))
    )
    momentum_threshold: float = field(
        default_factory=lambda: float(os.environ.get("MOMENTUM_THRESHOLD", "1.5"))
    )
    db_size_warn_mb: int = field(
        default_factory=lambda: int(os.environ.get("DB_SIZE_WARN_MB", "400"))
    )
    db_size_archive_mb: int = field(
        default_factory=lambda: int(os.environ.get("DB_SIZE_ARCHIVE_MB", "500"))
    )

    @property
    def db_path(self) -> Path:
        return self.project_root / "data" / "youtube_analytics.db"

    @property
    def reports_dir(self) -> Path:
        return self.project_root / "reports"

    @property
    def graphs_dir(self) -> Path:
        return self.project_root / "graphs"

    @property
    def docs_dir(self) -> Path:
        return self.project_root / "docs"

    @property
    def templates_dir(self) -> Path:
        return self.project_root / "templates"

    @property
    def logs_dir(self) -> Path:
        return self.project_root / "logs"

    def validate(self) -> list[str]:
        """Return list of validation errors. Empty means valid."""
        errors: list[str] = []
        if not self.youtube_api_key:
            errors.append("YOUTUBE_API_KEY is not set")
        if not self.channel_id and not self.channel_name:
            errors.append("Either CHANNEL_ID or CHANNEL_NAME must be set")
        return errors


_config: Config | None = None


def get_config() -> Config:
    """Return singleton Config instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config


def reset_config() -> None:
    """Reset singleton (for testing)."""
    global _config
    _config = None
