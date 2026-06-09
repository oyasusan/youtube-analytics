# 空想ロマンス YouTube Analytics System

YouTubeチャンネルの公開データを継続的に収集し、AIによる分析レポートを自動生成するシステムです。

[![CI](https://github.com/oyasusan/youtube-analytics/actions/workflows/ci.yml/badge.svg)](https://github.com/oyasusan/youtube-analytics/actions)

---

## アーキテクチャ

```
┌─────────────────────────────────────────────────────────────────┐
│  GitHub Actions                                                   │
│                                                                   │
│  [毎時] hourly.yml         [毎日] daily.yml                        │
│      │                         │                                  │
│      ▼                         ▼                                  │
│  collect.py              daily_analysis.py                        │
│      │                         │                                  │
│      ▼                    ┌────┴────────────────────┐             │
│  YouTube API v3           ▼         ▼         ▼     ▼             │
│  (channels, videos) analyzer  visualizer  ai    reporter          │
│      │                    │         │     │        │              │
│      ▼                    └────┬────┘     │        ▼              │
│  SQLite DB ◄───────────────────┘          │  reports/ graphs/     │
│  (data/youtube_analytics.db)              │  docs/ (GitHub Pages) │
└───────────────────────────────────────────┴───────────────────────┘
```

## ディレクトリ構成

```
youtube-analytics/
├── .github/
│   └── workflows/
│       ├── hourly.yml         # 毎時データ収集
│       ├── daily.yml          # 毎日分析・レポート生成
│       └── ci.yml             # PR時テスト・Lint
├── src/
│   └── youtube_analytics/
│       ├── config.py          # 設定管理
│       ├── models.py          # データモデル
│       ├── database.py        # SQLite操作
│       ├── collector.py       # YouTube API クライアント
│       ├── analyzer.py        # 統計分析エンジン
│       ├── ai_analyzer.py     # AI分析 (Ollama/OpenAI/Claude)
│       ├── visualizer.py      # Matplotlibグラフ生成
│       └── reporter.py        # レポート生成
├── scripts/
│   ├── collect.py             # 毎時収集エントリーポイント
│   ├── daily_analysis.py      # 毎日分析エントリーポイント
│   ├── maintenance.py         # DBメンテナンス
│   └── find_channel.py        # チャンネルID検索ユーティリティ
├── templates/
│   ├── report.md.j2           # Markdownレポートテンプレート
│   ├── report.html.j2         # HTMLレポートテンプレート
│   └── index.html.j2          # GitHub Pagesトップページ
├── tests/                     # pytest テストスイート
├── data/                      # SQLite DB（Git管理対象）
├── docs/                      # GitHub Pages 公開ディレクトリ
├── reports/                   # 生成レポート
├── graphs/                    # 生成グラフ (PNG)
├── pyproject.toml
├── sample.env
└── README.md
```

## DBスキーマ

```sql
channels               -- チャンネルマスタ
channel_snapshots      -- チャンネルスナップショット（毎時）
videos                 -- 動画マスタ
video_snapshots        -- 動画スナップショット（毎時）
daily_video_summaries  -- 動画日次集計
daily_channel_summaries-- チャンネル日次集計
video_scores           -- 動画スコア（勢い/成長/バズ/ロングテール/ファン獲得）
ai_analyses            -- AI分析履歴
report_history         -- レポート生成履歴
```

---

## セットアップ

### 前提条件

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) パッケージマネージャー
- YouTube Data API v3 APIキー

### 1. リポジトリのクローン

```bash
git clone https://github.com/oyasusan/youtube-analytics.git
cd youtube-analytics
```

### 2. 依存関係のインストール

```bash
uv sync
```

### 3. 環境変数の設定

```bash
cp sample.env .env
# .envを編集してAPIキーなどを設定
```

---

## API設定方法

### YouTube Data API v3 キーの取得

1. [Google Cloud Console](https://console.cloud.google.com/) にアクセス
2. 新しいプロジェクトを作成（または既存プロジェクトを使用）
3. 「APIとサービス」→「ライブラリ」→「YouTube Data API v3」を有効化
4. 「認証情報」→「認証情報を作成」→「APIキー」
5. 取得したキーを `.env` の `YOUTUBE_API_KEY` に設定

### チャンネルIDの確認

```bash
# チャンネル名からIDを検索
uv run python scripts/find_channel.py "空想ロマンス"
# → CHANNEL_ID=UC... が表示されます
```

---

## GitHub Actions設定方法

### Secretsの設定

GitHubリポジトリの **Settings → Secrets and variables → Actions → Secrets** で設定:

| Secret名 | 説明 | 必須 |
|---------|-----|------|
| `YOUTUBE_API_KEY` | YouTube Data API v3 キー | ✅ 必須 |
| `OLLAMA_BASE_URL` | Ollama サーバーURL | 任意 |
| `OPENAI_API_KEY` | OpenAI API キー | 任意 |
| `CLAUDE_API_KEY` | Claude API キー | 任意 |

### Variables（公開設定値）の設定

**Settings → Secrets and variables → Actions → Variables** で設定:

| Variable名 | 説明 | デフォルト |
|-----------|-----|---------|
| `CHANNEL_ID` | YouTubeチャンネルID (UC...) | （空=名前で検索） |
| `CHANNEL_NAME` | チャンネル名 | `空想ロマンス` |
| `AI_PROVIDER` | AIプロバイダー: auto/ollama/openai/claude/none | `auto` |
| `MEMBER_NAMES` | メンバー名（カンマ区切り） | 空 |
| `OPENAI_MODEL` | OpenAIモデル名 | `gpt-4o-mini` |
| `CLAUDE_MODEL` | Claudeモデル名 | `claude-haiku-4-5-20251001` |

---

## GitHub Pages設定方法

1. GitHubリポジトリの **Settings → Pages** を開く
2. **Source** を `Deploy from a branch` に設定
3. **Branch** を `main`、**Folder** を `/docs` に設定
4. **Save** をクリック

日次レポート生成後、`https://oyasusan.github.io/youtube-analytics/` でダッシュボードが公開されます。

---

## ローカル実行方法

### データ収集（1回）

```bash
uv run python scripts/collect.py
```

### 日次分析・レポート生成

```bash
uv run python scripts/daily_analysis.py
```

### DBメンテナンス

```bash
uv run python scripts/maintenance.py
```

### テスト実行

```bash
uv run pytest
# カバレッジ付き
uv run pytest --cov=src/youtube_analytics --cov-report=html
```

### Lint / 型チェック

```bash
uv run ruff check src/ scripts/ tests/
uv run mypy src/youtube_analytics/
```

---

## 運用方法

### 通常運用（完全自動）

GitHub Actionsが以下を自動実行します:

| スケジュール | ジョブ | 内容 |
|------------|-------|-----|
| 毎時 `:00` | `hourly.yml` | YouTube APIからデータ収集・DB更新 |
| 毎日 `00:30 UTC` | `daily.yml` | 分析・グラフ生成・レポート作成・Pages更新 |
| 手動 | `daily.yml` (workflow_dispatch) | 即時実行 |

### APIクォータ管理

YouTube Data API v3の無料クォータ: **10,000ユニット/日**

| 処理 | コスト | 1日合計（毎時） |
|-----|-------|--------------|
| channels.list | 1ユニット | 24ユニット |
| playlistItems.list × 4ページ | 4ユニット | 96ユニット |
| videos.list × 4バッチ | 4ユニット | 96ユニット |
| **合計** | **約9ユニット/時** | **約216ユニット/日** |

※ 動画数が増えるとコストが増加しますが、1,000本以下では余裕があります。

### DBサイズ管理

- `data/youtube_analytics.db` のサイズを毎時チェック
- **400MB**: 警告ログ出力
- **500MB**: メンテナンス推奨（古いスナップショットをアーカイブ）
- `scripts/maintenance.py` で手動クリーンアップ可能

### AI分析プロバイダー

優先順位 (`AI_PROVIDER=auto` の場合):

1. **Ollama** (ローカルLLM・完全無料) - `OLLAMA_BASE_URL` を設定
2. **OpenAI** - `OPENAI_API_KEY` を設定（gpt-4o-mini推奨）
3. **Claude** - `CLAUDE_API_KEY` を設定
4. **なし** - 統計分析のみで動作

---

## 今後の拡張案

1. **チャンネル比較分析** - 競合チャンネルとのベンチマーク
2. **メール通知** - バズ動画をGitHub Actions + メール送信
3. **Slack/Discord通知** - Webhook経由のリアルタイムアラート
4. **月次レポート** - 月次集計・長期トレンド分析
5. **感情分析** - コメントテキストのポジ/ネガ分析
6. **サムネイル分析** - 画像認識によるサムネイルパターン分析
7. **Twitter連携** - 関連ツイートとの相関分析
8. **複数チャンネル対応** - スキーマ拡張で複数チャンネルを一元管理

---

## 技術スタック

| カテゴリ | 技術 |
|---------|-----|
| 言語 | Python 3.12 |
| パッケージ管理 | uv |
| DB | SQLite (WAL mode) |
| YouTube API | google-api-python-client |
| データ処理 | pandas |
| グラフ | matplotlib |
| テンプレート | Jinja2 |
| AI | Ollama / OpenAI / Anthropic |
| テスト | pytest + pytest-cov |
| Lint | Ruff |
| 型チェック | mypy |
| CI/CD | GitHub Actions |
| ホスティング | GitHub Pages |

---

## ライセンス

MIT License - 詳細は [LICENSE](LICENSE) を参照
