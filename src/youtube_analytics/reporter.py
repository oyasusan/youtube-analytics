"""Report generation: Markdown and HTML via Jinja2 templates."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import Config
from .database import DatabaseManager
from .models import ReportData

logger = logging.getLogger(__name__)


def _relative_graph_path(abs_path: str, target_dir: Path) -> str:
    """Return path relative to target_dir for embedding in reports."""
    try:
        return str(Path(abs_path).relative_to(target_dir.parent))
    except ValueError:
        return abs_path


class Reporter:
    """Generates Markdown and HTML reports and updates GitHub Pages."""

    def __init__(self, config: Config, db: DatabaseManager) -> None:
        self.config = config
        self.db = db
        self._env = Environment(
            loader=FileSystemLoader(str(config.templates_dir)),
            autoescape=select_autoescape(["html"]),
        )
        self._env.filters["format_int"] = lambda v: f"{int(v):,}"
        self._env.filters["format_pct"] = lambda v: f"{v:.1%}"
        self._env.filters["format_float2"] = lambda v: f"{v:.2f}"
        self._env.filters["abs"] = abs
        self._env.filters["split"] = lambda s, sep="/": s.split(sep)
        self._env.filters["basename"] = lambda s: Path(s).name

    # ── Markdown report ───────────────────────────────────────────────────────

    def generate_markdown(self, data: ReportData, date_str: str) -> Path:
        template = self._env.get_template("report.md.j2")
        content = template.render(data=data, generated_at=datetime.utcnow().isoformat())
        out_path = self.config.reports_dir / f"report_{date_str}.md"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
        logger.info("Markdown report: %s", out_path)
        return out_path

    # ── HTML report ───────────────────────────────────────────────────────────

    def generate_html(self, data: ReportData, date_str: str) -> Path:
        template = self._env.get_template("report.html.j2")
        content = template.render(data=data, generated_at=datetime.utcnow().isoformat())
        out_path = self.config.reports_dir / f"report_{date_str}.html"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
        logger.info("HTML report: %s", out_path)
        return out_path

    # ── GitHub Pages ──────────────────────────────────────────────────────────

    def update_github_pages(self, data: ReportData, html_path: Path) -> None:
        """Copy latest report + graphs to docs/ for GitHub Pages."""
        docs = self.config.docs_dir
        docs.mkdir(parents=True, exist_ok=True)

        # Copy report as index.html and as dated file
        date_str = data.report_date
        dest_dated = docs / f"report_{date_str}.html"
        shutil.copy2(str(html_path), str(dest_dated))

        # Copy graphs
        graphs_in_docs = docs / "graphs"
        graphs_in_docs.mkdir(exist_ok=True)
        for src in self.config.graphs_dir.glob("*.png"):
            shutil.copy2(str(src), str(graphs_in_docs / src.name))

        # Generate index page
        recent_reports = self.db.get_recent_reports(30)
        index_template = self._env.get_template("index.html.j2")
        index_content = index_template.render(
            data=data,
            recent_reports=recent_reports,
            generated_at=datetime.utcnow().isoformat(),
        )
        (docs / "index.html").write_text(index_content, encoding="utf-8")
        logger.info("GitHub Pages updated: %s", docs)

    # ── Convenience: full report cycle ────────────────────────────────────────

    def generate_full_report(self, data: ReportData) -> tuple[Path, Path]:
        """Generate both formats, return (md_path, html_path)."""
        date_str = data.report_date
        md_path = self.generate_markdown(data, date_str)
        html_path = self.generate_html(data, date_str)
        self.update_github_pages(data, html_path)
        self.db.insert_report_history(
            report_type="daily",
            report_date=date_str,
            file_path_md=str(md_path),
            file_path_html=str(html_path),
            summary=f"登録者 {data.channel_metrics.current_subscribers:,} / 再生 {data.channel_metrics.current_views:,}",
        )
        return md_path, html_path
