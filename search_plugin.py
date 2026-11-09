#!/usr/bin/env python3
"""
Privacy-Respecting Web Search Plugin for DeepSeek Harness

This module provides a web search capability using SearXNG (metasearch engine)
or DuckDuckGo HTML scraping as a fallback. It can be used as:
1. A standalone Python module
2. An MCP (Model Context Protocol) server for DeepSeek Harness
3. A direct tool for AI agents

Features:
- Multiple backend support (SearXNG, DuckDuckGo HTML)
- Privacy-focused: no tracking, no API keys required for public instances
- Async HTTP requests with proper timeout handling
- Structured JSON and Markdown output formats
- Comprehensive error handling
- Configurable result limits and safe search

License: MIT
Author: DeepSeek Harness Community
"""

import asyncio
import json
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
from urllib.parse import quote_plus, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, HttpUrl, field_validator


# ============================================================================
# Data Models
# ============================================================================

class SearchBackend(str, Enum):
    """Supported search backends."""
    SEARXNG = "searxng"
    DUCKDUCKGO = "duckduckgo"


class SafeSearchLevel(int, Enum):
    """Safe search filtering levels."""
    NONE = 0
    MODERATE = 1
    STRICT = 2


@dataclass
class SearchResult:
    """A single search result."""
    url: str
    title: Optional[str] = None
    snippet: Optional[str] = None
    summary: Optional[str] = None
    published_at: Optional[str] = None
    source_engine: Optional[str] = None
    position: int = 0
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, omitting None values."""
        return {k: v for k, v in {
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "summary": self.summary,
            "published_at": self.published_at,
            "source_engine": self.source_engine,
            "position": self.position,
            "score": self.score,
        }.items() if v is not None}

    def to_markdown(self, index: int = 0) -> str:
        """Format as Markdown for easy reading."""
        parts = [f"{index + 1}. **[{self.title or self.url}]({self.url})**"]
        if self.snippet:
            parts.append(f"   {self.snippet}")
        if self.source_engine:
            parts.append(f"   *Source: {self.source_engine}*")
        return "\n".join(parts)


@dataclass
class SearchResponse:
    """Complete search response."""
    query: str
    results: list[SearchResult] = field(default_factory=list)
    truncated: bool = False
    total_results: int = 0
    search_time_ms: float = 0.0
    backend_used: SearchBackend = SearchBackend.SEARXNG
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "query": self.query,
            "results": [r.to_dict() for r in self.results],
            "truncated": self.truncated,
            "total_results": self.total_results,
            "search_time_ms": round(self.search_time_ms, 2),
            "backend_used": self.backend_used.value,
            "error": self.error,
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_markdown(self) -> str:
        """Format as Markdown."""
        lines = [
            f"# Search Results for: `{self.query}`",
            f"**Backend:** {self.backend_used.value}  |  **Results:** {len(self.results)}  |  **Time:** {self.search_time_ms:.0f}ms",
            "",
        ]
        
        if self.error:
            lines.append(f"> ⚠️ **Warning:** {self.error}")
            lines.append("")
        
        if not self.results:
            lines.append("*No results found.*")
        else:
            for i, result in enumerate(self.results):
                lines.append(result.to_markdown(i))
                lines.append("")
        
        if self.truncated:
            lines.append(f"*Results truncated to {len(self.results)} items (total: {self.total_results})*")
        
        return "\n".join(lines)


class SearchConfig(BaseModel):
    """Configuration for search plugin."""
    # Backend settings
    backend: SearchBackend = SearchBackend.SEARXNG
    searxng_instances: list[HttpUrl] = Field(
        default_factory=lambda: [
            "https://searx.be",
            "https://search.bus-hit.me",
            "https://searx.tiekoetter.com",
            "https://searx.thegpm.org",
            "https://search.projectsegfau.lt",
        ]
    )
    
    # Search parameters
    max_results: int = Field(default=10, ge=1, le=50)
    timeout_seconds: float = Field(default=30.0, ge=1.0, le=120.0)
    safe_search: SafeSearchLevel = SafeSearchLevel.MODERATE
    categories: str = "general"
    language: str = "auto"
    time_range: Optional[str] = Field(default=None, pattern="^(day|week|month|year)?$")
    
    # HTTP settings
    user_agent: str = "deepseek-harness/1.0.0 (+https://github.com/deepseek-ai/mcp-web-search)"
    follow_redirects: bool = True
    max_redirects: int = 5
    
    # Retry settings
    max_retries: int = 3
    retry_delay_seconds: float = 1.0
    
    @field_validator("searxng_instances", mode="before")
    @classmethod
    def parse_instances(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v


# ============================================================================
# Search Backend Interface
# ============================================================================

class SearchBackendBase(ABC):
    """Abstract base class for search backends."""
    
    def __init__(self, config: SearchConfig):
        self.config = config
        self.client: Optional[httpx.AsyncClient] = None
    
    async def __aenter__(self):
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.timeout_seconds),
            follow_redirects=self.config.follow_redirects,
            max_redirects=self.config.max_redirects,
            headers={"User-Agent": self.config.user_agent},
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()
    
    @abstractmethod
    async def search(self, query: str, max_results: Optional[int] = None) -> SearchResponse:
        """Perform a search and return results."""
        pass
    
    @property
    @abstractmethod
    def backend_type(self) -> SearchBackend:
        """Return the backend type identifier."""
        pass
    
    def _create_response(
        self,
        query: str,
        results: list[SearchResult],
        total_results: int,
        search_time_ms: float,
        truncated: bool = False,
        error: Optional[str] = None,
    ) -> SearchResponse:
        """Create a standardized search response."""
        return SearchResponse(
            query=query,
            results=results[:self.config.max_results],
            truncated=truncated or len(results) > self.config.max_results,
            total_results=total_results,
            search_time_ms=search_time_ms,
            backend_used=self.backend_type,
            error=error,
        )


class SearXNGBackend(SearchBackendBase):
    """SearXNG metasearch engine backend."""
    
    def __init__(self, config: SearchConfig):
        super().__init__(config)
        self.instances = [str(url) for url in config.searxng_instances]
        self.current_instance_index = 0
    
    @property
    def backend_type(self) -> SearchBackend:
        return SearchBackend.SEARXNG
    
    def _build_search_url(self, instance: str, query: str, max_results: int) -> str:
        """Build SearXNG search URL with parameters."""
        params = {
            "q": query,
            "format": "json",
            "categories": self.config.categories,
            "language": self.config.language,
            "safesearch": str(self.config.safe_search.value),
        }
        if self.config.time_range:
            params["time_range"] = self.config.time_range
        
        param_str = "&".join(f"{k}={quote_plus(str(v))}" for k, v in params.items())
        return f"{instance.rstrip('/')}/search?{param_str}"
    
    async def search(self, query: str, max_results: Optional[int] = None) -> SearchResponse:
        start_time = time.perf_counter()
        max_results = max_results or self.config.max_results
        last_error: Optional[Exception] = None
        
        # Try each instance until one succeeds
        for attempt in range(len(self.instances)):
            instance = self.instances[self.current_instance_index]
            self.current_instance_index = (self.current_instance_index + 1) % len(self.instances)
            
            try:
                if not self.client:
                    raise RuntimeError("Client not initialized. Use async context manager.")
                
                url = self._build_search_url(instance, query, max_results)
                response = await self.client.get(url)
                response.raise_for_status()
                
                data = response.json()
                results = self._parse_searxng_results(data, max_results)
                
                search_time_ms = (time.perf_counter() - start_time) * 1000
                return self._create_response(
                    query=query,
                    results=results,
                    total_results=data.get("number_of_results", len(results)),
                    search_time_ms=search_time_ms,
                )
                
            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code == 429:
                    # Rate limited, try next instance
                    await asyncio.sleep(self.config.retry_delay_seconds)
                    continue
                elif e.response.status_code >= 500:
                    # Server error, try next instance
                    continue
                else:
                    # Client error, don't retry
                    break
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_error = e
                # Network error, try next instance
                continue
            except Exception as e:
                last_error = e
                # Unexpected error, try next instance
                continue
        
        # All instances failed
        search_time_ms = (time.perf_counter() - start_time) * 1000
        error_msg = f"All SearXNG instances failed. Last error: {last_error}"
        return self._create_response(
            query=query,
            results=[],
            total_results=0,
            search_time_ms=search_time_ms,
            error=error_msg,
        )
    
    def _parse_searxng_results(self, data: dict, max_results: int) -> list[SearchResult]:
        """Parse SearXNG JSON response into SearchResult objects."""
        results = []
        for i, item in enumerate(data.get("results", [])[:max_results]):
            results.append(SearchResult(
                url=item.get("url", ""),
                title=item.get("title") or None,
                snippet=item.get("content") or None,
                source_engine=item.get("engine"),
                position=i + 1,
                score=item.get("score", 0.0),
            ))
        return results


class DuckDuckGoBackend(SearchBackendBase):
    """DuckDuckGo HTML scraping backend (fallback)."""
    
    @property
    def backend_type(self) -> SearchBackend:
        return SearchBackend.DUCKDUCKGO
    
    def _build_search_url(self, query: str, max_results: int) -> str:
        """Build DuckDuckGo HTML search URL."""
        params = {
            "q": query,
            "kl": self.config.language if self.config.language != "auto" else "us-en",
            "kp": str(self.config.safe_search.value),  # Safe search
            "df": self.config.time_range or "",  # Time range
        }
        param_str = "&".join(f"{k}={quote_plus(str(v))}" for k, v in params.items() if v)
        return f"https://html.duckduckgo.com/html/?{param_str}"
    
    async def search(self, query: str, max_results: Optional[int] = None) -> SearchResponse:
        start_time = time.perf_counter()
        max_results = max_results or self.config.max_results
        
        try:
            if not self.client:
                raise RuntimeError("Client not initialized. Use async context manager.")
            
            url = self._build_search_url(query, max_results)
            response = await self.client.get(url)
            response.raise_for_status()
            
            results = self._parse_duckduckgo_html(response.text, max_results)
            
            search_time_ms = (time.perf_counter() - start_time) * 1000
            return self._create_response(
                query=query,
                results=results,
                total_results=len(results),
                search_time_ms=search_time_ms,
            )
            
        except Exception as e:
            search_time_ms = (time.perf_counter() - start_time) * 1000
            return self._create_response(
                query=query,
                results=[],
                total_results=0,
                search_time_ms=search_time_ms,
                error=f"DuckDuckGo search failed: {e}",
            )
    
    def _parse_duckduckgo_html(self, html: str, max_results: int) -> list[SearchResult]:
        """Parse DuckDuckGo HTML response."""
        soup = BeautifulSoup(html, "lxml")
        results = []
        
        # Find result containers
        result_divs = soup.select("div.result__snippet")
        if not result_divs:
            # Try alternative selectors
            result_divs = soup.select("div.web-result-description")
        if not result_divs:
            result_divs = soup.select("a.result__snippet")
        
        for i, div in enumerate(result_divs[:max_results]):
            # Find the parent result container
            container = div.find_parent("div", class_=re.compile(r"result"))
            if not container:
                container = div.find_parent("div", class_=re.compile(r"web-result"))
            
            # Extract URL
            url = ""
            link = container.find("a", class_=re.compile(r"result__url")) if container else None
            if not link:
                link = container.find("a", href=True) if container else None
            if link and link.get("href"):
                url = link["href"]
                # Clean DuckDuckGo redirect URLs
                if url.startswith("//duckduckgo.com/l/?uddg="):
                    from urllib.parse import unquote, parse_qs, urlparse
                    parsed = urlparse(url)
                    params = parse_qs(parsed.query)
                    if "uddg" in params:
                        url = unquote(params["uddg"][0])
            
            # Extract title
            title_elem = container.find("a", class_=re.compile(r"result__title")) if container else None
            if not title_elem:
                title_elem = container.find("h2") if container else None
            title = title_elem.get_text(strip=True) if title_elem else None
            
            # Extract snippet
            snippet = div.get_text(strip=True) if div else None
            
            if url:
                results.append(SearchResult(
                    url=url,
                    title=title,
                    snippet=snippet,
                    source_engine="duckduckgo",
                    position=i + 1,
                ))
        
        return results


# ============================================================================
# Main Search Plugin Class
# ============================================================================

class WebSearchPlugin:
    """
    Main web search plugin for DeepSeek Harness.
    
    This class provides a unified interface for web searching using
    privacy-respecting backends (SearXNG, DuckDuckGo).
    
    Usage:
        plugin = WebSearchPlugin()
        async with plugin:
            results = await plugin.search("Python async programming")
            print(results.to_markdown())
    """
    
    def __init__(self, config: Optional[SearchConfig] = None):
        self.config = config or SearchConfig()
        self._backend: Optional[SearchBackendBase] = None
        self._initialize_backend()
    
    def _initialize_backend(self):
        """Initialize the appropriate search backend."""
        if self.config.backend == SearchBackend.SEARXNG:
            self._backend = SearXNGBackend(self.config)
        elif self.config.backend == SearchBackend.DUCKDUCKGO:
            self._backend = DuckDuckGoBackend(self.config)
        else:
            raise ValueError(f"Unknown backend: {self.config.backend}")
    
    async def __aenter__(self):
        if self._backend:
            await self._backend.__aenter__()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._backend:
            await self._backend.__aexit__(exc_type, exc_val, exc_tb)
    
    async def search(
        self,
        query: str,
        max_results: Optional[int] = None,
        output_format: str = "markdown",
    ) -> str | SearchResponse:
        """
        Perform a web search.
        
        Args:
            query: Search query string
            max_results: Maximum number of results (overrides config)
            output_format: "json", "markdown", or "dict" (returns SearchResponse object)
        
        Returns:
            Formatted search results or SearchResponse object
        """
        if not self._backend:
            raise RuntimeError("Backend not initialized. Use async context manager.")
        
        response = await self._backend.search(query, max_results)
        
        if output_format == "json":
            return response.to_json()
        elif output_format == "markdown":
            return response.to_markdown()
        elif output_format == "dict":
            return response.to_dict()
        else:
            return response
    
    def search_sync(
        self,
        query: str,
        max_results: Optional[int] = None,
        output_format: str = "markdown",
    ) -> str | SearchResponse:
        """
        Synchronous wrapper for search (runs async in event loop).
        
        Note: This creates a new event loop each call. For multiple searches,
        use the async version directly.
        """
        return asyncio.run(self.search(query, max_results, output_format))


# ============================================================================
# MCP Server Integration
# ============================================================================

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    HAS_MCP = True
except ImportError:
    HAS_MCP = False
    Server = None
    stdio_server = None
    Tool = None
    TextContent = None


def create_mcp_server(config: Optional[SearchConfig] = None) -> "Server":
    """
    Create an MCP server with web search tools.
    
    This server can be connected to DeepSeek Harness via the MCP client.
    
    Configuration for DeepSeek Harness (cordis.yml or settings.yaml):
    ```yaml
    - id: mcp-web-search
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        transport: stdio
        serverName: web_search
        command: python
        args: ["-m", "mcp_web_search.search_server"]
        cwd: /path/to/mcp-web-search
        env:
          PATH: /usr/local/bin:/usr/bin:/bin
        toolCallTimeoutMs: 60000
        startupTimeoutMs: 15000
        reconnect:
          enabled: true
          initialDelayMs: 500
          maxDelayMs: 30000
          maxAttempts: 10
    ```
    """
    if not HAS_MCP:
        raise ImportError("MCP package not installed. Install with: pip install mcp")
    
    search_config = config or SearchConfig()
    plugin = WebSearchPlugin(search_config)
    
    server = Server("web-search")
    
    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="web_search",
                description="Search the web using privacy-respecting engines (SearXNG/DuckDuckGo)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query string",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of results to return (1-50)",
                            "minimum": 1,
                            "maximum": 50,
                            "default": 10,
                        },
                        "backend": {
                            "type": "string",
                            "description": "Search backend to use",
                            "enum": ["searxng", "duckduckgo"],
                            "default": "searxng",
                        },
                        "output_format": {
                            "type": "string",
                            "description": "Output format for results",
                            "enum": ["markdown", "json"],
                            "default": "markdown",
                        },
                    },
                    "required": ["query"],
                },
            ),
        ]
    
    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name != "web_search":
            raise ValueError(f"Unknown tool: {name}")
        
        query = arguments.get("query", "")
        max_results = arguments.get("max_results", search_config.max_results)
        backend = arguments.get("backend", search_config.backend.value)
        output_format = arguments.get("output_format", "markdown")
        
        # Temporarily override backend if requested
        original_backend = search_config.backend
        if backend != original_backend.value:
            search_config.backend = SearchBackend(backend)
            plugin._initialize_backend()
        
        try:
            async with plugin:
                result = await plugin.search(query, max_results, output_format)
            
            if isinstance(result, SearchResponse):
                text = result.to_markdown() if output_format == "markdown" else result.to_json()
            else:
                text = str(result)
            
            return [TextContent(type="text", text=text)]
        finally:
            # Restore original backend
            search_config.backend = original_backend
            plugin._initialize_backend()
    
    return server


async def run_mcp_server(config: Optional[SearchConfig] = None):
    """Run the MCP server over stdio."""
    if not HAS_MCP:
        raise ImportError("MCP package not installed. Install with: pip install mcp")
    
    server = create_mcp_server(config)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    """CLI entry point for direct usage."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Privacy-respecting web search for DeepSeek Harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "Python async programming"
  %(prog)s "machine learning" --max-results 5 --backend duckduckgo
  %(prog)s "AI news" --format json
        """,
    )
    
    parser.add_argument("query", help="Search query")
    parser.add_argument(
        "-m", "--max-results",
        type=int,
        default=10,
        help="Maximum results (default: 10)"
    )
    parser.add_argument(
        "-b", "--backend",
        choices=["searxng", "duckduckgo"],
        default="searxng",
        help="Search backend (default: searxng)"
    )
    parser.add_argument(
        "-f", "--format",
        choices=["markdown", "json", "dict"],
        default="markdown",
        help="Output format (default: markdown)"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Request timeout in seconds (default: 30)"
    )
    parser.add_argument(
        "--safe-search",
        type=int,
        choices=[0, 1, 2],
        default=1,
        help="Safe search level: 0=none, 1=moderate, 2=strict (default: 1)"
    )
    parser.add_argument(
        "--mcp",
        action="store_true",
        help="Run as MCP server (stdio)"
    )
    
    args = parser.parse_args()
    
    if args.mcp:
        if not HAS_MCP:
            print("Error: MCP package not installed. Install with: pip install mcp", file=sys.stderr)
            sys.exit(1)
        asyncio.run(run_mcp_server())
        return
    
    config = SearchConfig(
        backend=SearchBackend(args.backend),
        max_results=args.max_results,
        timeout_seconds=args.timeout,
        safe_search=SafeSearchLevel(args.safe_search),
    )
    
    plugin = WebSearchPlugin(config)
    result = plugin.search_sync(args.query, args.max_results, args.format)
    
    if isinstance(result, SearchResponse):
        if args.format == "json":
            print(result.to_json())
        elif args.format == "markdown":
            print(result.to_markdown())
        else:
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(result)


if __name__ == "__main__":
    import sys
    main()