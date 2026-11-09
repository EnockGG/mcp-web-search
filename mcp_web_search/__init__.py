"""
MCP Web Search Plugin

Privacy-respecting web search for DeepSeek Harness using SearXNG and DuckDuckGo.
"""

from .search_plugin import (
    SearchBackend,
    SafeSearchLevel,
    SearchConfig,
    SearchResult,
    SearchResponse,
    WebSearchPlugin,
    SearXNGBackend,
    DuckDuckGoBackend,
    create_mcp_server,
    run_mcp_server,
)

__version__ = "1.0.0"
__author__ = "DeepSeek Harness Community"
__license__ = "MIT"

__all__ = [
    "SearchBackend",
    "SafeSearchLevel",
    "SearchConfig",
    "SearchResult",
    "SearchResponse",
    "WebSearchPlugin",
    "SearXNGBackend",
    "DuckDuckGoBackend",
    "create_mcp_server",
    "run_mcp_server",
]