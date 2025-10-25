from flask import Flask, Response, jsonify
import requests
import xml.etree.ElementTree as ET
import os
import re
import html

app = Flask(__name__)

# Config
GOOGLE_FEED_URL = "https://aquariumhuis-friesland.webnode.nl/rss/pf-google_eur.xml"
CATEGORY_ID = "396"           # Marktplaats categoryId
CONDITION = "new"             # Toegestane waarden: new, used, refurbished
ZIPCODE = "8921SR"

PHONE_NUMBER = "+31582124300"
EMAIL_ADVERTISER = "true"
SELLER_NAME = "Aquariumhuis Friesland"

NS = {"g": "http://base.google.com/ns/1.0"}

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


def fetch_google_feed():
    headers = {"User-Agent": "Marktplaats Feed Adapter/1.0"}
    resp = requests.get(GOOGLE_FEED_URL, headers=headers, timeout=20)
    resp.raise_for_status()
    return ET.fromstring(resp.content)


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
    """Verwijder HTML, decodeer entities en geef platte tekst terug."""
    if not text:
        return ""
    text = text.strip()
    text = re.sub(r"<[^>]+>", "", text)               # verwijder HTML-tags
    text = html.unescape(html.unescape(text))         # decodeer dubbele entities
    text = text.replace("\xa0", " ").replace("&nbsp;", " ")
    text = re.sub(r"\s+", " ", text)                  # normaliseer witruimte
    if max_length:
        text = text[:max_length]
    return text


def create_marktplaats_feed(google_root):
    ET.register_namespace('admarkt', 'http://admarkt.marktplaats.nl/schemas/1.0')
    root = ET.Element("{http://admarkt.marktplaats.nl/schemas/1.0}ads")

    items = google_root.findall(".//item")
    if not items:
        channel = google_root.find(".//channel")
        if channel is not None:
            items = channel.findall(".//item")

    for item in items:
        ad = ET.SubElement(root, "{http://admarkt.marktplaats.nl/schemas/1.0}ad")

        # Vendor ID
        vendor_id = item.findtext("g:id", default="", namespaces=NS).strip()
        if not vendor_id:
            vendor_id = item.findtext("g:gtin", default="", namespaces=NS).strip()
        if not vendor_id:
            vendor_id = item.findtext("link", default="").strip()
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}vendorId").text = vendor_id

        # Titel – platte tekst, max 60 karakters
        title = clean_text(item.findtext("title", default=""), max_length=60)
        if len(title) > 60:
            title = title[:57] + "..."
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}title").text = title

        # Beschrijving – platte tekst, max 4000 tekens
        desc = clean_text(item.findtext("description", default=""), max_length=4000)
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}description").text = desc

        # Categorie
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}categoryId").text = CATEGORY_ID

        # URL & Vanity URL
        product_url = item.findtext("link", default="").strip()
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}url").text = product_url
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}vanityUrl").text = product_url

        # Prijs
        price_cents = parse_price_cents(item)
        if price_cents:
            ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}price").text = price_cents
            ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}priceType").text = "FIXED_PRICE"

        # Contactgegevens
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}phoneNumber").text = PHONE_NUMBER
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}emailAdvertiser").text = EMAIL_ADVERTISER
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}sellerName").text = SELLER_NAME

        # Status
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}status").text = "ACTIVE"

        # Media (afbeeldingen)
        media_el = ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}media")
        image_url = (item.findtext("g:image_link", default="", namespaces=NS) or
                     item.findtext("image_link", default="")).strip()
        if image_url:
            ET.SubElement(media_el, "{http://admarkt.marktplaats.nl/schemas/1.0}image", url=image_url)
        for add_img in item.findall("g:additional_image_link", namespaces=NS):
            url = (add_img.text or "").strip()
            if url:
                ET.SubElement(media_el, "{http://admarkt.marktplaats.nl/schemas/1.0}image", url=url)

        # Budget – alleen autobid = true
        budget_el = ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}budget")
        ET.SubElement(budget_el, "{http://admarkt.marktplaats.nl/schemas/1.0}autobid").text = "true"

        # Verzendopties
        shipping_el = ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}shippingOptions")

        ship = ET.SubElement(shipping_el, "{http://admarkt.marktplaats.nl/schemas/1.0}shippingOption")
        ET.SubElement(ship, "{http://admarkt.marktplaats.nl/schemas/1.0}shippingType").text = "SHIP"
        ET.SubElement(ship, "{http://admarkt.marktplaats.nl/schemas/1.0}cost").text = "695"
        ET.SubElement(ship, "{http://admarkt.marktplaats.nl/schemas/1.0}time").text = "2d-5d"

        pickup = ET.SubElement(shipping_el, "{http://admarkt.marktplaats.nl/schemas/1.0}shippingOption")
        ET.SubElement(pickup, "{http://admarkt.marktplaats.nl/schemas/1.0}shippingType").text = "PICKUP"
        ET.SubElement(pickup, "{http://admarkt.marktplaats.nl/schemas/1.0}location").text = ZIPCODE

        # Conditie
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}condition").text = CONDITION

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def generate_feed_response():
    try:
        google_root = fetch_google_feed()
        mp_xml = create_marktplaats_feed(google_root)
        return Response(mp_xml, mimetype="application/xml; charset=utf-8")
    except requests.HTTPError as e:
        return Response(f"<error>Upstream HTTP error: {e}</error>", status=502, mimetype="application/xml")
    except requests.RequestException as e:
        return Response(f"<error>Upstream request error: {e}</error>", status=504, mimetype="application/xml")
    except ET.ParseError as e:
        return Response(f"<error>Upstream parse error: {e}</error>", status=502, mimetype="application/xml")
    except Exception as e:
        return Response(f"<error>Unexpected error: {e}</error>", status=500, mimetype="application/xml")


@app.route("/feed", methods=["GET", "HEAD"])
def feed():
    return generate_feed_response()


@app.route("/feed.xml", methods=["GET", "HEAD"])
def feed_xml():
    return generate_feed_response()


@app.route("/", methods=["GET"])
def home():
    return "Service is live. Gebruik /feed of /feed.xml voor de Marktplaats-feed."


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
