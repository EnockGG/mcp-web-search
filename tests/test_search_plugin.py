#!/usr/bin/env python3
"""
Unit tests for the Web Search Plugin.

Run with: pytest tests/ -v
"""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from search_plugin import (
    SearchBackend,
    SafeSearchLevel,
    SearchConfig,
    SearchResult,
    SearchResponse,
    SearXNGBackend,
    DuckDuckGoBackend,
    WebSearchPlugin,
    validate_url,
)


class TestSearchConfig:
    """Tests for SearchConfig validation."""
    
    def test_default_config(self):
        config = SearchConfig()
        assert config.backend == SearchBackend.SEARXNG
        assert config.max_results == 10
        assert config.timeout_seconds == 30.0
        assert config.safe_search == SafeSearchLevel.MODERATE
        assert len(config.searxng_instances) == 5
    
    def test_custom_config(self):
        config = SearchConfig(
            backend=SearchBackend.DUCKDUCKGO,
            max_results=5,
            timeout_seconds=15.0,
            safe_search=SafeSearchLevel.STRICT,
        )
        assert config.backend == SearchBackend.DUCKDUCKGO
        assert config.max_results == 5
        assert config.timeout_seconds == 15.0
        assert config.safe_search == SafeSearchLevel.STRICT
    
    def test_invalid_max_results(self):
        with pytest.raises(Exception):
            SearchConfig(max_results=0)
        with pytest.raises(Exception):
            SearchConfig(max_results=51)
    
    def test_invalid_timeout(self):
        with pytest.raises(Exception):
            SearchConfig(timeout_seconds=0)
        with pytest.raises(Exception):
            SearchConfig(timeout_seconds=121)
    
    def test_invalid_safe_search(self):
        with pytest.raises(Exception):
            SearchConfig(safe_search=3)
    
    def test_parse_instances_from_string(self):
        config = SearchConfig(searxng_instances="https://a.com, https://b.com ,https://c.com")
        assert len(config.searxng_instances) == 3
        assert str(config.searxng_instances[0]) == "https://a.com/"
        assert str(config.searxng_instances[1]) == "https://b.com/"
        assert str(config.searxng_instances[2]) == "https://c.com/"
    
    def test_parse_instances_filters_empty(self):
        config = SearchConfig(searxng_instances="https://a.com,,https://b.com,")
        assert len(config.searxng_instances) == 2


class TestSearchResult:
    """Tests for SearchResult dataclass."""
    
    def test_to_dict(self):
        result = SearchResult(
            url="https://example.com",
            title="Test Title",
            snippet="Test snippet",
            source_engine="google",
            position=1,
            score=0.95,
        )
        d = result.to_dict()
        assert d["url"] == "https://example.com"
        assert d["title"] == "Test Title"
        assert d["snippet"] == "Test snippet"
        assert d["source_engine"] == "google"
        assert d["position"] == 1
        assert d["score"] == 0.95
    
    def test_to_dict_omits_none(self):
        result = SearchResult(url="https://example.com")
        d = result.to_dict()
        assert "title" not in d
        assert "snippet" not in d
        assert "source_engine" not in d
        assert d["url"] == "https://example.com"
    
    def test_to_markdown(self):
        result = SearchResult(
            url="https://example.com",
            title="Test Title",
            snippet="Test snippet",
            source_engine="google",
        )
        md = result.to_markdown(0)
        assert "1. **[Test Title](https://example.com)**" in md
        assert "Test snippet" in md
        assert "*Source: google*" in md


class TestSearchResponse:
    """Tests for SearchResponse dataclass."""
    
    def test_to_dict(self):
        results = [
            SearchResult(url="https://a.com", title="A"),
            SearchResult(url="https://b.com", title="B"),
        ]
        response = SearchResponse(
            query="test",
            results=results,
            total_results=100,
            search_time_ms=150.5,
            backend_used=SearchBackend.SEARXNG,
        )
        d = response.to_dict()
        assert d["query"] == "test"
        assert len(d["results"]) == 2
        assert d["total_results"] == 100
        assert d["search_time_ms"] == 150.5
        assert d["backend_used"] == "searxng"
    
    def test_to_json(self):
        response = SearchResponse(query="test", results=[])
        json_str = response.to_json()
        data = json.loads(json_str)
        assert data["query"] == "test"
    
    def test_to_markdown(self):
        results = [
            SearchResult(url="https://a.com", title="A", snippet="Snippet A"),
            SearchResult(url="https://b.com", title="B", snippet="Snippet B"),
        ]
        response = SearchResponse(
            query="test query",
            results=results,
            search_time_ms=100.0,
        )
        md = response.to_markdown()
        assert "# Search Results for: `test query`" in md
        assert "Backend: searxng" in md
        assert "Results: 2" in md
        assert "Time: 100ms" in md
        assert "**[A](https://a.com)**" in md
        assert "Snippet A" in md
        assert "**[B](https://b.com)**" in md
        assert "Snippet B" in md
    
    def test_to_markdown_with_error(self):
        response = SearchResponse(
            query="test",
            results=[],
            error="Something went wrong",
        )
        md = response.to_markdown()
        assert "⚠️ **Warning:** Something went wrong" in md
    
    def test_to_markdown_empty_results(self):
        response = SearchResponse(query="test", results=[])
        md = response.to_markdown()
        assert "*No results found.*" in md
    
    def test_to_markdown_truncated(self):
        results = [SearchResult(url=f"https://{i}.com") for i in range(10)]
        response = SearchResponse(
            query="test",
            results=results,
            total_results=100,
            truncated=True,
        )
        md = response.to_markdown()
        assert "Results truncated to 10 items (total: 100)" in md


class TestSearXNGBackend:
    """Tests for SearXNGBackend."""
    
    def test_backend_type(self):
        config = SearchConfig()
        backend = SearXNGBackend(config)
        assert backend.backend_type == SearchBackend.SEARXNG
    
    def test_build_search_url(self):
        config = SearchConfig(
            categories="news,images",
            language="fr",
            safe_search=SafeSearchLevel.STRICT,
            time_range="week",
        )
        backend = SearXNGBackend(config)
        url = backend._build_search_url("https://searx.be", "test query", 10)
        
        assert "q=test+query" in url
        assert "format=json" in url
        assert "categories=news%2Cimages" in url
        assert "language=fr" in url
        assert "safesearch=2" in url
        assert "time_range=week" in url
    
    def test_parse_searxng_results(self):
        config = SearchConfig()
        backend = SearXNGBackend(config)
        
        mock_data = {
            "number_of_results": 2,
            "results": [
                {
                    "url": "https://example.com/1",
                    "title": "Result 1",
                    "content": "Snippet 1",
                    "engine": "google",
                    "score": 0.9,
                },
                {
                    "url": "https://example.com/2",
                    "title": "Result 2",
                    "content": "Snippet 2",
                    "engine": "bing",
                    "score": 0.8,
                },
            ],
        }
        
        results = backend._parse_searxng_results(mock_data, 10)
        assert len(results) == 2
        assert results[0].url == "https://example.com/1"
        assert results[0].title == "Result 1"
        assert results[0].snippet == "Snippet 1"
        assert results[0].source_engine == "google"
        assert results[0].position == 1
        assert results[0].score == 0.9
        assert results[1].url == "https://example.com/2"
        assert results[1].source_engine == "bing"


class TestDuckDuckGoBackend:
    """Tests for DuckDuckGoBackend."""
    
    def test_backend_type(self):
        config = SearchConfig()
        backend = DuckDuckGoBackend(config)
        assert backend.backend_type == SearchBackend.DUCKDUCKGO
    
    def test_build_search_url(self):
        config = SearchConfig(
            language="fr",
            safe_search=SafeSearchLevel.STRICT,
            time_range="month",
        )
        backend = DuckDuckGoBackend(config)
        url = backend._build_search_url("test query", 10)
        
        assert "q=test+query" in url
        assert "kl=fr" in url
        assert "kp=2" in url
        assert "df=month" in url
    
    def test_build_search_url_auto_language(self):
        config = SearchConfig(language="auto")
        backend = DuckDuckGoBackend(config)
        url = backend._build_search_url("test", 10)
        # auto language should not add kl parameter
        assert "kl=" not in url or "kl=us-en" in url


class TestWebSearchPlugin:
    """Tests for WebSearchPlugin main class."""
    
    def test_init_default_config(self):
        plugin = WebSearchPlugin()
        assert plugin.config.backend == SearchBackend.SEARXNG
        assert plugin._backend is not None
        assert isinstance(plugin._backend, SearXNGBackend)
    
    def test_init_custom_config(self):
        config = SearchConfig(backend=SearchBackend.DUCKDUCKGO)
        plugin = WebSearchPlugin(config)
        assert plugin.config.backend == SearchBackend.DUCKDUCKGO
        assert isinstance(plugin._backend, DuckDuckGoBackend)
    
    def test_search_sync_returns_response(self):
        plugin = WebSearchPlugin(SearchConfig(backend=SearchBackend.DUCKDUCKGO))
        
        # Mock the backend search method
        mock_response = SearchResponse(
            query="test",
            results=[SearchResult(url="https://example.com", title="Test")],
            search_time_ms=100,
        )
        plugin._backend.search = AsyncMock(return_value=mock_response)
        
        result = plugin.search_sync("test query", output_format="dict")
        assert isinstance(result, SearchResponse)
        assert result.query == "test"
    
    @pytest.mark.asyncio
    async def test_search_async_markdown(self):
        plugin = WebSearchPlugin(SearchConfig(backend=SearchBackend.DUCKDUCKGO))
        
        mock_response = SearchResponse(
            query="test",
            results=[SearchResult(url="https://example.com", title="Test", snippet="Snippet")],
            search_time_ms=100,
        )
        plugin._backend.search = AsyncMock(return_value=mock_response)
        
        async with plugin:
            result = await plugin.search("test query", output_format="markdown")
        
        assert isinstance(result, str)
        assert "Test" in result
        assert "Snippet" in result
    
    @pytest.mark.asyncio
    async def test_search_async_json(self):
        plugin = WebSearchPlugin(SearchConfig(backend=SearchBackend.DUCKDUCKGO))
        
        mock_response = SearchResponse(
            query="test",
            results=[SearchResult(url="https://example.com", title="Test")],
            search_time_ms=100,
        )
        plugin._backend.search = AsyncMock(return_value=mock_response)
        
        async with plugin:
            result = await plugin.search("test query", output_format="json")
        
        assert isinstance(result, str)
        data = json.loads(result)
        assert data["query"] == "test"


class TestURLValidation:
    """Tests for URL validation utilities."""
    
    def test_valid_https_url(self):
        url = validate_url("https://example.com")
        assert str(url) == "https://example.com/"
    
    def test_valid_http_url(self):
        url = validate_url("http://localhost:8080")
        assert str(url) == "http://localhost:8080/"
    
    def test_invalid_url(self):
        with pytest.raises(Exception):
            validate_url("not-a-url")
    
    def test_invalid_scheme(self):
        with pytest.raises(Exception):
            validate_url("ftp://example.com")


class TestIntegrationMocked:
    """Integration-style tests with mocked HTTP responses."""
    
    @pytest.mark.asyncio
    async def test_searxng_success_flow(self):
        config = SearchConfig(
            backend=SearchBackend.SEARXNG,
            searxng_instances=["https://test.searxng.org"],
        )
        
        mock_response_data = {
            "query": "python async",
            "number_of_results": 42,
            "results": [
                {
                    "url": "https://docs.python.org/3/library/asyncio.html",
                    "title": "asyncio — Asynchronous I/O — Python 3.12 documentation",
                    "content": "The asyncio module provides infrastructure for writing single-threaded concurrent code...",
                    "engine": "google",
                    "score": 0.95,
                },
            ],
            "suggestions": [],
            "corrections": [],
            "infoboxes": [],
            "engines": ["google"],
            "categories": ["general"],
        }
        
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response
            
            plugin = WebSearchPlugin(config)
            async with plugin:
                result = await plugin.search("python async", output_format="dict")
            
            assert result["query"] == "python async"
            assert len(result["results"]) == 1
            assert result["results"][0]["title"] == "asyncio — Asynchronous I/O — Python 3.12 documentation"
            assert result["results"][0]["url"] == "https://docs.python.org/3/library/asyncio.html"
            assert result["total_results"] == 42
            assert result["backend_used"] == "searxng"
    
    @pytest.mark.asyncio
    async def test_searxng_fallback_to_next_instance(self):
        config = SearchConfig(
            backend=SearchBackend.SEARXNG,
            searxng_instances=["https://fail1.searxng.org", "https://success.searxng.org"],
        )
        
        mock_success_data = {
            "query": "test",
            "number_of_results": 1,
            "results": [{"url": "https://example.com", "title": "Success", "content": "OK", "engine": "bing", "score": 0.8}],
            "suggestions": [], "corrections": [], "infoboxes": [], "engines": [], "categories": [],
        }
        
        with patch("httpx.AsyncClient.get") as mock_get:
            # First call fails, second succeeds
            mock_fail = MagicMock()
            mock_fail.raise_for_status.side_effect = Exception("Connection failed")
            
            mock_success = MagicMock()
            mock_success.json.return_value = mock_success_data
            mock_success.raise_for_status = MagicMock()
            
            mock_get.side_effect = [mock_fail, mock_success]
            
            plugin = WebSearchPlugin(config)
            async with plugin:
                result = await plugin.search("test", output_format="dict")
            
            assert result["results"][0]["title"] == "Success"
            assert mock_get.call_count == 2
    
    @pytest.mark.asyncio
    async def test_duckduckgo_html_parsing(self):
        config = SearchConfig(backend=SearchBackend.DUCKDUCKGO)
        
        # Sample DuckDuckGo HTML
        mock_html = """
        <html>
            <body>
                <div class="result">
                    <a class="result__title" href="https://example.com/page1">Page 1 Title</a>
                    <a class="result__snippet" href="https://example.com/page1">Page 1 snippet content</a>
                </div>
                <div class="result">
                    <a class="result__title" href="https://example.com/page2">Page 2 Title</a>
                    <a class="result__snippet" href="https://example.com/page2">Page 2 snippet content</a>
                </div>
            </body>
        </html>
        """
        
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_response = MagicMock()
            mock_response.text = mock_html
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response
            
            plugin = WebSearchPlugin(config)
            async with plugin:
                result = await plugin.search("test", output_format="dict")
            
            assert len(result["results"]) == 2
            assert result["results"][0]["title"] == "Page 1 Title"
            assert result["results"][0]["snippet"] == "Page 1 snippet content"
            assert result["results"][1]["title"] == "Page 2 Title"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])