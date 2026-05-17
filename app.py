from flask import Flask, render_template, request, jsonify, send_file
import requests
from bs4 import BeautifulSoup
import re
import csv
import io
import json
import time
import openpyxl
from urllib.parse import urljoin, urlparse
from googlesearch import search

app = Flask(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
}

# ── Helpers ──────────────────────────────────────────────────────────────────

def extract_emails(text):
    return list(set(re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)))

def extract_phones(text):
    raw = re.findall(
        r"(\+?\d[\d\s\-().]{6,}\d)",
        text
    )
    cleaned = []
    for p in raw:
        digits = re.sub(r"\D", "", p)
        if 7 <= len(digits) <= 15:
            cleaned.append(p.strip())
    return list(set(cleaned))

def extract_socials(soup, base_url):
    socials = {}
    patterns = {
        "facebook":  r"facebook\.com",
        "twitter":   r"twitter\.com|x\.com",
        "instagram": r"instagram\.com",
        "linkedin":  r"linkedin\.com",
        "youtube":   r"youtube\.com",
        "tiktok":    r"tiktok\.com",
    }
    for a in soup.find_all("a", href=True):
        href = a["href"]
        for platform, pattern in patterns.items():
            if re.search(pattern, href, re.I) and platform not in socials:
                socials[platform] = href
    return socials

def find_subpages(soup, base_url):
    """Return URLs for contact/about pages."""
    keywords = ["contact", "about", "get-in-touch", "reach-us"]
    found = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        for kw in keywords:
            if kw in href and kw not in found:
                full = urljoin(base_url, a["href"])
                found[kw] = full
    return found

def scrape_page(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        return r.text
    except Exception:
        return ""

def scrape_site(url):
    result = {
        "url": url,
        "name": "",
        "emails": [],
        "phones": [],
        "socials": {},
        "contact_page": "",
        "about_page": "",
        "address": "",
        "description": "",
        "status": "ok"
    }

    html = scrape_page(url)
    if not html:
        result["status"] = "unreachable"
        return result

    soup = BeautifulSoup(html, "lxml")

    # Title / name
    title = soup.find("title")
    result["name"] = title.get_text(strip=True) if title else urlparse(url).netloc

    # Meta description
    meta = soup.find("meta", attrs={"name": "description"})
    if meta:
        result["description"] = meta.get("content", "")[:200]

    # Combine all text
    all_text = soup.get_text(" ")

    result["emails"]  = extract_emails(all_text)
    result["phones"]  = extract_phones(all_text)
    result["socials"] = extract_socials(soup, url)

    # Sub-pages
    subpages = find_subpages(soup, url)

    for kw, sub_url in subpages.items():
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

    # Address heuristic
    address_match = re.search(
        r"\d{1,4}\s[\w\s]{3,40},\s[\w\s]{2,20},\s[A-Z]{1,2}\d[\dA-Z]?\s*\d[A-Z]{2}",
        all_text
    )
    if address_match:
        result["address"] = address_match.group(0).strip()

    return result


# ── Routes ───────────────────────────────────────────────────────────────────

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
    try:
        urls = list(search(keyword, num_results=num, sleep_interval=1))
        return jsonify({"urls": urls})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    data = request.json
    urls = data.get("urls", [])
    if not urls:
        return jsonify({"error": "No URLs provided"}), 400
    results = []
    for url in urls:
        if not url.startswith("http"):
            url = "https://" + url
        results.append(scrape_site(url))
        time.sleep(0.8)
    return jsonify({"results": results})


@app.route("/api/export/csv", methods=["POST"])
def export_csv():
    results = request.json.get("results", [])
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "name", "url", "emails", "phones", "address",
        "description", "contact_page", "about_page",
        "facebook", "twitter", "instagram", "linkedin", "youtube", "tiktok", "status"
    ])
    writer.writeheader()
    for r in results:
        row = {**r}
        row["emails"]  = ", ".join(r.get("emails", []))
        row["phones"]  = ", ".join(r.get("phones", []))
        socials = r.get("socials", {})
        for s in ["facebook","twitter","instagram","linkedin","youtube","tiktok"]:
            row[s] = socials.get(s, "")
        row.pop("socials", None)
        writer.writerow(row)
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name="scrape_results.csv"
    )


@app.route("/api/export/excel", methods=["POST"])
def export_excel():
    results = request.json.get("results", [])
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Results"
    headers = ["Name","URL","Emails","Phones","Address","Description",
                "Contact Page","About Page","Facebook","Twitter",
                "Instagram","LinkedIn","YouTube","TikTok","Status"]
    ws.append(headers)
    for r in results:
        socials = r.get("socials", {})
        ws.append([
            r.get("name",""),
            r.get("url",""),
            ", ".join(r.get("emails",[])),
            ", ".join(r.get("phones",[])),
            r.get("address",""),
            r.get("description",""),
            r.get("contact_page",""),
            r.get("about_page",""),
            socials.get("facebook",""),
            socials.get("twitter",""),
            socials.get("instagram",""),
            socials.get("linkedin",""),
            socials.get("youtube",""),
            socials.get("tiktok",""),
            r.get("status",""),
        ])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="scrape_results.xlsx"
    )


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
