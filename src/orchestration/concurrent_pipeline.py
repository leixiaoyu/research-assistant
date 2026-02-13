"""Concurrent paper processing pipeline.

Implements async producer-consumer pattern with:
- Bounded queue with backpressure
- Semaphore-based resource limiting
- Worker pool management
- Integration with Phase 2.5 FallbackPDFService
- Integration with Phase 3 intelligence services
- Integration with Phase 3.5 RegistryService (global identity)
- Prometheus metrics export (Phase 4)
"""

import asyncio
from typing import List, AsyncIterator, Optional, Dict
from pathlib import Path
import time
import structlog

from src.models.paper import PaperMetadata
from src.models.extraction import ExtractionTarget, ExtractedPaper
from src.models.concurrency import ConcurrencyConfig, PipelineStats, WorkerStats
from src.models.registry import ProcessingAction, RegistryEntry
from src.models.synthesis import ProcessingResult, ProcessingStatus

# Phase 2.5 integration
from src.services.pdf_extractors.fallback_service import FallbackPDFService

# Phase 3 integrations
from src.services.cache_service import CacheService
from src.services.dedup_service import DeduplicationService
from src.services.filter_service import FilterService
from src.services.checkpoint_service import CheckpointService
from src.services.llm_service import LLMService

# Phase 3.5 integration
from src.services.registry_service import RegistryService

# Phase 4: Prometheus metrics
from src.observability.metrics import (
    PAPERS_PROCESSED,
    ACTIVE_WORKERS,
    QUEUE_SIZE,
    PAPERS_IN_QUEUE,
    PAPER_PROCESSING_DURATION,
    PDF_DOWNLOADS,
    PDF_CONVERSIONS,
    EXTRACTION_ERRORS,
)

logger = structlog.get_logger()


class ConcurrentPipeline:
    """Concurrent paper processing pipeline.

    Coordinates all services (cache, dedup, filter, PDF, LLM, checkpoint, registry)
    with concurrent worker pool and intelligent resource management.
    """

    def __init__(
        self,
        config: ConcurrencyConfig,
        fallback_pdf_service: FallbackPDFService,  # Phase 2.5
        llm_service: LLMService,
        cache_service: CacheService,  # Phase 3
        dedup_service: DeduplicationService,  # Phase 3
        filter_service: FilterService,  # Phase 3
        checkpoint_service: CheckpointService,  # Phase 3
        registry_service: Optional[RegistryService] = None,  # Phase 3.5
    ):
        """Initialize concurrent pipeline.

        Args:
            config: Concurrency configuration
            fallback_pdf_service: Multi-backend PDF service (Phase 2.5)
            llm_service: LLM extraction service
            cache_service: Caching service (Phase 3)
            dedup_service: Deduplication service (Phase 3)
            filter_service: Filtering service (Phase 3)
            checkpoint_service: Checkpoint service (Phase 3)
            registry_service: Registry service for global identity (Phase 3.5)
        """
        self.config = config
        self.fallback_pdf_service = fallback_pdf_service
        self.llm_service = llm_service
        self.cache_service = cache_service
        self.dedup_service = dedup_service
        self.filter_service = filter_service
        self.checkpoint_service = checkpoint_service
        self.registry_service = registry_service

        # Processing results for Phase 3.6 synthesis
        self.processing_results: List[ProcessingResult] = []

        # Semaphores for resource limiting
        self.download_sem = asyncio.Semaphore(config.max_concurrent_downloads)
        self.conversion_sem = asyncio.Semaphore(config.max_concurrent_conversions)
        self.llm_sem = asyncio.Semaphore(config.max_concurrent_llm)

        # Statistics
        self.stats = PipelineStats()
        self.worker_stats: List[WorkerStats] = []

        logger.info(
            "concurrent_pipeline_initialized",
            max_downloads=config.max_concurrent_downloads,
            max_conversions=config.max_concurrent_conversions,
            max_llm=config.max_concurrent_llm,
            queue_size=config.queue_size,
        )

    async def process_papers_concurrent(
        self,
        papers: List[PaperMetadata],
        targets: List[ExtractionTarget],
        run_id: str,
        query: str,
        topic_slug: Optional[str] = None,
    ) -> AsyncIterator[ExtractedPaper]:
        """Process papers concurrently with full intelligence pipeline.

        Pipeline stages:
        1. Registry check (Phase 3.5) - Global identity resolution if available
        2. Deduplication (Phase 3) - Remove papers we've seen (fallback)
        3. Filtering (Phase 3) - Apply quality filters
        4. Cache check (Phase 3) - Skip papers with cached extractions
        5. Concurrent processing:
           a. PDF extraction (Phase 2.5 multi-backend)
           b. LLM extraction
           c. Checkpoint (Phase 3)

        Args:
            papers: Papers to process
            targets: Extraction targets
            run_id: Unique run identifier
            query: Search query (for relevance ranking)
            topic_slug: Topic slug for registry affiliation (Phase 3.5)

        Yields:
            ExtractedPaper as they complete (unordered)
        """
        start_time = time.time()

        # Clear processing results for this run
        self.processing_results = []

        logger.info(
            "concurrent_processing_started", run_id=run_id, total_papers=len(papers)
        )

        # Stage 1: Registry-based identity resolution (Phase 3.5)
        new_papers: List[PaperMetadata] = []
        duplicates: List[PaperMetadata] = []
        # Track existing entries for backfill persistence
        backfill_entries: Dict[str, RegistryEntry] = {}

        if self.registry_service and topic_slug:
            # Use global registry for identity resolution
            for paper in papers:
                action, existing_entry = self.registry_service.determine_action(
                    paper, topic_slug, targets
                )

                if action == ProcessingAction.FULL_PROCESS:
                    new_papers.append(paper)
                    self._add_processing_result(paper, ProcessingStatus.NEW, topic_slug)
                elif action == ProcessingAction.BACKFILL:
                    new_papers.append(paper)  # Process it
                    self._add_processing_result(
                        paper, ProcessingStatus.BACKFILLED, topic_slug
                    )
                    # Store existing entry for persistence update
                    if existing_entry:
                        backfill_entries[paper.paper_id] = existing_entry
                elif action == ProcessingAction.MAP_ONLY:
                    # Just add topic affiliation, no processing needed
                    duplicates.append(paper)
                    self._add_processing_result(
                        paper, ProcessingStatus.MAPPED, topic_slug
                    )
                    # Register topic affiliation for MAP_ONLY
                    if existing_entry:
                        self.registry_service.add_topic_affiliation(
                            existing_entry, topic_slug
                        )
                else:  # SKIP
                    duplicates.append(paper)
                    self._add_processing_result(
                        paper, ProcessingStatus.SKIPPED, topic_slug
                    )

            logger.info(
                "registry_resolution_complete",
                total=len(papers),
                new=sum(
                    1
                    for r in self.processing_results
                    if r.status == ProcessingStatus.NEW
                ),
                backfill=sum(
                    1
                    for r in self.processing_results
                    if r.status == ProcessingStatus.BACKFILLED
                ),
                skipped=len(duplicates),
            )
        else:
            # Fallback to legacy deduplication (Phase 3)
            new_papers, duplicates = self.dedup_service.find_duplicates(papers)

        self.stats.total_papers = len(papers)
        self.stats.papers_deduplicated = len(duplicates)

        logger.info(
            "deduplication_complete",
            total=len(papers),
            new=len(new_papers),
            duplicates=len(duplicates),
        )

        # Stage 2: Filtering
        filtered_papers = self.filter_service.filter_and_rank(new_papers, query)

        # Stage 3: Checkpoint - resume from interruption
        processed_ids = self.checkpoint_service.get_processed_ids(run_id)
        pending_papers = [p for p in filtered_papers if p.paper_id not in processed_ids]

        logger.info(
            "checkpoint_loaded",
            run_id=run_id,
            already_processed=len(processed_ids),
            pending=len(pending_papers),
        )

        if not pending_papers:
            logger.info("no_papers_to_process", run_id=run_id)
            return

        # Stage 4: Concurrent processing with bounded queues
        input_queue: asyncio.Queue[Optional[PaperMetadata]] = asyncio.Queue(
            maxsize=self.config.queue_size
        )
        results_queue: asyncio.Queue[Optional[ExtractedPaper]] = asyncio.Queue(
            maxsize=self.config.queue_size
        )

        # Start workers
        num_workers = min(self.config.max_concurrent_downloads, len(pending_papers))

        workers: List[asyncio.Task] = [
            asyncio.create_task(
                self._worker(
                    worker_id=i,
                    input_queue=input_queue,
                    results_queue=results_queue,
                    targets=targets,
                    run_id=run_id,
                )
            )
            for i in range(num_workers)
        ]

        self.stats.active_workers = num_workers

        # Update metrics
        ACTIVE_WORKERS.labels(worker_type="pipeline").set(num_workers)
        PAPERS_IN_QUEUE.set(len(pending_papers))

        logger.info(
            "workers_started",
            num_workers=num_workers,
            pending_papers=len(pending_papers),
        )

        # Producer: Feed input queue
        producer = asyncio.create_task(
            self._produce(input_queue, pending_papers, num_workers)
        )

        # Consumer: Collect results and yield
        completed = 0
        processed_paper_ids: List[str] = []

        async for result in self._collect_results(results_queue, num_workers):
            yield result

            completed += 1
            self.stats.papers_completed = completed
            processed_paper_ids.append(result.metadata.paper_id)

            # Phase 3.5: Persist to global registry after successful extraction
            if self.registry_service and topic_slug:
                paper_id = result.metadata.paper_id
                existing_entry = backfill_entries.get(paper_id)

                # Get PDF path from result if available
                pdf_path = None
                if hasattr(result, "pdf_path") and result.pdf_path:
                    pdf_path = str(result.pdf_path)

                self.registry_service.register_paper(
                    paper=result.metadata,
                    topic_slug=topic_slug,
                    extraction_targets=targets,
                    pdf_path=pdf_path,
                    existing_entry=existing_entry,  # For backfill updates
                )

                logger.debug(
                    "registry_paper_persisted",
                    paper_id=paper_id,
                    is_backfill=existing_entry is not None,
                    topic=topic_slug,
                )

            # Update metrics
            PAPERS_PROCESSED.labels(status="success").inc()
            PAPERS_IN_QUEUE.dec()

            # Checkpoint periodically with accumulated IDs
            if completed % self.config.checkpoint_interval == 0:
                self.checkpoint_service.save_checkpoint(
                    run_id=run_id,
                    processed_paper_ids=processed_paper_ids,
                    completed=False,
                )

            # Update stats
            self.stats.queue_size = input_queue.qsize()
            QUEUE_SIZE.labels(queue_name="input").set(input_queue.qsize())
            QUEUE_SIZE.labels(queue_name="results").set(results_queue.qsize())

            logger.info(
                "progress_update",
                run_id=run_id,
                completed=completed,
                total=len(pending_papers),
                progress=f"{completed/len(pending_papers):.1%}",
            )

        # Wait for producer and workers to finish
        await producer
        await asyncio.gather(*workers, return_exceptions=True)

        # Reset worker metrics
        ACTIVE_WORKERS.labels(worker_type="pipeline").set(0)

        # Final checkpoint save
        if processed_paper_ids:
            self.checkpoint_service.save_checkpoint(
                run_id=run_id,
                processed_paper_ids=processed_paper_ids,
                completed=True,
            )

        # Update dedup indices with processed papers
        successful_papers = [
            p for p in filtered_papers if p.paper_id not in processed_ids
        ]
        self.dedup_service.update_indices(successful_papers)

        # Clear checkpoint after successful completion
        self.checkpoint_service.clear_checkpoint(run_id)

        # Final statistics
        self.stats.total_duration_seconds = time.time() - start_time

        # Track skipped/failed papers
        PAPERS_PROCESSED.labels(status="skipped").inc(self.stats.papers_deduplicated)

        logger.info(
            "concurrent_processing_complete",
            run_id=run_id,
            total_papers=len(papers),
            completed=self.stats.papers_completed,
            failed=self.stats.papers_failed,
            deduplicated=self.stats.papers_deduplicated,
            duration_seconds=round(self.stats.total_duration_seconds, 2),
            papers_per_minute=round(
                self.stats.papers_completed / (self.stats.total_duration_seconds / 60),
                2,
            ),
        )

    async def _produce(
        self, queue: asyncio.Queue, papers: List[PaperMetadata], num_workers: int
    ) -> None:
        """Producer coroutine: Feed papers to queue.

        Implements backpressure: blocks if queue is full.
        """
        for paper in papers:
            await queue.put(paper)

        # Send sentinel values to signal workers to stop
        for _ in range(num_workers):
            await queue.put(None)

        logger.debug("producer_finished", papers_fed=len(papers))

    async def _worker(
        self,
        worker_id: int,
        input_queue: asyncio.Queue,
        results_queue: asyncio.Queue,
        targets: List[ExtractionTarget],
        run_id: str,
    ) -> None:
        """Worker coroutine: Process papers from queue.

        Each worker:
        1. Gets paper from input_queue
        2. Checks cache (Phase 3)
        3. Downloads + converts PDF (Phase 2.5 multi-backend)
        4. Extracts with LLM
        5. Caches result (Phase 3)
        6. Puts result in results_queue

        Args:
            worker_id: Unique worker identifier
            input_queue: Shared paper queue
            results_queue: Queue for completed results
            targets: Extraction targets
            run_id: Run identifier
        """
        worker_stats = WorkerStats(worker_id=worker_id)
        self.worker_stats.append(worker_stats)

        logger.info("worker_started", worker_id=worker_id)

        while True:
            try:
                # Get paper from queue (with timeout to check for shutdown)
                try:
                    paper = await asyncio.wait_for(input_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:  # pragma: no cover (worker timeout loop)
                    continue

                # Sentinel value = shutdown signal
                if paper is None:
                    logger.info("worker_shutting_down", worker_id=worker_id)
                    break

                # Process paper
                start_time = time.time()

                try:
                    result = await self._process_single_paper(paper, targets, worker_id)

                    if result:
                        await results_queue.put(result)
                        worker_stats.papers_processed += 1
                    else:
                        worker_stats.papers_failed += 1
                        self.stats.papers_failed += 1
                        PAPERS_PROCESSED.labels(status="failed").inc()

                except Exception as e:
                    logger.error(
                        "worker_processing_error",
                        worker_id=worker_id,
                        paper_id=paper.paper_id,
                        error=str(e),
                        exc_info=True,
                    )
                    worker_stats.papers_failed += 1
                    self.stats.papers_failed += 1
                    PAPERS_PROCESSED.labels(status="failed").inc()

                finally:
                    duration = time.time() - start_time
                    worker_stats.total_duration_seconds += duration
                    input_queue.task_done()

            except Exception as e:  # pragma: no cover (defensive catch-all)
                logger.error(
                    "worker_error", worker_id=worker_id, error=str(e), exc_info=True
                )

        # Send sentinel to signal this worker is done
        await results_queue.put(None)
        worker_stats.is_active = False

        logger.info(
            "worker_finished",
            worker_id=worker_id,
            processed=worker_stats.papers_processed,
            failed=worker_stats.papers_failed,
            avg_duration=round(
                worker_stats.total_duration_seconds
                / max(1, worker_stats.papers_processed),
                2,
            ),
        )

    async def _process_single_paper(
        self, paper: PaperMetadata, targets: List[ExtractionTarget], worker_id: int
    ) -> Optional[ExtractedPaper]:
        """Process single paper with full pipeline.

        1. Check extraction cache
        2. If not cached:
           a. Download + convert PDF (Phase 2.5)
           b. Extract with LLM
           c. Cache result

        Args:
            paper: Paper to process
            targets: Extraction targets
            worker_id: Worker ID (for logging)

        Returns:
            ExtractedPaper or None if processing failed
        """
        logger.debug(
            "processing_paper_start",
            worker_id=worker_id,
            paper_id=paper.paper_id,
            title=paper.title[:50] if paper.title else "Untitled",
        )

        # Check extraction cache (Phase 3)
        cached_extraction = self.cache_service.get_extraction(paper.paper_id, targets)

        if cached_extraction:
            logger.info(
                "extraction_cache_hit", worker_id=worker_id, paper_id=paper.paper_id
            )
            self.stats.papers_cached += 1

            return ExtractedPaper(
                metadata=paper,
                extraction=cached_extraction,
                pdf_available=True,  # Assume PDF was available when cached
            )

        # Not cached - process from scratch

        # Download + convert PDF with Phase 2.5 multi-backend fallback
        pdf_result = None
        markdown_content = ""

        if paper.open_access_pdf:
            async with self.download_sem:
                pdf_start = time.time()
                try:
                    # Phase 2.5 FallbackPDFService automatically tries:
                    # PyMuPDF → pdfplumber → marker → pandoc
                    pdf_result = await self.fallback_pdf_service.extract_with_fallback(
                        pdf_path=Path(str(paper.open_access_pdf))
                    )

                    if pdf_result and pdf_result.success and pdf_result.markdown:
                        markdown_content = pdf_result.markdown

                        # Track successful PDF conversion
                        backend_name = (
                            pdf_result.backend.value
                            if pdf_result.backend
                            else "unknown"
                        )
                        PDF_CONVERSIONS.labels(
                            backend=backend_name, status="success"
                        ).inc()
                        PDF_DOWNLOADS.labels(status="success").inc()

                        # Track processing duration
                        PAPER_PROCESSING_DURATION.labels(stage="conversion").observe(
                            time.time() - pdf_start
                        )

                        logger.info(
                            "pdf_extraction_complete",
                            worker_id=worker_id,
                            paper_id=paper.paper_id,
                            backend=backend_name,
                            quality_score=pdf_result.quality_score or 0.0,
                        )
                    else:
                        error_msg = pdf_result.error if pdf_result else "Unknown error"
                        PDF_DOWNLOADS.labels(status="failed").inc()
                        PDF_CONVERSIONS.labels(backend="unknown", status="failed").inc()
                        raise Exception(f"PDF extraction failed: {error_msg}")

                except Exception as e:
                    EXTRACTION_ERRORS.labels(error_type="conversion").inc()
                    logger.error(
                        "pdf_extraction_failed",
                        worker_id=worker_id,
                        paper_id=paper.paper_id,
                        error=str(e),
                    )

        # Prepare content for LLM
        if markdown_content:
            pdf_available = True
        elif paper.abstract:
            # Fallback to abstract
            markdown_content = f"# {paper.title or 'Untitled'}\n\n{paper.abstract}"
            pdf_available = False
            logger.warning(
                "using_abstract_fallback",
                worker_id=worker_id,
                paper_id=paper.paper_id,
            )
        else:
            logger.error(
                "no_content_available", worker_id=worker_id, paper_id=paper.paper_id
            )
            return None

        # Extract with LLM
        async with self.llm_sem:
            try:
                extraction = await self.llm_service.extract(
                    markdown_content, targets, paper
                )

                logger.info(
                    "llm_extraction_complete",
                    worker_id=worker_id,
                    paper_id=paper.paper_id,
                )

                # Cache extraction result (Phase 3)
                self.cache_service.set_extraction(paper.paper_id, targets, extraction)

                return ExtractedPaper(
                    metadata=paper, extraction=extraction, pdf_available=pdf_available
                )

            except Exception as e:
                logger.error(
                    "llm_extraction_failed",
                    worker_id=worker_id,
                    paper_id=paper.paper_id,
                    error=str(e),
                )
                return None

    async def _collect_results(
        self, results_queue: asyncio.Queue, num_workers: int
    ) -> AsyncIterator[ExtractedPaper]:
        """Collect results from queue until all workers done.

        Args:
            results_queue: Queue containing completed ExtractedPaper results
            num_workers: Number of workers to wait for completion

        Yields:
            ExtractedPaper as workers produce them
        """
        workers_done = 0

        while workers_done < num_workers:
            try:
                result = await results_queue.get()

                if result is None:
                    # Sentinel value - a worker has finished
                    workers_done += 1
                    logger.debug("worker_sentinel_received", workers_done=workers_done)
                else:
                    # Valid result - yield to caller
                    yield result

            except Exception as e:  # pragma: no cover (defensive catch-all)
                logger.error("result_collection_error", error=str(e), exc_info=True)

    def get_stats(self) -> PipelineStats:
        """Get current pipeline statistics"""
        return self.stats

    def get_processing_results(self) -> List[ProcessingResult]:
        """Get processing results for Phase 3.6 synthesis.

        Returns:
            List of ProcessingResult objects from the current run.
        """
        return self.processing_results

    def _add_processing_result(
        self,
        paper: PaperMetadata,
        status: ProcessingStatus,
        topic_slug: str,
        quality_score: float = 0.0,
        pdf_available: bool = False,
        extraction_success: bool = False,
        error_message: Optional[str] = None,
    ) -> None:
        """Add a processing result for a paper.

        Args:
            paper: Paper that was processed.
            status: Processing status.
            topic_slug: Topic this result belongs to.
            quality_score: Quality score if available.
            pdf_available: Whether PDF was available.
            extraction_success: Whether extraction succeeded.
            error_message: Error message if failed.
        """
        result = ProcessingResult(
            paper_id=paper.paper_id,
            title=paper.title or "Untitled",
            status=status,
            quality_score=quality_score,
            pdf_available=pdf_available,
            extraction_success=extraction_success,
            topic_slug=topic_slug,
            error_message=error_message,
        )
        self.processing_results.append(result)
