from flask import Flask, Response, jsonify
import requests
import xml.etree.ElementTree as ET
import os

app = Flask(__name__)

# Config
GOOGLE_FEED_URL = "https://aquariumhuis-friesland.webnode.nl/rss/pf-google_eur.xml"
VERKOPER_NAAM = "Aquariumhuis Friesland"
CATEGORIE_ID = "396"
PRIJS_TYPE = "VASTE_PRIJS"
CONDITIE = "Nieuw"
PLAATS = "Leeuwarden"
POSTCODE = "8921SR"
VERZENDOPTIES = [
    {"type": "OPHALEN", "postcode": POSTCODE},
    {"type": "VERZENDEN", "kosten": "0", "omschrijving": "Gratis vanaf €49,-"},
]

NS = {"g": "http://base.google.com/ns/1.0"}

@app.route("/api/health")
def health():
    return jsonify({"status": "ok"}), 200


def fetch_google_feed():
    headers = {"User-Agent": "Aquariumhuis Friesland Feed/1.0"}
    resp = requests.get(GOOGLE_FEED_URL, headers=headers, timeout=15)
    resp.raise_for_status()
    return ET.fromstring(resp.content)


def create_marktplaats_feed(google_root):
    mp_root = ET.Element("ads")
    items = google_root.findall(".//item")
    if not items:
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

        # Locatiegegevens
        ET.SubElement(ad, "plaats").text = PLAATS
        ET.SubElement(ad, "postcode").text = POSTCODE

        # Prijs (in centen)
        prijs_raw = (
            item.findtext("g:price", default="", namespaces=NS)
            or item.findtext("price", default="")
        ).strip()
        if prijs_raw:
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

        # Kenmerken (Conditie)
        kenmerken = ET.SubElement(ad, "kenmerken")
        ET.SubElement(kenmerken, "kenmerk", naam="Conditie").text = CONDITIE

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

    return ET.tostring(mp_root, encoding="utf-8", xml_declaration=True)


@app.route("/feed", methods=["GET", "HEAD"])
def serve_feed():
    try:
        google_root = fetch_google_feed()
        mp_xml = create_marktplaats_feed(google_root)
        return Response(mp_xml, mimetype="application/xml; charset=utf-8")
    except Exception as e:
        return Response(f"<error>{e}</error>", status=500, mimetype="application/xml")


# Extra route zodat ook /feed.xml werkt
@app.route("/feed.xml", methods=["GET", "HEAD"])
def serve_feed_xml():
    return serve_feed()


@app.route("/")
def home():
    return "Service is live. Gebruik /feed of /feed.xml voor de Marktplaats-feed."


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
