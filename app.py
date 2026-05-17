from flask import Flask, render_template, request, jsonify, send_file
import requests
from bs4 import BeautifulSoup
import re
import csv
import io
import time
import os
import openpyxl
from urllib.parse import urljoin, urlparse

app = Flask(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]
_ua_index = 0

def get_headers():
    global _ua_index
    ua = USER_AGENTS[_ua_index % len(USER_AGENTS)]
    _ua_index += 1
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0",
    }

def extract_emails(text):
    found = re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)
    filtered = [e for e in found if not re.search(r"\.(png|jpg|gif|svg|webp|css|js)$", e, re.I)]
    return list(set(filtered))

def extract_phones(text):
    raw = re.findall(r"(\+?\d[\d\s\-().]{6,}\d)", text)
    cleaned = []
    for p in raw:
        digits = re.sub(r"\D", "", p)
        if 7 <= len(digits) <= 15:
            cleaned.append(p.strip())
    return list(set(cleaned))

def extract_socials(soup, base_url):
    socials = {}
    patterns = {
        "facebook":  r"facebook\.com/(?!sharer|share|login)",
        "twitter":   r"twitter\.com/(?!share|intent)|x\.com/(?!share|intent)",
        "instagram": r"instagram\.com/",
        "linkedin":  r"linkedin\.com/",
        "youtube":   r"youtube\.com/(?!watch)",
        "tiktok":    r"tiktok\.com/@",
    }
    for a in soup.find_all("a", href=True):
        href = a["href"]
        for platform, pattern in patterns.items():
            if re.search(pattern, href, re.I) and platform not in socials:
                socials[platform] = href
    return socials

def find_subpages(soup, base_url):
    keywords = ["contact", "about", "get-in-touch", "reach-us", "find-us"]
    found = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        for kw in keywords:
            if kw in href and kw not in found:
                full = urljoin(base_url, a["href"])
                if urlparse(full).netloc == urlparse(base_url).netloc or not urlparse(full).netloc:
                    found[kw] = full
    return found

def scrape_page(url, retries=2):
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=get_headers(), timeout=12, allow_redirects=True)
            if r.status_code == 200:
                return r.text
            elif r.status_code in (403, 429) and attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            else:
                return ""
        except requests.exceptions.SSLError:
            try:
                r = requests.get(url, headers=get_headers(), timeout=12, verify=False)
                return r.text if r.status_code == 200 else ""
            except Exception:
                return ""
        except Exception:
            if attempt < retries:
                time.sleep(1)
            continue
    return ""

def scrape_site(url):
    result = {
        "url": url, "name": "", "emails": [], "phones": [],
        "socials": {}, "contact_page": "", "about_page": "",
        "address": "", "description": "", "status": "ok"
    }
    html = scrape_page(url)
    if not html:
        result["status"] = "unreachable"
        return result

    soup = BeautifulSoup(html, "lxml")
    title = soup.find("title")
    result["name"] = title.get_text(strip=True) if title else urlparse(url).netloc

    meta = soup.find("meta", attrs={"name": "description"})
    if meta:
        result["description"] = meta.get("content", "")[:200]

    all_text = soup.get_text(" ")
    result["emails"]  = extract_emails(all_text)
    result["phones"]  = extract_phones(all_text)
    result["socials"] = extract_socials(soup, url)

    subpages = find_subpages(soup, url)
    for kw, sub_url in subpages.items():
        if sub_url == url:
            continue
        sub_html = scrape_page(sub_url)
        if not sub_html:
            continue
        sub_soup = BeautifulSoup(sub_html, "lxml")
        sub_text = sub_soup.get_text(" ")
        result["emails"]  = list(set(result["emails"]  + extract_emails(sub_text)))
        result["phones"]  = list(set(result["phones"]  + extract_phones(sub_text)))
        result["socials"].update(extract_socials(sub_soup, sub_url))
        if "contact" in kw:
            result["contact_page"] = sub_url
        if "about" in kw:
            result["about_page"] = sub_url
        time.sleep(0.5)

    address_match = re.search(
        r"\d{1,4}\s[\w\s]{3,40},\s[\w\s]{2,20},\s[A-Z]{1,2}\d[\dA-Z]?\s*\d[A-Z]{2}",
        all_text
    )
    if address_match:
        result["address"] = address_match.group(0).strip()

    return result

def search_google(keyword, num=10):
    api_key = os.environ.get("SERPAPI_KEY", "")
    if api_key:
        try:
            params = {"q": keyword, "num": num, "api_key": api_key, "engine": "google"}
            r = requests.get("https://serpapi.com/search", params=params, timeout=15)
            data = r.json()
            urls = [item["link"] for item in data.get("organic_results", [])[:num]]
            return urls, None
        except Exception as e:
            return [], str(e)
    else:
        try:
            r = requests.get(
                "https://html.duckduckgo.com/html/",
                params={"q": keyword},
                headers=get_headers(),
                timeout=15,
            )
            soup = BeautifulSoup(r.text, "lxml")
            links = []
            for a in soup.select("a.result__a"):
                href = a.get("href", "")
                if href.startswith("http") and "duckduckgo" not in href:
                    links.append(href)
                if len(links) >= num:
                    break
            warning = None if links else "No results found. Add a SERPAPI_KEY env var on Render for reliable keyword search."
            return links, warning
        except Exception as e:
            return [], str(e)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/search", methods=["POST"])
def api_search():
    data = request.json
    keyword = data.get("keyword", "").strip()
    num = int(data.get("num", 10))
    if not keyword:
        return jsonify({"error": "No keyword provided"}), 400
    urls, error = search_google(keyword, num)
    if error and not urls:
        return jsonify({"error": error}), 500
    return jsonify({"urls": urls, "warning": error})

@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    data = request.json
    urls = data.get("urls", [])
    if not urls:
        return jsonify({"error": "No URLs provided"}), 400
    seen = set()
    unique_urls = []
    for url in urls:
        if not url.startswith("http"):
            url = "https://" + url
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)
    results = []
    for url in unique_urls:
        results.append(scrape_site(url))
        time.sleep(0.8)
    return jsonify({"results": results})

@app.route("/api/export/csv", methods=["POST"])
def export_csv():
    results = request.json.get("results", [])
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "name","url","emails","phones","address","description",
        "contact_page","about_page","facebook","twitter",
        "instagram","linkedin","youtube","tiktok","status"
    ])
    writer.writeheader()
    for r in results:
        row = {**r}
        row["emails"] = ", ".join(r.get("emails", []))
        row["phones"] = ", ".join(r.get("phones", []))
        socials = r.get("socials", {})
        for s in ["facebook","twitter","instagram","linkedin","youtube","tiktok"]:
            row[s] = socials.get(s, "")
        row.pop("socials", None)
        writer.writerow(row)
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode()), mimetype="text/csv",
                     as_attachment=True, download_name="scrape_results.csv")

@app.route("/api/export/excel", methods=["POST"])
def export_excel():
    results = request.json.get("results", [])
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Results"
    ws.append(["Name","URL","Emails","Phones","Address","Description",
                "Contact Page","About Page","Facebook","Twitter",
                "Instagram","LinkedIn","YouTube","TikTok","Status"])
    for r in results:
        socials = r.get("socials", {})
        ws.append([
            r.get("name",""), r.get("url",""),
            ", ".join(r.get("emails",[])), ", ".join(r.get("phones",[])),
            r.get("address",""), r.get("description",""),
            r.get("contact_page",""), r.get("about_page",""),
            socials.get("facebook",""), socials.get("twitter",""),
            socials.get("instagram",""), socials.get("linkedin",""),
            socials.get("youtube",""), socials.get("tiktok",""),
            r.get("status",""),
        ])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True, download_name="scrape_results.xlsx")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
