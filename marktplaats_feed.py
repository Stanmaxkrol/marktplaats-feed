from flask import Flask, Response, jsonify
import requests
import xml.etree.ElementTree as ET
import os

app = Flask(__name__)

# Config
GOOGLE_FEED_URL = "https://aquariumhuis-friesland.webnode.nl/rss/pf-google_eur.xml"
CATEGORY_ID = "396"           # Marktplaats categoryId
CONDITION = "NEW"             # Toegestane waarden: NEW, USED, REFURBISHED
CITY = "Leeuwarden"
ZIPCODE = "8921SR"
VENDOR_ID = "55743253"

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
    """Parse prijs uit Google feed en zet om naar centen (integer string)."""
    raw = (item.findtext("g:price", default="", namespaces=NS) or item.findtext("price", default="")).strip()
    if not raw:
        return None
    value = raw.replace("EUR", "").strip().replace(",", ".")
    try:
        return str(int(round(float(value) * 100)))
    except ValueError:
        return None

def cdata(text):
    return f"<![CDATA[{text}]]>"

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

        # Vendor ID (verplicht)
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}vendorId").text = VENDOR_ID

        # Seller name
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}sellerName").text = SELLER_NAME

        # External ID
        external_id = item.findtext("g:id", default="", namespaces=NS) or item.findtext("id", default="")
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}externalId").text = external_id.strip()

        # Title & Description met CDATA
        title = item.findtext("title", default="").strip()
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}title").text = cdata(title)

        description = item.findtext("description", default="").strip()
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}description").text = cdata(description)

        # Category
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}categoryId").text = CATEGORY_ID

        # PriceType en Price in centen
        price_cents = parse_price_cents(item)
        if price_cents:
            ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}priceType").text = "FIXED_PRICE"
            price_el = ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}price")
            price_el.text = price_cents

        # Location
        loc = ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}location")
        ET.SubElement(loc, "{http://admarkt.marktplaats.nl/schemas/1.0}zipcode").text = ZIPCODE
        ET.SubElement(loc, "{http://admarkt.marktplaats.nl/schemas/1.0}city").text = CITY

        # Condition
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}condition").text = CONDITION

        # Product URL
        product_url = item.findtext("link", default="").strip()
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}url").text = product_url

        # Vanity URL (zelfde als product_url)
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}vanityUrl").text = product_url

        # Images
        images_el = ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}images")
        image_url = (item.findtext("g:image_link", default="", namespaces=NS) or item.findtext("image_link", default="")).strip()
        if image_url:
            ET.SubElement(images_el, "{http://admarkt.marktplaats.nl/schemas/1.0}image", url=image_url)

        # Shipping options (exacte structuur zoals voorbeeld)
        # SHIP
        shipping_el1 = ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}shippingOptions")
        ship = ET.SubElement(shipping_el1, "{http://admarkt.marktplaats.nl/schemas/1.0}shippingOption")
        ET.SubElement(ship, "{http://admarkt.marktplaats.nl/schemas/1.0}shippingType").text = "SHIP"
        ET.SubElement(ship, "{http://admarkt.marktplaats.nl/schemas/1.0}cost").text = "695"
        ET.SubElement(ship, "{http://admarkt.marktplaats.nl/schemas/1.0}time").text = "2d-5d"

        # PICKUP
        shipping_el2 = ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}shippingOptions")
        pickup = ET.SubElement(shipping_el2, "{http://admarkt.marktplaats.nl/schemas/1.0}shippingOption")
        ET.SubElement(pickup, "{http://admarkt.marktplaats.nl/schemas/1.0}shippingType").text = "PICKUP"
        ET.SubElement(pickup, "{http://admarkt.marktplaats.nl/schemas/1.0}location").text = ZIPCODE

        # Contactgegevens BUITEN shippingOptions
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}phoneNumber").text = PHONE_NUMBER
        ET.SubElement(ad, "{http://admarkt.marktplaats.nl/schemas/1.0}emailAdvertiser").text = EMAIL_ADVERTISER

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
