"""LLM integration: Ollama → OpenAI → Claude with graceful fallback."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

import httpx

from .config import Config
from .models import ReportData

logger = logging.getLogger(__name__)

_ANALYSIS_PROMPT_TEMPLATE = """\
あなたはYouTubeチャンネル「{channel_name}」の専属データアナリストです。
以下のデータを分析し、日本語で詳細なレポートを作成してください。

## チャンネル概要（{report_date}時点）
- 登録者数: {subscriber_count:,}人（前日比 {subscriber_delta:+,}人）
- 総再生回数: {view_count:,}回（前日比 {view_delta:+,}回）
- 総動画数: {video_count}本
- 月間投稿本数: {posts_per_month:.1f}本
- Shorts比率: {shorts_ratio:.1%}

## 急上昇動画 TOP5（過去24時間）
{rising_videos}

## 急減速動画 TOP5
{declining_videos}

## Shorts vs 通常動画
- Shorts 30日平均成長率: {shorts_growth_rate:.2%}
- 通常動画 30日平均成長率: {regular_growth_rate:.2%}

## コンテンツタイプ別
{content_type_stats}

## ヒット予測候補
{hit_predictions}

---

以下の7項目について、日本語で具体的かつ実践的なレポートを作成してください。
各項目は必ず記述してください。

1. **エグゼクティブサマリー**（3文以内で核心を突いた要約）

2. **急上昇動画の深堀り分析**（なぜ伸びているのか仮説を立て考察）

3. **急減速動画への対応策**（具体的なアクション提案）

4. **コンテンツ戦略の提言**（データに基づいた優先順位付き提案）

5. **Shorts活用最適化案**（現状の課題と改善方向）

6. **注意すべき警告事項**（投稿頻度、依存リスク、成長鈍化など）

7. **推奨アクション TOP3**（最優先で実施すべき具体的な3つのアクション）

Markdownフォーマットで出力してください。
"""


def _format_videos(videos: list[Any]) -> str:
    lines: list[str] = []
    for i, v in enumerate(videos[:5], 1):
        from .models import GrowthMetrics
        if isinstance(v, GrowthMetrics):
            lines.append(
                f"{i}. 「{v.title}」"
                f" 再生数:{v.current_views:,}"
                f" (+{v.delta_24h:,}/24h)"
                f" 勢い指数:{v.momentum_index:.2f}"
            )
    return "\n".join(lines) if lines else "データなし"


def _format_content_types(stats: list[Any]) -> str:
    lines: list[str] = []
    for s in stats[:6]:
        from .models import ContentTypeStats
        if isinstance(s, ContentTypeStats):
            lines.append(
                f"- {s.content_type}: {s.video_count}本"
                f" 平均再生:{s.avg_views:,.0f}"
            )
    return "\n".join(lines) if lines else "データなし"


def _format_hit_predictions(videos: list[Any]) -> str:
    lines: list[str] = []
    for i, v in enumerate(videos[:5], 1):
        from .models import GrowthMetrics
        if isinstance(v, GrowthMetrics):
            lines.append(
                f"{i}. 「{v.title}」"
                f" スコア:{v.hit_prediction_score:.0f}/100"
            )
    return "\n".join(lines) if lines else "対象なし"


def build_prompt(data: ReportData) -> str:
    return _ANALYSIS_PROMPT_TEMPLATE.format(
        channel_name=data.channel_metrics.channel_name,
        report_date=data.report_date,
        subscriber_count=data.channel_metrics.current_subscribers,
        subscriber_delta=data.channel_metrics.delta_subscribers_24h,
        view_count=data.channel_metrics.current_views,
        view_delta=data.channel_metrics.delta_views_24h,
        video_count=data.channel_metrics.current_video_count,
        posts_per_month=data.channel_metrics.posts_per_month,
        shorts_ratio=data.channel_metrics.shorts_ratio,
        rising_videos=_format_videos(data.rising_videos),
        declining_videos=_format_videos(data.declining_videos),
        shorts_growth_rate=data.shorts_growth_rate,
        regular_growth_rate=data.regular_growth_rate,
        content_type_stats=_format_content_types(data.content_type_stats),
        hit_predictions=_format_hit_predictions(data.hit_predictions),
    )


# ── Provider base class ───────────────────────────────────────────────────────


class AIProvider(ABC):
    """Abstract base for LLM providers."""

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def complete(self, prompt: str) -> tuple[str, str, int]:
        """Return (response_text, model_name, prompt_token_estimate)."""
        ...


# ── Ollama provider ───────────────────────────────────────────────────────────


class OllamaProvider(AIProvider):
    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def is_available(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=5.0)
            return r.status_code == 200
        except Exception:
            return False

    def complete(self, prompt: str) -> tuple[str, str, int]:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.7, "num_predict": 2048},
        }
        r = httpx.post(
            f"{self.base_url}/api/generate",
            json=payload,
            timeout=120.0,
        )
        r.raise_for_status()
        data = r.json()
        text: str = data.get("response", "")
        tokens: int = data.get("prompt_eval_count", len(prompt) // 4)
        return text, self.model, tokens


# ── OpenAI-compatible provider ────────────────────────────────────────────────


class OpenAIProvider(AIProvider):
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    def is_available(self) -> bool:
        return bool(self.api_key)

    def complete(self, prompt: str) -> tuple[str, str, int]:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        resp = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2048,
            temperature=0.7,
        )
        text = resp.choices[0].message.content or ""
        tokens = resp.usage.prompt_tokens if resp.usage else len(prompt) // 4
        return text, self.model, tokens


# ── Claude provider ───────────────────────────────────────────────────────────


class ClaudeProvider(AIProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def is_available(self) -> bool:
        return bool(self.api_key)

    def complete(self, prompt: str) -> tuple[str, str, int]:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        msg = client.messages.create(
            model=self.model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text if msg.content else ""  # type: ignore[union-attr]
        tokens = msg.usage.input_tokens if msg.usage else len(prompt) // 4
        return text, self.model, tokens


# ── Factory + main analyzer ───────────────────────────────────────────────────


def _build_providers(config: Config) -> list[AIProvider]:
    providers: list[AIProvider] = []
    mode = config.ai_provider.lower()

    if mode == "none":
        return []

    if mode in ("auto", "ollama"):
        providers.append(OllamaProvider(config.ollama_base_url, config.ollama_model))
    if mode in ("auto", "openai"):
        providers.append(OpenAIProvider(config.openai_api_key, config.openai_base_url, config.openai_model))
    if mode in ("auto", "claude"):
        providers.append(ClaudeProvider(config.claude_api_key, config.claude_model))

    if mode not in ("auto", "none", "ollama", "openai", "claude"):
        logger.warning("Unknown AI_PROVIDER '%s'; using auto mode", config.ai_provider)
        providers = [
            OllamaProvider(config.ollama_base_url, config.ollama_model),
            OpenAIProvider(config.openai_api_key, config.openai_base_url, config.openai_model),
            ClaudeProvider(config.claude_api_key, config.claude_model),
        ]

    return providers


class AIAnalyzer:
    """Wraps LLM providers with fallback chain and report data formatting."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._providers = _build_providers(config)

    def _pick_provider(self) -> Optional[AIProvider]:
        for p in self._providers:
            if p.is_available():
                logger.info("Using AI provider: %s", type(p).__name__)
                return p
        return None

    def generate_analysis(self, data: ReportData) -> tuple[str, str, int]:
        """Generate full AI analysis. Returns (text, model_name, tokens)."""
        provider = self._pick_provider()
        if not provider:
            logger.info("No AI provider available; skipping AI analysis")
            return "", "none", 0

        prompt = build_prompt(data)
        try:
            text, model, tokens = provider.complete(prompt)
            logger.info("AI analysis generated by %s (%d tokens)", model, tokens)
            return text, model, tokens
        except Exception as exc:
            logger.warning("AI analysis failed: %s", exc)
            return "", "error", 0
