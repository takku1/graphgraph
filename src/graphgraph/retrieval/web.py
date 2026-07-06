from __future__ import annotations

import re
import urllib.parse
import urllib.request
from typing import TypedDict


class WebSearchResult(TypedDict):
    title: str
    url: str
    snippet: str


def search_web(query: str, limit: int = 3) -> list[WebSearchResult]:
    """Execute an anonymous web search using DuckDuckGo Lite and parse the top organic results.
    
    Degrades gracefully to an empty list on network or parse failures.
    """
    try:
        encoded_query = urllib.parse.urlencode({"q": query})
        url = f"https://lite.duckduckgo.com/lite/"
        data = encoded_query.encode("utf-8")
        
        # DuckDuckGo Lite requires a browser-like User-Agent to prevent bot blockages
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=8) as response:
            html = response.read().decode("utf-8", errors="ignore")
            
        return parse_duckduckgo_lite(html, limit=limit)
    except Exception:
        return []


def parse_duckduckgo_lite(html: str, limit: int = 3) -> list[WebSearchResult]:
    results: list[WebSearchResult] = []
    
    # DuckDuckGo Lite results are structured in tables:
    # <tr><td class="result-link"><a href="...">Title</a></td></tr>
    # <tr><td class="result-snippet">Snippet text...</td></tr>
    
    # We locate all links with class="result-link" or similar.
    # A robust way is to split by <tr> or find matches via regex.
    # Let's extract td blocks.
    td_pattern = re.compile(
        r'<td[^>]*class="result-link"[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?</td>',
        re.DOTALL | re.IGNORECASE
    )
    
    # Snippet pattern comes in subsequent td or tr
    # We will search matching table rows.
    rows = html.split("<tr")
    current_link = None
    current_title = None
    
    for row in rows:
        # Check if this row contains the link
        link_match = td_pattern.search(row)
        if link_match:
            raw_url = link_match.group(1)
            # Parse redirect URL: DuckDuckGo uses proxy links like /l/?kh=-1&uddg=https%3A%2F%2F...
            url = raw_url
            if "/l/?uddg=" in raw_url:
                parsed_url = urllib.parse.urlparse(raw_url)
                query_params = urllib.parse.parse_qs(parsed_url.query)
                if "uddg" in query_params:
                    url = query_params["uddg"][0]
                    
            title = re.sub(r"<[^>]+>", "", link_match.group(2)).strip()
            current_link = url
            current_title = title
            continue
            
        # If we have a current link, check if this row has the snippet
        if current_link and 'class="result-snippet"' in row:
            snippet_match = re.search(r'<td[^>]*class="result-snippet"[^>]*>(.*?)</td>', row, re.DOTALL | re.IGNORECASE)
            if snippet_match:
                snippet = re.sub(r"<[^>]+>", "", snippet_match.group(1)).strip()
                # Clean up multiple whitespaces
                snippet = re.sub(r"\s+", " ", snippet)
                
                results.append({
                    "title": current_title or "Search Result",
                    "url": current_link,
                    "snippet": snippet
                })
                current_link = None
                current_title = None
                if len(results) >= limit:
                    break
                    
    return results
