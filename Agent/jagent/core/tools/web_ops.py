import json
import re
import subprocess
import urllib.error
import urllib.request
from urllib.parse import urlparse


DEFAULT_TIMEOUT = 30
SEARCH_API_URL = "https://qianfan.baidubce.com/v2/ai_search/web_search"
MAX_SUMMARY_CHARS = 600
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_CHARSET_ALIASES = {
    "gb2312": "gb18030",
    "gbk": "gb18030",
    "utf8": "utf-8",
}


def _is_supported_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _detect_charset(html_bytes: bytes) -> str | None:
    head = html_bytes[:4096]
    match = re.search(
        rb"<meta[^>]+charset\s*=\s*[\"']?\s*([a-zA-Z0-9_\-]+)",
        head,
        re.IGNORECASE,
    )
    if not match:
        match = re.search(
            rb"<\?xml[^>]+encoding\s*=\s*[\"']([a-zA-Z0-9_\-]+)[\"']",
            head,
            re.IGNORECASE,
        )
    if not match:
        return None
    return match.group(1).decode("ascii", "ignore")


def _decode_html(html_bytes: bytes) -> str:
    detected = _detect_charset(html_bytes)
    encodings = []
    if detected:
        encodings.append(_CHARSET_ALIASES.get(detected.lower(), detected))
    encodings.extend(["utf-8", "gb18030", "latin-1"])

    for encoding in encodings:
        try:
            return html_bytes.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return html_bytes.decode("latin-1", errors="replace")


def _error(url: str, message: str) -> str:
    return json.dumps({"url": url, "error": message}, ensure_ascii=False)


def _search_error(query: str, message: str) -> str:
    return json.dumps({"query": query, "error": message}, ensure_ascii=False)


def _clip_summary(text: str, limit: int = MAX_SUMMARY_CHARS) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _api_error_detail(raw: bytes, fallback: str) -> str:
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        text = raw.decode("utf-8", errors="replace").strip()
        return text[:500] or fallback
    if not isinstance(data, dict):
        return fallback
    message = data.get("message") or fallback
    code = data.get("code")
    if code is None:
        return str(message)
    return f"{message}（code={code}）"


def search_web(query: str, api_key: str, top_k: int = 10, timeout: int = DEFAULT_TIMEOUT) -> str:
    query = (query or "").strip()
    if not query:
        return _search_error(query, "搜索关键词不能为空")

    api_key = (api_key or "").strip()
    if not api_key:
        return _search_error(query, "缺少配置：请在config.ini的[search]小节中设置baidu_qianfan_api_key")

    try:
        top_k = max(1, min(int(top_k), 20))
    except (TypeError, ValueError):
        top_k = 10

    try:
        timeout = max(1, min(int(timeout), 60))
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT

    payload = {
        "messages": [{"role": "user", "content": query}],
        "search_source": "baidu_search_v2",
        "resource_type_filter": [{"type": "web", "top_k": top_k}],
    }
    request = urllib.request.Request(
        SEARCH_API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as e:
        detail = _api_error_detail(e.read(), f"HTTP {e.code} {e.reason}")
        return _search_error(query, f"搜索API返回错误：{detail}")
    except (urllib.error.URLError, TimeoutError) as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
            return _search_error(query, f"网络请求超时（超过{timeout}秒）")
        return _search_error(query, f"网络请求失败：{reason}")
    except Exception as e:
        return _search_error(query, f"网络请求失败：{e}")

    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception as e:
        return _search_error(query, f"搜索API返回数据解析失败：{e}")

    if not isinstance(data, dict):
        return _search_error(query, "搜索API返回数据格式错误")

    code = data.get("code")
    if code not in (None, 0, "0", ""):
        message = data.get("message") or "未知错误"
        return _search_error(query, f"搜索API返回错误：{message}（code={code}）")

    references = data.get("references") or []
    if not isinstance(references, list):
        return _search_error(query, "搜索API返回数据格式错误：references字段无效")

    results = []
    seen_urls = set()
    for reference in references:
        if not isinstance(reference, dict):
            continue
        url = (reference.get("url") or "").strip()
        title = (reference.get("title") or reference.get("web_anchor") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        item = {
            "title": title,
            "url": url,
            "summary": _clip_summary(reference.get("snippet") or reference.get("content") or ""),
        }
        date = reference.get("date")
        if date:
            item["date"] = date
        results.append(item)

    if not results:
        return json.dumps(
            {"query": query, "results": [], "message": "未找到相关搜索结果"},
            ensure_ascii=False,
        )

    return json.dumps({"query": query, "results": results}, ensure_ascii=False)


def fetch_web(url: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    url = (url or "").strip()
    if not _is_supported_url(url):
        return _error(url, "无效的URL，仅支持http或https协议")

    try:
        timeout = int(timeout)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT
    timeout = max(1, min(timeout, 120))

    command = [
        "curl",
        "-sS",
        "-L",
        "--compressed",
        "--fail",
        "--connect-timeout",
        str(min(timeout, 10)),
        "--max-time",
        str(timeout),
        "-A",
        USER_AGENT,
        "-H",
        "Accept: text/html,application/xhtml+xml,*/*;q=0.8",
        "-H",
        "Accept-Language: zh-CN,zh;q=0.9,en;q=0.8",
        "--",
        url,
    ]

    try:
        result = subprocess.run(
            command,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout + 5,
            check=False,
        )
    except FileNotFoundError:
        return _error(url, "未找到curl程序，请确认已安装curl并加入PATH")
    except subprocess.TimeoutExpired:
        return _error(url, f"访问网页超时（超过{timeout}秒）")
    except Exception as e:
        return _error(url, f"调用curl失败: {e}")

    if result.returncode == 28:
        return _error(url, f"访问网页超时（超过{timeout}秒）")

    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        return _error(url, f"网页访问失败（curl退出码{result.returncode}）: {stderr or '未知错误'}")

    if not result.stdout:
        return _error(url, "网页访问失败：返回内容为空")

    try:
        html = _decode_html(result.stdout)
    except Exception as e:
        return _error(url, f"HTML解码失败: {e}")

    try:
        import trafilatura
    except ImportError:
        return _error(url, "缺少trafilatura库，请先执行 pip install trafilatura")

    try:
        markdown = trafilatura.extract(
            html,
            url=url,
            output_format="markdown",
            include_links=True,
            include_tables=True,
            include_comments=False,
            include_images=False,
        )
    except Exception as e:
        return _error(url, f"HTML解析失败: {e}")

    if not markdown or not markdown.strip():
        return _error(url, "正文内容无法提取")

    return json.dumps({"url": url, "markdown": markdown.strip()}, ensure_ascii=False)
