# MCP Web Search Plugin

Privacy-respecting web search plugin for DeepSeek Harness using SearXNG and DuckDuckGo.

## Features

- **Multiple Backends**: SearXNG (metasearch) and DuckDuckGo HTML scraping
- **Privacy-First**: No tracking, no API keys required for public instances
- **MCP Compatible**: Runs as an MCP server for DeepSeek Harness integration
- **Async/Await**: Full async support with proper timeout handling
- **Structured Output**: JSON, Markdown, and dict formats
- **Fallback Support**: Automatically tries multiple SearXNG instances
- **Configurable**: Safe search, categories, language, time range, result limits

## Installation

```bash
pip install -e .
```

Or install dependencies directly:
```bash
pip install mcp httpx beautifulsoup4 lxml pydantic python-dotenv
```

## Quick Start

### As a Python Module

```python
import asyncio
from search_plugin import WebSearchPlugin, SearchConfig, SearchBackend

async def main():
    config = SearchConfig(
        backend=SearchBackend.SEARXNG,
        max_results=10,
    )
    
    async with WebSearchPlugin(config) as plugin:
        # Get Markdown output (default)
        results = await plugin.search("Python async programming")
        print(results)
        
        # Get JSON output
        results_json = await plugin.search("Python async programming", output_format="json")
        print(results_json)
        
        # Get dict object
        results_dict = await plugin.search("Python async programming", output_format="dict")
        print(results_dict["results"])

asyncio.run(main())
```

### As CLI Tool

```bash
# Basic search
python -m search_plugin "Python async programming"

# With options
python -m search_plugin "machine learning" --max-results 5 --backend duckduckgo --format json

# Run as MCP server
python -m search_plugin --mcp
```

### As MCP Server for DeepSeek Harness

Add to your DeepSeek Harness configuration (`cordis.yml` or `settings.yaml`):

```yaml
- id: mcp-web-search
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    transport: stdio
    serverName: web_search
    command: python
    args: ["-m", "search_plugin"]
    cwd: /path/to/mcp-web-search
    env:
      PATH: /usr/local/bin:/usr/bin:/bin
    toolCallTimeoutMs: 60000
    startupTimeoutMs: 15000
    maxInstructionBytes: 32768
    failOnStartupError: false
    reconnect:
      enabled: true
      initialDelayMs: 500
      maxDelayMs: 30000
      maxAttempts: 10
```

Then use the `mcp__web_search__web_search` tool in your agent.

## Configuration

### SearchConfig Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `backend` | `SearchBackend` | `SEARXNG` | Search backend: `searxng` or `duckduckgo` |
| `searxng_instances` | `list[HttpUrl]` | 5 public instances | SearXNG instance URLs |
| `max_results` | `int` | `10` | Max results per search (1-50) |
| `timeout_seconds` | `float` | `30.0` | Request timeout (1-120s) |
| `safe_search` | `SafeSearchLevel` | `MODERATE` | 0=none, 1=moderate, 2=strict |
| `categories` | `str` | `general` | Search categories (comma-separated) |
| `language` | `str` | `auto` | Language code or `auto` |
| `time_range` | `str` | `None` | `day`, `week`, `month`, `year` |
| `user_agent` | `str` | `deepseek-harness/1.0.0` | Custom User-Agent |
| `max_retries` | `int` | `3` | Max retry attempts |
| `retry_delay_seconds` | `float` | `1.0` | Delay between retries |

### Environment Variables

```bash
# Override SearXNG instances (comma-separated)
export SEARXNG_INSTANCES="https://my-searxng.example.com,https://backup.example.com"

# Custom timeout
export SEARCH_TIMEOUT=60

# Default max results
export SEARCH_MAX_RESULTS=20
```

## SearXNG Instances

The plugin uses these public SearXNG instances by default:
- https://searx.be
- https://search.bus-hit.me
- https://searx.tiekoetter.com
- https://searx.thegpm.org
- https://search.projectsegfau.lt

You can host your own SearXNG instance for better reliability:
```bash
docker run -d -p 8080:8080 searxng/searxng
```

Then configure:
```python
config = SearchConfig(searxng_instances=["http://localhost:8080"])
```

## Output Formats

### Markdown (Default)
Human-readable format with clickable links:
```markdown
# Search Results for: `Python async`
**Backend:** searxng  |  **Results:** 3  |  **Time:** 245ms

1. **[asyncio — Python 3.12 documentation](https://docs.python.org/3/library/asyncio.html)**
   The asyncio module provides infrastructure for writing single-threaded concurrent code...
   *Source: google*
```

### JSON
Structured data for programmatic use:
```json
{
  "query": "Python async",
  "results": [
    {
      "url": "https://docs.python.org/3/library/asyncio.html",
      "title": "asyncio — Python 3.12 documentation",
      "snippet": "The asyncio module provides...",
      "source_engine": "google",
      "position": 1,
      "score": 0.95
    }
  ],
  "truncated": false,
  "total_results": 42,
  "search_time_ms": 245.3,
  "backend_used": "searxng"
}
```

## Error Handling

The plugin handles various error conditions gracefully:
- Network timeouts and connection errors
- HTTP errors (rate limiting, server errors)
- Invalid responses
- All instances failing (returns error in response)

Errors are included in the response object:
```python
response = await plugin.search("query")
if response.error:
    print(f"Search warning: {response.error}")
```

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=search_plugin --cov-report=html
```

## License

MIT License - see LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## Related Projects

- [DeepSeek Harness](https://github.com/deepseek-ai/dsh)
- [SearXNG](https://github.com/searxng/searxng)
- [Model Context Protocol](https://modelcontextprotocol.io/)