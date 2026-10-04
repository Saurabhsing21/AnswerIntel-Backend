import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime, timezone

from sqlalchemy import select

from app.analysis.base import AnalysisContext
from app.analysis.persistence import save_analysis
from app.analysis.service import ResponseAnalysisService
from app.common.config import settings
from app.common.database import SessionLocal
from app.competitors.models import Competitor
from app.metrics.service import compute_and_store
from app.opportunities.service import generate_and_store
from app.projects.models import Project
from app.prompts.models import ScanPrompt
from app.providers.base import AIProvider, ProviderContext
from app.providers.registry import ModelRegistry, get_provider
from app.providers.response_model import AIResponseRecord
from app.scans.models import Scan

log = logging.getLogger(__name__)


class ScanExecutionService:
    """Runs one queued scan: provider calls in parallel, persistence on one thread."""

    def __init__(
        self,
        provider: AIProvider | None = None,
        model_registry: ModelRegistry | None = None,
        analysis_service: ResponseAnalysisService | None = None,
    ):
        self.provider = provider or get_provider()
        self.model_registry = model_registry or ModelRegistry()
        self.analysis_service = analysis_service or ResponseAnalysisService()

    def run(self, scan_id: int) -> None:
        try:
            self._run(scan_id)
        except Exception as exc:  # never leave a scan stuck in "running"
            log.exception("Scan %s crashed", scan_id)
            with SessionLocal() as session:
                scan = session.get(Scan, scan_id)
                if scan and scan.status in ("queued", "running"):
                    scan.status = "failed"
                    scan.error_message = f"Scan crashed: {exc.__class__.__name__}"
                    scan.completed_at = datetime.now(timezone.utc)
                    session.commit()

    def _run(self, scan_id: int) -> None:
        with SessionLocal() as session:
            scan = session.get(Scan, scan_id)
            if not scan or scan.status != "queued":
                return  # idempotent: a scan is executed at most once
            project = session.get(Project, scan.project_id)
            competitors = session.scalars(select(Competitor).where(Competitor.project_id == project.id)).all()
            prompts = session.scalars(
                select(ScanPrompt).where(ScanPrompt.scan_id == scan.id).order_by(ScanPrompt.id)
            ).all()
            engines = self.model_registry.get_all()

            analysis_context = AnalysisContext(
                brand_name=project.brand_name,
                competitors=[{"id": c.id, "name": c.name, "website": c.website} for c in competitors],
                brand_website=project.website,
            )
            provider_context = ProviderContext(
                brand_name=project.brand_name,
                competitors=[c.name for c in competitors],
                brand_website=project.website,
                variation=scan.id,
            )

            scan.status = "running"
            scan.started_at = datetime.now(timezone.utc)
            scan.provider = self.provider.name
            scan.total_runs = len(prompts) * len(engines)
            session.commit()

            def work(prompt: ScanPrompt, engine):
                response = self.provider.ask(prompt.text, engine.model, provider_context)
                result = self.analysis_service.analyze(
                    response.text,
                    replace(analysis_context, prompt=prompt.text),
                    citations=response.citations,
                )
                return response, result

            last_error: str | None = None
            jobs = [(p.id, p.text, p.category, p.intent, e) for p in prompts for e in engines]
            snapshot = {p.id: p for p in prompts}
            with ThreadPoolExecutor(max_workers=max(1, settings.scan_concurrency)) as pool:
                futures = {pool.submit(work, snapshot[pid], engine): (pid, engine) for pid, _, _, _, engine in jobs}
                for future in as_completed(futures):
                    prompt_id, engine = futures[future]
                    try:
                        response, result = future.result()
                    except Exception as exc:
                        scan.failed_runs += 1
                        last_error = f"{engine.display_name}: {exc}"[:500]
                        session.commit()
                        continue
                    record = AIResponseRecord(
                        scan_id=scan.id,
                        scan_prompt_id=prompt_id,
                        engine=engine.key,
                        provider=response.provider,
                        model=response.model,
                        prompt=response.prompt,
                        response_text=response.text,
                        raw_response=response.raw_response,
                        latency_ms=response.latency_ms,
                    )
                    session.add(record)
                    session.flush()
                    save_analysis(session, record.id, result)
                    scan.completed_runs += 1
                    session.commit()

            if scan.completed_runs:
                data = compute_and_store(session, scan)
                generate_and_store(session, scan, project.brand_name, data["observations"])

            if scan.failed_runs == 0:
                scan.status = "completed"
            elif scan.completed_runs > 0:
                scan.status = "partial"
            else:
                scan.status = "failed"
            scan.error_message = last_error if scan.failed_runs else None
            scan.completed_at = datetime.now(timezone.utc)
            session.commit()


def run_scan(scan_id: int) -> None:
    ScanExecutionService().run(scan_id)


def recover_interrupted_scans() -> int:
    """Single-process MVP: scans still active at startup were interrupted by a restart."""
    with SessionLocal() as session:
        stale = session.scalars(select(Scan).where(Scan.status.in_(("queued", "running")))).all()
        for scan in stale:
            scan.status = "failed" if not scan.completed_runs else "partial"
            scan.error_message = "Interrupted by a server restart."
            scan.completed_at = datetime.now(timezone.utc)
        session.commit()
        return len(stale)
