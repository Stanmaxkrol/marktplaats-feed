from flask import Flask, Response, jsonify
import requests
import xml.etree.ElementTree as ET
import os
import re
import html
import csv
import io

app = Flask(__name__)

# Config
GOOGLE_FEED_URL = "https://aquariumhuis-friesland.webnode.nl/rss/pf-google_eur.xml"
SPREADSHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/1LVq-LngUlgv7kAj4d03ijcajHcTv-WWNzSBu2QwJHmI/export?format=csv&gid=18228996"

CATEGORY_ID = "396"
CONDITION = "new"
ZIPCODE = "8921SR"
PHONE_NUMBER = "+31582124300"
EMAIL_ADVERTISER = "true"
SELLER_NAME = "Aquariumhuis Friesland"

NS = {"g": "http://base.google.com/ns/1.0"}

def fetch_google_feed():
    headers = {"User-Agent": "Marktplaats Feed Adapter/1.0"}
    resp = requests.get(GOOGLE_FEED_URL, headers=headers, timeout=20)
    resp.raise_for_status()
    return ET.fromstring(resp.content)

def fetch_spreadsheet_data():
    """Haalt data op en is flexibel met kolomnamen (hoofdletters/kleine letters)"""
    try:
        resp = requests.get(SPREADSHEET_CSV_URL, timeout=20)
        resp.raise_for_status()
        f = io.StringIO(resp.text)
        reader = csv.DictReader(f)
        
        product_data = {}
        for row in reader:
            # Maak alle keys lowercase voor makkelijker zoeken
            row_low = {k.lower().strip(): v for k, v in row.items() if k}
            
            item_id = row_low.get('id', '').strip()
            if not item_id:
                continue
            
            images = []
            for i in range(1, 11):
                url = row_low.get(f'image_{i}', '').strip()
                if url and url.startswith('http'):
                    images.append(url)
            
            product_data[item_id] = {
                "images": images,
                "brand": row_low.get('brand', '').strip(),
                "gtin": row_low.get('gtin', '').strip(),
                "mpn": row_low.get('mpn', '').strip()
            }
        return product_data
    except Exception as e:
        print(f"Spreadsheet error: {e}")
        return {}

def parse_price_cents(item):
    raw = (item.findtext("g:price", default="", namespaces=NS) or
           item.findtext("price", default="")).strip()
    if not raw:
        return None
    value = raw.replace("EUR", "").strip().replace(",", ".")
    try:
        return str(int(round(float(value) * 100)))
    except ValueError:
        return None

def clean_text(text, max_length=None):
    if not text:
        return ""
    text = text.strip()
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(html.unescape(text))
    text = text.replace("\xa0", " ").replace("&nbsp;", " ")
    text = re.sub(r"\s+", " ", text)
    if max_length:
        text = text[:max_length]
    return text

def create_marktplaats_feed(google_root, spreadsheet_data):
    ADMARKT_NS = "http://admarkt.marktplaats.nl/schemas/1.0"
    ET.register_namespace('admarkt', ADMARKT_NS)
    root = ET.Element(f"{{{ADMARKT_NS}}}ads")

    items = google_root.findall(".//item")
    if not items:
        channel = google_root.find(".//channel")
        if channel is not None:
            items = channel.findall(".//item")

    for item in items:
        ad = ET.SubElement(root, f"{{{ADMARKT_NS}}}ad")

        vendor_id = item.findtext("g:id", default="", namespaces=NS).strip()
        if not vendor_id:
            vendor_id = item.findtext("g:gtin", default="", namespaces=NS).strip()
        
        ET.SubElement(ad, f"{{{ADMARKT_NS}}}vendorId").text = vendor_id

        # Titel & Beschrijving
        title = clean_text(item.findtext("title", default=""), max_length=60)
        if len(title) > 60:
            title = title[:57] + "..."
        ET.SubElement(ad, f"{{{ADMARKT_NS}}}title").text = title
        
        desc = clean_text(item.findtext("description", default=""), max_length=4000)
        ET.SubElement(ad, f"{{{ADMARKT_NS}}}description").text = desc

        # Basis velden
        ET.SubElement(ad, f"{{{ADMARKT_NS}}}categoryId").text = CATEGORY_ID
        product_url = item.findtext("link", default="").strip()
        ET.SubElement(ad, f"{{{ADMARKT_NS}}}url").text = product_url
        ET.SubElement(ad, f"{{{ADMARKT_NS}}}vanityUrl").text = product_url

        # EXTRA DATA UIT SPREADSHEET (Brand, GTIN, MPN)
        extra_info = spreadsheet_data.get(vendor_id, {})
        
        brand = extra_info.get("brand", "")
        if brand:
            ET.SubElement(ad, f"{{{ADMARKT_NS}}}brand").text = brand[:70]

        gtin = extra_info.get("gtin", "")
        if gtin:
            ET.SubElement(ad, f"{{{ADMARKT_NS}}}gtin").text = gtin[:50]

        mpn = extra_info.get("mpn", "")
        if mpn:
            ET.SubElement(ad, f"{{{ADMARKT_NS}}}mpn").text = mpn[:70]

        # Prijs
        price_cents = parse_price_cents(item)
        if price_cents:
            ET.SubElement(ad, f"{{{ADMARKT_NS}}}price").text = price_cents
            ET.SubElement(ad, f"{{{ADMARKT_NS}}}priceType").text = "FIXED_PRICE"

        ET.SubElement(ad, f"{{{ADMARKT_NS}}}phoneNumber").text = PHONE_NUMBER
        ET.SubElement(ad, f"{{{ADMARKT_NS}}}emailAdvertiser").text = EMAIL_ADVERTISER
        ET.SubElement(ad, f"{{{ADMARKT_NS}}}sellerName").text = SELLER_NAME
        ET.SubElement(ad, f"{{{ADMARKT_NS}}}status").text = "ACTIVE"

        # Media
        media_el = ET.SubElement(ad, f"{{{ADMARKT_NS}}}media")
        image_url = (item.findtext("g:image_link", default="", namespaces=NS) or
                     item.findtext("image_link", default="")).strip()
        if image_url:
            ET.SubElement(media_el, f"{{{ADMARKT_NS}}}image", url=image_url)

        extra_images = extra_info.get("images", [])
        for extra_url in extra_images:
            if extra_url != image_url:
                ET.SubElement(media_el, f"{{{ADMARKT_NS}}}image", url=extra_url)

        # Budget & Verzending
        budget_el = ET.SubElement(ad, f"{{{ADMARKT_NS}}}budget")
        ET.SubElement(budget_el, f"{{{ADMARKT_NS}}}cpc")
        ET.SubElement(budget_el, f"{{{ADMARKT_NS}}}autobid").text = "true"

        shipping_el = ET.SubElement(ad, f"{{{ADMARKT_NS}}}shippingOptions")
        shipping_cost = "695"
        if price_cents and int(price_cents) >= 4900:
            shipping_cost = "0"
            
        ship = ET.SubElement(shipping_el, f"{{{ADMARKT_NS}}}shippingOption")
        ET.SubElement(ship, f"{{{ADMARKT_NS}}}shippingType").text = "SHIP"
        ET.SubElement(ship, f"{{{ADMARKT_NS}}}cost").text = shipping_cost
        ET.SubElement(ship, f"{{{ADMARKT_NS}}}time").text = "2d-5d"

        pickup = ET.SubElement(shipping_el, f"{{{ADMARKT_NS}}}shippingOption")
        ET.SubElement(pickup, f"{{{ADMARKT_NS}}}shippingType").text = "PICKUP"
        ET.SubElement(pickup, f"{{{ADMARKT_NS}}}location").text = ZIPCODE

        ET.SubElement(ad, f"{{{ADMARKT_NS}}}condition").text = CONDITION

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)

def generate_feed_response():
    try:
        google_root = fetch_google_feed()
        spreadsheet_data = fetch_spreadsheet_data()
        mp_xml = create_marktplaats_feed(google_root, spreadsheet_data)
        return Response(mp_xml, mimetype="application/xml; charset=utf-8")
    except Exception as e:
        return Response(f"<error>{str(e)}</error>", status=500, mimetype="application/xml")

@app.route("/feed", methods=["GET", "HEAD"])
@app.route("/feed.xml", methods=["GET", "HEAD"])
def feed():
    return generate_feed_response()

@app.route("/", methods=["GET"])
def home():
    return "Service live. Check /feed.xml voor brand, gtin en mpn."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
