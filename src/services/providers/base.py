from abc import ABC, abstractmethod
from typing import List
from src.models.config import ResearchTopic
from src.models.paper import PaperMetadata

class APIError(Exception):
    """External API error"""
    pass

class RateLimitError(APIError):
    """Rate limit exceeded"""
    pass

class DiscoveryProvider(ABC):
    """Abstract base class for research paper discovery providers"""

    @abstractmethod
    async def search(self, topic: ResearchTopic) -> List[PaperMetadata]:
        """Search for papers matching the given topic"""
        pass