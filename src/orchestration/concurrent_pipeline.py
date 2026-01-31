"""Concurrent paper processing pipeline.

Implements async producer-consumer pattern with:
- Bounded queue with backpressure
- Semaphore-based resource limiting
- Worker pool management
- Integration with Phase 2.5 FallbackPDFService
- Integration with Phase 3 intelligence services
"""

import asyncio
from typing import List, AsyncIterator, Optional
from pathlib import Path
import time
import structlog

from src.models.paper import PaperMetadata
from src.models.extraction import ExtractionTarget, ExtractedPaper
from src.models.concurrency import ConcurrencyConfig, PipelineStats, WorkerStats

# Phase 2.5 integration
from src.services.pdf_extractors.fallback_service import FallbackPDFService

# Phase 3 integrations
from src.services.cache_service import CacheService
from src.services.dedup_service import DeduplicationService
from src.services.filter_service import FilterService
from src.services.checkpoint_service import CheckpointService
from src.services.llm_service import LLMService

logger = structlog.get_logger()


class ConcurrentPipeline:
    """Concurrent paper processing pipeline.

    Coordinates all services (cache, dedup, filter, PDF, LLM, checkpoint)
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
        """
        self.config = config
        self.fallback_pdf_service = fallback_pdf_service
        self.llm_service = llm_service
        self.cache_service = cache_service
        self.dedup_service = dedup_service
        self.filter_service = filter_service
        self.checkpoint_service = checkpoint_service

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
    ) -> AsyncIterator[ExtractedPaper]:
        """Process papers concurrently with full intelligence pipeline.

        Pipeline stages:
        1. Deduplication (Phase 3) - Remove papers we've seen
        2. Filtering (Phase 3) - Apply quality filters
        3. Cache check (Phase 3) - Skip papers with cached extractions
        4. Concurrent processing:
           a. PDF extraction (Phase 2.5 multi-backend)
           b. LLM extraction
           c. Checkpoint (Phase 3)

        Args:
            papers: Papers to process
            targets: Extraction targets
            run_id: Unique run identifier
            query: Search query (for relevance ranking)

        Yields:
            ExtractedPaper as they complete (unordered)
        """
        start_time = time.time()

        logger.info(
            "concurrent_processing_started", run_id=run_id, total_papers=len(papers)
        )

        # Stage 1: Deduplication
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

            # Checkpoint periodically with accumulated IDs
            if completed % self.config.checkpoint_interval == 0:
                self.checkpoint_service.save_checkpoint(
                    run_id=run_id,
                    processed_paper_ids=processed_paper_ids,
                    completed=False,
                )

            # Update stats
            self.stats.queue_size = input_queue.qsize()

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
                except asyncio.TimeoutError:
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

                finally:
                    duration = time.time() - start_time
                    worker_stats.total_duration_seconds += duration
                    input_queue.task_done()

            except Exception as e:
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
                try:
                    # Phase 2.5 FallbackPDFService automatically tries:
                    # PyMuPDF → pdfplumber → marker → pandoc
                    pdf_result = await self.fallback_pdf_service.extract_with_fallback(
                        pdf_path=Path(str(paper.open_access_pdf))
                    )

                    if pdf_result and pdf_result.success and pdf_result.markdown:
                        markdown_content = pdf_result.markdown

                        logger.info(
                            "pdf_extraction_complete",
                            worker_id=worker_id,
                            paper_id=paper.paper_id,
                            backend=(
                                pdf_result.backend.value if pdf_result.backend else None
                            ),
                            quality_score=pdf_result.quality_score or 0.0,
                        )
                    else:
                        error_msg = pdf_result.error if pdf_result else "Unknown error"
                        raise Exception(f"PDF extraction failed: {error_msg}")

                except Exception as e:
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

            except Exception as e:
                logger.error("result_collection_error", error=str(e), exc_info=True)

    def get_stats(self) -> PipelineStats:
        """Get current pipeline statistics"""
        return self.stats
