import re, json
from urllib.parse import urlparse, urljoin, urldefrag, parse_qs, urlunparse
from bs4 import BeautifulSoup
from collections import defaultdict, Counter
import atexit

unique_pages   = set()
longest_page   = ("", 0)
token_freq     = defaultdict(int)
subdomains     = defaultdict(set)

STOP_WORDS = {
    "a","about","above","after","again","against","all","am","an","and","any",
    "are","aren't","as","at","be","because","been","before","being","below",
    "between","both","but","by","can't","cannot","could","couldn't","did",
    "didn't","do","does","doesn't","doing","don't","down","during","each",
    "few","for","from","further","get","got","had","hadn't","has","hasn't",
    "have","haven't","having","he","he'd","he'll","he's","her","here","here's",
    "hers","herself","him","himself","his","how","how's","i","i'd","i'll",
    "i'm","i've","if","in","into","is","isn't","it","it's","its","itself",
    "let's","me","more","most","mustn't","my","myself","no","nor","not","of",
    "off","on","once","only","or","other","ought","our","ours","ourselves",
    "out","over","own","same","shan't","she","she'd","she'll","she's","should",
    "shouldn't","so","some","such","than","that","that's","the","their",
    "theirs","them","themselves","then","there","there's","these","they",
    "they'd","they'll","they're","they've","this","those","through","to","too",
    "under","until","up","very","was","wasn't","we","we'd","we'll","we're",
    "we've","were","weren't","what","what's","when","when's","where","where's",
    "which","while","who","who's","whom","why","why's","will","with","won't",
    "would","wouldn't","you","you'd","you'll","you're","you've","your","yours",
    "yourself","yourselves"
}

def scraper(url, resp):
    links = extract_next_links(url, resp)
    valid = [link for link in links if is_valid(link)]
    # _save_stats()
    return valid

# ------------------------------------------------------------------------------
# Link extraction
# ------------------------------------------------------------------------------

def extract_next_links(url, resp):
    # Processes a crawled page and tracks subdomains, extracts links
    # and update stats (unique pages, longest page, word frequencies)
    global longest_page, unique_pages, token_freq, subdomains
    links = []

    # 1. response check
    if resp.status != 200 or resp.raw_response is None:
        return links
    
    base_url = resp.raw_response.url    # final URL of the HTTP response after any redirects
    defragmented_url, _ = urldefrag(base_url)   # final URL without fragments 

    parsed = urlparse(defragmented_url)         # ParsedResult object (gives .scheme, .netloc, etc.)
    host = parsed.netloc.lower()        # domain part of URL

    # 2. subdomain tracking - moved early to track subdomains immediately right after URL is parsed
    # counts every subdomain that returns a successful 200 response page 
    if re.search(r"(^|\.)(ics|cs|informatics|stat)\.uci\.edu$", host):
        subdomains[host].add(defragmented_url)
    
    # 3. check if a page's content type is text/html. skips pdf, image to improve efficiency
    content_type = resp.raw_response.headers.get("Content-Type", "").lower()
    if "text/html" not in content_type:
        return links

    content = resp.raw_response.content

    # 4. check content 
    # len(content) is not # of words. its bytes of a page.
    if not content or len(content) < 100:
        return links

    # 5. html parsing
    try:
        soup = BeautifulSoup(content, "lxml")
    except Exception:
        soup = BeautifulSoup(content, "html.parser")

    # 6. skip login pages (title check)
    final_url = base_url.lower()
    title_tag = soup.find("title")
    title_text = title_tag.get_text().lower() if title_tag else ""

    if any(word in final_url for word in ["login", "noauth", "signin", "cas.uci.edu"]):
        return links
    if any(word in title_text for word in ["login", "sign in", "access denied", "authentication required", "forbidden"]):
        return links

    # 7. robots meta handling
    robots_meta = soup.find("meta", attrs={"name": "robots"})
    robots_content = robots_meta.get("content", "").lower() if robots_meta else ""
    
    # "nofollow": do NOT follow any hyperlinks on page for further crawling
    # 8. if "nofollow" is NOT present, collect links to follow
    if "nofollow" not in robots_content:
        for tag in soup.find_all("a", href=True):
            try:
                href = tag["href"].strip()
                absolute = urljoin(base_url, href)
                defragged, _ = urldefrag(absolute)
                links.append(defragged)
            except ValueError:
                continue

    # "noindex": do NOT show page in search/indexing or reports 
    # 9. if "noindex" is NOT present, proceed to report
    if "noindex" not in robots_content:
        # unique_pages should ignore fragments AND queries (refer to ed discussion #122)
        # assume unique_pages counts pages that respond to status 200 AND have meaningful info
        parsed_unique = parsed._replace(query="", fragment="")
        unique_url = urlunparse(parsed_unique).rstrip('/')

        unique_pages.add(unique_url)

        text = soup.get_text(separator=" ")
        words = [w.lower() for w in re.findall(r"[a-zA-Z']{2,}", text)]

        if len(words) > longest_page[1]:
            longest_page = (defragmented_url, len(words))

        for word in words:
            if word not in STOP_WORDS:
                token_freq[word] += 1

    return links

# ------------------------------------------------------------------------------
# Stats and URL filtering
# ------------------------------------------------------------------------------

def _save_stats():
    # Save stats when the program exits via atexit.register() at bottom.
    # - records: unique pages, longest page, top 50 words 
    # - (excluding stop words or words < 2 characters), and subdomains 

    top_50 = sorted(token_freq.items(), key=lambda x: x[1], reverse=True)[:50]
    sorted_subs = sorted(
        {sub: len(pages) for sub, pages in subdomains.items()}.items()
    )
    stats = {
        "unique_pages": len(unique_pages),
        "longest_page": {"url": longest_page[0], "word_count": longest_page[1]},
        "top_50_words": top_50,
        "subdomains": sorted_subs,
    }
    with open("stats.json", "w") as f:
        json.dump(stats, f, indent=2)

def is_valid(url):
    # Decide whether to crawl this url or not. 
    # If you decide to crawl it, return True; otherwise return False.
    # There are already some conditions that return False.
    # Enforces: domain restrictions, trap detection, and file type filtering
    try:
        parsed = urlparse(url)

        # scheme restriction
        if parsed.scheme not in {"http", "https"}:
            return False

        # domain restriction
        host = parsed.netloc.lower()
        allowed = (
            re.search(r"(^|\.)ics\.uci\.edu$", host) or
            re.search(r"(^|\.)cs\.uci\.edu$", host) or
            re.search(r"(^|\.)informatics\.uci\.edu$", host) or
            re.search(r"(^|\.)stat\.uci\.edu$", host)
        )
        if not allowed:
            return False

        # path-based trap detection
        path_lower = parsed.path.lower()

        # filters out excessive deep paths trap (ex: /a/b/c/d/e/f/g/h/i/j/k)
        path_parts = [p for p in path_lower.split("/") if p]
        if len(path_parts) > 10:
            return False
        
        # filters out paths where it repeats 3+ times (ex: /a/b/a/b/a/b/)
        path_part_counts = Counter(path_parts)
        if any(count >= 3 for count in path_part_counts.values()):
            return False
        
        if re.search(r"/events/|/event/", path_lower):
            return False
    
        # Block month calendar paths (but NOT "may" as a common word)
        months_pattern = r"/(january|february|march|april|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)(/|-|_|\d|$)"
        if re.search(months_pattern, path_lower):
            return False
        
        if re.search(r"(login|noauth|ticket)", path_lower):
            return False

        if re.search(r"(genealogy|family|marriage|birth|death)", path_lower):
            return False

        # query-based trap detection
        query_params = parse_qs(parsed.query).keys()
        raw_query = parsed.query.lower()

        # filters out URLs with too many query parameters (ex: ?a=1&b=2&c=3&d=4&e=5&f=6&g=7&h=8&i=9)
        if len(query_params) > 8:
            return False
        
        blocked_query_params = {
            "ical", "outlook-ical", "tribe-bar-date", "action", "replytocom", "eventDisplay",
            "rev", "diff", "precision", "version", "calendar", "cal", "date"
        }

        if blocked_query_params & query_params:
            return False
        
        if re.search(r"([?&][cmo]=|;[cmo]=)", raw_query):
            return False
        
        # avoid specific site traps
        if re.search(r"/releases/\d", path_lower):
            return False
    
        if re.search(r"/page/\d+", path_lower):
            return False
        
        if re.search(r"doku\.php/group", path_lower):
            return False

        if "doku.php" in path_lower and raw_query:
            return False

        if "/pix/" in path_lower:
            return False

        # filter file extension type
        return not re.match(
            r".*\.(css|js|bmp|gif|jpe?g|ico"
            + r"|png|tiff?|mid|mp2|mp3|mp4"
            + r"|wav|avi|mov|mpeg|ram|m4v|mkv|ogg|ogv|pdf"
            + r"|ps|eps|tex|ppt|pptx|doc|docx|xls|xlsx|names"
            + r"|data|dat|exe|bz2|tar|msi|bin|7z|psd|dmg|iso"
            + r"|epub|dll|cnf|tgz|sha1"
            + r"|thmx|mso|arff|rtf|jar|csv"
            + r"|rm|smil|wmv|swf|wma|zip|rar|gz)$", path_lower)

    except TypeError:
        print("TypeError for ", parsed)
        raise

atexit.register(_save_stats)