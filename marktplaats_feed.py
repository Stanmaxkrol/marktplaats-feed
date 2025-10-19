from flask import Flask, Response, jsonify
import requests
import xml.etree.ElementTree as ET
import os

app = Flask(__name__)

# Config
GOOGLE_FEED_URL = "https://aquariumhuis-friesland.webnode.nl/rss/pf-google_eur.xml"
CATEGORY_ID = "396"           # Marktplaats categoryId
CONDITION = "NEW"             # Toegestane waarden: NEW, USED, REFURBISHED (afhankelijk van XSD)
CITY = "Leeuwarden"
ZIPCODE = "8921SR"
SHIPPING_OPTIONS = [
    {"type": "PICKUP"},  # Ophalen
    {"type": "DELIVERY", "cost": "0", "description": "Gratis vanaf €49,-"},
]

NS = {"g": "http://base.google.com/ns/1.0"}


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


def fetch_google_feed():
    headers = {"User-Agent": "Marktplaats Feed Adapter/1.0"}
    resp = requests.get(GOOGLE_FEED_URL, headers=headers, timeout=20)
    resp.raise_for_status()
    return ET.fromstring(resp.content)


def parse_price_eur(item):
    """Return price in euros as string, e.g. '12.95' (no currency suffix)."""
    raw = (item.findtext("g:price", default="", namespaces=NS) or item.findtext("price", default="")).strip()
    if not raw:
        return None
    # Examples: "12.95 EUR", "12,95 EUR", "12.95"
    value = raw.replace("EUR", "").strip()
    value = value.replace(",", ".")
    try:
        # Keep two decimals as text
        num = float(value)
        return f"{num:.2f}"
    except ValueError:
        return None


def create_marktplaats_feed(google_root):
    """
    Bouw XSD-conforme feed:
    <ads>
      <ad>
        <externalId>...</externalId>
        <title>...</title>
        <description>...</description>
        <categoryId>396</categoryId>
        <price currency="EUR">12.95</price>
        <location>
          <zipcode>8921SR</zipcode>
          <city>Leeuwarden</city>
        </location>
        <condition>NEW</condition>
        <url>https://...</url>
        <images>
          <image url="https://..."/>
        </images>
        <shippingOptions>
          <shippingOption>
            <type>PICKUP</type>
          </shippingOption>
          <shippingOption>
            <type>DELIVERY</type>
            <cost>0</cost>
            <description>Gratis vanaf €49,-</description>
          </shippingOption>
        </shippingOptions>
      </ad>
    </ads>
    """
    root = ET.Element("ads")

    # Ondersteun <rss><channel><item> alsook los <item>
    items = google_root.findall(".//item")
    if not items:
        channel = google_root.find(".//channel")
        if channel is not None:
            items = channel.findall(".//item")

    for item in items:
        ad = ET.SubElement(root, "ad")

        # IDs & basis
        external_id = item.findtext("g:id", default="", namespaces=NS) or item.findtext("id", default="")
        ET.SubElement(ad, "externalId").text = external_id.strip()

        title = item.findtext("title", default="").strip()
        ET.SubElement(ad, "title").text = title

        description = item.findtext("description", default="").strip()
        ET.SubElement(ad, "description").text = description

        ET.SubElement(ad, "categoryId").text = CATEGORY_ID

        # Prijs (EUR met attribuut currency)
        price_eur = parse_price_eur(item)
        if price_eur:
            price_el = ET.SubElement(ad, "price", currency="EUR")
            price_el.text = price_eur

        # Locatie
        loc = ET.SubElement(ad, "location")
        ET.SubElement(loc, "zipcode").text = ZIPCODE
        ET.SubElement(loc, "city").text = CITY

        # Conditie
        ET.SubElement(ad, "condition").text = CONDITION

        # URL (product link)
        product_url = item.findtext("link", default="").strip()
        ET.SubElement(ad, "url").text = product_url

        # Afbeeldingen (één of meer)
        images_el = ET.SubElement(ad, "images")
        image_url = (item.findtext("g:image_link", default="", namespaces=NS) or item.findtext("image_link", default="")).strip()
        if image_url:
            ET.SubElement(images_el, "image", url=image_url)

        # Verzendopties (PICKUP/DELIVERY)
        shipping_el = ET.SubElement(ad, "shippingOptions")
        for opt in SHIPPING_OPTIONS:
            so = ET.SubElement(shipping_el, "shippingOption")
            ET.SubElement(so, "type").text = opt.get("type", "").strip()
            if "cost" in opt:
                ET.SubElement(so, "cost").text = str(opt["cost"])
            if "description" in opt and opt["description"]:
                ET.SubElement(so, "description").text = opt["description"]

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
