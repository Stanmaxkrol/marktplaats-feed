from flask import Flask, Response, jsonify
import requests
import xml.etree.ElementTree as ET
import os

app = Flask(__name__)

# Config (pas aan naar wens)
GOOGLE_FEED_URL = "https://aquariumhuis-friesland.webnode.nl/rss/pf-google_eur.xml"
VERKOPER_NAAM = "Aquariumhuis Friesland"
CATEGORIE_ID = "396"
PRIJS_TYPE = "VASTE_PRIJS"
KENMERK_VOORWAARDE = "Nieuw"
VERZENDOPTIES = [
    {"type": "OPHALEN", "postcode": "8921SR"},
    {"type": "VERZENDEN", "kosten": "0", "omschrijving": "Gratis vanaf €49,-"},
]

# Nettere namespace mapping voor Google feeds
NS = {"g": "http://base.google.com/ns/1.0"}

# Optioneel: eenvoudige health-check voor deploy platformen
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


def fetch_google_feed():
    """Haalt de Google Merchant feed op en retourneert XML root."""
    headers = {
        "User-Agent": "Aquariumhuis Friesland Feed/1.0 (+Marktplaats adapter)"
    }
    resp = requests.get(GOOGLE_FEED_URL, headers=headers, timeout=15)
    resp.raise_for_status()
    return ET.fromstring(resp.content)


def create_marktplaats_feed(google_root):
    """Zet Google Merchant XML om naar Marktplaats XML."""
    mp_root = ET.Element("ads")

    # Ondersteun zowel <item> als <channel>/<item>
    items = google_root.findall(".//item")
    if not items:
        # Sommige feeds gebruiken <channel><item>
        channel = google_root.find(".//channel")
        if channel is not None:
            items = channel.findall(".//item")

    for item in items:
        ad = ET.SubElement(mp_root, "ad")

        # Basisvelden
        leverancier_id = (
            item.findtext("g:id", default="", namespaces=NS)
            or item.findtext("id", default="")
        )
        ET.SubElement(ad, "leveranciers-id").text = leverancier_id
        ET.SubElement(ad, "verkopersnaam").text = VERKOPER_NAAM
        ET.SubElement(ad, "titel").text = item.findtext("title", default="").strip()
        ET.SubElement(ad, "beschrijving").text = item.findtext("description", default="").strip()
        ET.SubElement(ad, "categorie-id").text = CATEGORIE_ID
        ET.SubElement(ad, "prijs-type").text = PRIJS_TYPE

        # Prijs (in centen)
        prijs_raw = (
            item.findtext("g:price", default="", namespaces=NS)
            or item.findtext("price", default="")
        ).strip()
        if prijs_raw:
            # Voorbeelden: "12.95 EUR" of "12,95 EUR"
            waarde = prijs_raw.replace(" EUR", "").replace(",", ".").strip()
            try:
                prijs_cent = int(round(float(waarde) * 100))
                ET.SubElement(ad, "prijs").text = str(prijs_cent)
            except ValueError:
                pass

        # URL en media
        ET.SubElement(ad, "url").text = item.findtext("link", default="").strip()

        image = (
            item.findtext("g:image_link", default="", namespaces=NS)
            or item.findtext("image_link", default="")
        ).strip()
        if image:
            media = ET.SubElement(ad, "media")
            ET.SubElement(media, "url").text = image

        # Kenmerken
        kenmerken = ET.SubElement(ad, "kenmerken")
        ET.SubElement(kenmerken, "kenmerk", naam="Voorwaarde").text = KENMERK_VOORWAARDE

        # Verzendopties
        verzendopties = ET.SubElement(ad, "verzendopties")
        for optie in VERZENDOPTIES:
            o = ET.SubElement(verzendopties, "verzendoptie")
            ET.SubElement(o, "type").text = optie.get("type", "")
            if "postcode" in optie:
                ET.SubElement(o, "postcode").text = optie["postcode"]
            if "kosten" in optie:
                ET.SubElement(o, "kosten").text = optie["kosten"]
            if "omschrijving" in optie:
                ET.SubElement(o, "omschrijving").text = optie["omschrijving"]

    # Maak nette XML output met declaratie
    return ET.tostring(mp_root, encoding="utf-8", xml_declaration=True)


@app.route("/feed", methods=["GET", "HEAD"])
def serve_feed():
    """Serveert de Marktplaats-feed via /feed"""
    try:
        google_root = fetch_google_feed()
        mp_xml = create_marktplaats_feed(google_root)
        # Gebruik application/xml en expliciete charset
        return Response(mp_xml, mimetype="application/xml; charset=utf-8")
    except requests.HTTPError as e:
        return Response(f"<error>Upstream feed HTTP error: {e}</error>", status=502, mimetype="application/xml")
    except requests.RequestException as e:
        return Response(f"<error>Upstream feed request error: {e}</error>", status=504, mimetype="application/xml")
    except ET.ParseError as e:
        return Response(f"<error>Upstream feed parse error: {e}</error>", status=502, mimetype="application/xml")
    except Exception as e:
        return Response(f"<error>Unexpected error: {e}</error>", status=500, mimetype="application/xml")


@app.route("/", methods=["GET"])
def home():
    return "Service is live. Gebruik /feed voor de Marktplaats-feed."


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
