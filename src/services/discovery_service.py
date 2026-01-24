from typing import List, Dict
import structlog

from src.services.providers.base import DiscoveryProvider, APIError
from src.services.providers.semantic_scholar import SemanticScholarProvider
from src.services.providers.arxiv import ArxivProvider
from src.models.config import ResearchTopic, ProviderType
from src.models.paper import PaperMetadata

logger = structlog.get_logger()


class DiscoveryService:
    """Wrapper service for paper discovery with multi-provider support"""

    def __init__(self, api_key: str = ""):
        self.providers: Dict[str, DiscoveryProvider] = {}

        # Initialize ArXiv (Always available)
        self.providers[ProviderType.ARXIV] = ArxivProvider()

        # Initialize Semantic Scholar (Only if key provided)
        if api_key:
            self.providers[ProviderType.SEMANTIC_SCHOLAR] = SemanticScholarProvider(
                api_key=api_key
            )
        else:
            logger.info("semantic_scholar_disabled", reason="no_api_key")

    async def search(self, topic: ResearchTopic) -> List[PaperMetadata]:
        """Search for papers using the configured provider for the topic"""

        provider_type = topic.provider

        if provider_type not in self.providers:
            if provider_type == ProviderType.SEMANTIC_SCHOLAR:
                logger.error(
                    "provider_unavailable",
                    provider=provider_type,
                    reason="missing_api_key",
                )
                raise APIError(
                    f"Provider {provider_type} is configured but not "
                    "available (missing API key). Check .env file."
                )
            else:
                raise ValueError(f"Unknown provider type: {provider_type}")

        provider = self.providers[provider_type]
        return await provider.search(topic)
