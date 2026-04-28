import re, json
from urllib.parse import urlparse, urljoin, urldefrag
from bs4 import BeautifulSoup
from collections import defaultdict

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
    _save_stats()
    return valid

def extract_next_links(url, resp):
    global longest_page

    if resp.status != 200 or resp.raw_response is None:
        return []

    content = resp.raw_response.content
    if not content or len(content) < 100:
        return []

    soup = BeautifulSoup(content, "lxml")
    base_url = resp.raw_response.url

    page_url, _ = urldefrag(base_url)
    unique_pages.add(page_url)

    text = soup.get_text(separator=" ")
    words = [w.lower() for w in re.findall(r"[a-zA-Z]+", text) if len(w) > 1]

    if len(words) > longest_page[1]:
        longest_page = (page_url, len(words))

    for word in words:
        if word not in STOP_WORDS:
            token_freq[word] += 1

    parsed = urlparse(page_url)
    host = parsed.netloc.lower()
    if host.endswith(".ics.uci.edu"):
        subdomains[host].add(page_url)

    links = []
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        absolute = urljoin(base_url, href)
        defragged, _ = urldefrag(absolute)
        links.append(defragged)

    return links

def _save_stats():
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
    try:
        parsed = urlparse(url)

        if parsed.scheme not in {"http", "https"}:
            return False

        host = parsed.netloc.lower()
        allowed = (
            re.search(r"(^|\.)ics\.uci\.edu$", host) or
            re.search(r"(^|\.)cs\.uci\.edu$", host) or
            re.search(r"(^|\.)informatics\.uci\.edu$", host) or
            re.search(r"(^|\.)stat\.uci\.edu$", host)
        )
        if not allowed:
            return False

        if len(parsed.query) > 200:
            return False

        if re.search(r"(calendar|date|event|action=|tribe-bar-date)", parsed.query.lower()):
            return False

        path_parts = [p for p in parsed.path.lower().split("/") if p]
        if len(path_parts) != len(set(path_parts)) and len(path_parts) > 6:
            return False

        return not re.match(
            r".*\.(css|js|bmp|gif|jpe?g|ico"
            + r"|png|tiff?|mid|mp2|mp3|mp4"
            + r"|wav|avi|mov|mpeg|ram|m4v|mkv|ogg|ogv|pdf"
            + r"|ps|eps|tex|ppt|pptx|doc|docx|xls|xlsx|names"
            + r"|data|dat|exe|bz2|tar|msi|bin|7z|psd|dmg|iso"
            + r"|epub|dll|cnf|tgz|sha1"
            + r"|thmx|mso|arff|rtf|jar|csv"
            + r"|rm|smil|wmv|swf|wma|zip|rar|gz)$", parsed.path.lower())

    except TypeError:
        print("TypeError for ", parsed)
        raise