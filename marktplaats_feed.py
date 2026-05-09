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
# De export-URL van je spreadsheet (format=csv zorgt dat we het makkelijk kunnen inlezen)
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

def fetch_spreadsheet_images():
    """Haalt de spreadsheet op en maakt een dict: { product_id: [image_urls] }"""
    try:
        resp = requests.get(SPREADSHEET_CSV_URL, timeout=20)
        resp.raise_for_status()
        
        # Gebruik de csv module om de data te parsen
        f = io.StringIO(resp.text)
        reader = csv.DictReader(f)
        
        image_map = {}
        for row in reader:
            # We gaan ervan uit dat de kolom 'id' de match is met vendorId
            # En we zoeken naar kolommen 'image_1' t/m 'image_10'
            item_id = row.get('id', '').strip()
            if not item_id:
                continue
                
            images = []
            for i in range(1, 11):
                col_name = f'image_{i}'
                url = row.get(col_name, '').strip()
                if url and url.startswith('http'):
                    images.append(url)
            
            image_map[item_id] = images
        return image_map
    except Exception as e:
        print(f"Fout bij laden spreadsheet: {e}")
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

def create_marktplaats_feed(google_root, spreadsheet_images):
    ET.register_namespace('admarkt', 'http://admarkt.marktplaats.nl/schemas/1.0')
    root = ET.Element("{http://admarkt.marktplaats.nl/schemas/1.0}ads")

    items = google_root.findall(".//item")
    if not items:
        channel = google_root.find(".//channel")
        if channel is not None:
            items = channel.findall(".//item")

    for item in items:
        ad = ET.SubElement(root, "{http://admarkt.marktplaats.nl/schemas/1.0}ad")

        # Vendor ID (Product ID)
        vendor_id = item.findtext("g:id", default="", namespaces=NS).strip()
        if not vendor_id:
            vendor_id = item.findtext("g:gtin", default="", namespaces=NS).strip()
        if not vendor_id:
            vendor_id = item.findtext("link", default="").strip()
        
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}vendorId").text = vendor_id

        # Titel & Beschrijving
        title = clean_text(item.findtext("title", default=""), max_length=60)
        if len(title) > 60:
            title = title[:57] + "..."
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}title").text = title
        
        desc = clean_text(item.findtext("description", default=""), max_length=4000)
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}description").text = desc

        # Overige basisvelden
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}categoryId").text = CATEGORY_ID
        product_url = item.findtext("link", default="").strip()
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}url").text = product_url
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}vanityUrl").text = product_url

        price_cents = parse_price_cents(item)
        if price_cents:
            ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}price").text = price_cents
            ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}priceType").text = "FIXED_PRICE"

        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}phoneNumber").text = PHONE_NUMBER
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}emailAdvertiser").text = EMAIL_ADVERTISER
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}sellerName").text = SELLER_NAME
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}status").text = "ACTIVE"

        # --- MEDIA / AFBEELDINGEN LOGICA ---
        media_el = ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}media")
        
        # 1. De hoofdafbeelding uit de Google RSS feed
        image_url = (item.findtext("g:image_link", default="", namespaces=NS) or
                     item.findtext("image_link", default="")).strip()
        if image_url:
            ET.SubElement(media_el, "{http://admarkt.marktplaats.nl/schemas/1.0}image", url=image_url)

        # 2. Extra afbeeldingen uit de SPREADSHEET toevoegen (image_1 t/m image_10)
        # We matchen op de vendor_id
        extra_images = spreadsheet_images.get(vendor_id, [])
        for extra_url in extra_images:
            # Voorkom dubbele hoofdafbeelding
            if extra_url != image_url:
                ET.SubElement(media_el, "{http://admarkt.marktplaats.nl/schemas/1.0}image", url=extra_url)

        # 3. Bestaande additional_image_links uit de RSS (optioneel, als fallback)
        for add_img in item.findall("g:additional_image_link", namespaces=NS):
            url = (add_img.text or "").strip()
            if url and url != image_url and url not in extra_images:
                ET.SubElement(media_el, "{http://admarkt.marktplaats.nl/schemas/1.0}image", url=url)

        # Budget & Verzending
        budget_el = ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}budget")
        ET.SubElement(budget_el, "{http://admarkt.marktplaats.nl/schemas/1.0}cpc")
        ET.SubElement(budget_el, "{http://admarkt.marktplaats.nl/schemas/1.0}autobid").text = "true"

        shipping_el = ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}shippingOptions")
        shipping_cost = "695"
        if price_cents and int(price_cents) >= 4900:
            shipping_cost = "0"
            
        ship = ET.SubElement(shipping_el, "{http://admarkt.marktplaats.nl/schemas/1.0}shippingOption")
        ET.SubElement(ship, "{http://admarkt.marktplaats.nl/schemas/1.0}shippingType").text = "SHIP"
        ET.SubElement(ship, "{http://admarkt.marktplaats.nl/schemas/1.0}cost").text = shipping_cost
        ET.SubElement(ship, "{http://admarkt.marktplaats.nl/schemas/1.0}time").text = "2d-5d"

        pickup = ET.SubElement(shipping_el, "{http://admarkt.marktplaats.nl/schemas/1.0}shippingOption")
        ET.SubElement(pickup, "{http://admarkt.marktplaats.nl/schemas/1.0}shippingType").text = "PICKUP"
        ET.SubElement(pickup, "{http://admarkt.marktplaats.nl/schemas/1.0}location").text = ZIPCODE

        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}condition").text = CONDITION

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)

def generate_feed_response():
    try:
        # Haal beide bronnen op
        google_root = fetch_google_feed()
        spreadsheet_images = fetch_spreadsheet_images()
        
        # Genereer de Marktplaats XML
        mp_xml = create_marktplaats_feed(google_root, spreadsheet_images)
        return Response(mp_xml, mimetype="application/xml; charset=utf-8")
    except Exception as e:
        return Response(f"<error>{str(e)}</error>", status=500, mimetype="application/xml")

@app.route("/feed", methods=["GET", "HEAD"])
def feed():
    return generate_feed_response()

@app.route("/", methods=["GET"])
def home():
    return "Service is live. Gebruik /feed voor de Marktplaats-feed met extra afbeeldingen."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
