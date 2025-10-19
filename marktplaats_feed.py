from flask import Flask, Response
import requests
import xml.etree.ElementTree as ET

app = Flask(__name__)

GOOGLE_FEED_URL = "https://aquariumhuis-friesland.webnode.nl/rss/pf-google_eur.xml"
VERKOPER_NAAM = "Aquariumhuis Friesland"
CATEGORIE_ID = "396"
PRIJS_TYPE = "VASTE_PRIJS"
KENMERK_VOORWAARDE = "Nieuw"
VERZENDOPTIES = [
    {"type": "OPHALEN", "postcode": "8921SR"},
    {"type": "VERZENDEN", "kosten": "0", "omschrijving": "Gratis vanaf €49,-"}
]


def fetch_google_feed():
    """Haalt de Google Merchant feed op en retourneert XML root."""
    response = requests.get(GOOGLE_FEED_URL)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    return root


def create_marktplaats_feed(google_root):
    """Zet Google Merchant XML om naar Marktplaats XML."""
    ns = {"g": "http://base.google.com/ns/1.0"}
    mp_root = ET.Element("ads")

    for item in google_root.findall(".//item"):
        ad = ET.SubElement(mp_root, "ad")

        # Basisvelden
        ET.SubElement(ad, "leveranciers-id").text = item.findtext("g:id", default="", namespaces=ns)
        ET.SubElement(ad, "verkopersnaam").text = VERKOPER_NAAM
        ET.SubElement(ad, "titel").text = item.findtext("title", default="")
        ET.SubElement(ad, "beschrijving").text = item.findtext("description", default="")
        ET.SubElement(ad, "categorie-id").text = CATEGORIE_ID
        ET.SubElement(ad, "prijs-type").text = PRIJS_TYPE

        # Prijs (in centen)
        prijs = item.findtext("g:price", default="", namespaces=ns)
        if prijs:
            prijs_eur = prijs.replace(" EUR", "").replace(",", ".")
            try:
                prijs_cent = int(float(prijs_eur) * 100)
                ET.SubElement(ad, "prijs").text = str(prijs_cent)
            except ValueError:
                pass

        # URL en media
        ET.SubElement(ad, "url").text = item.findtext("link", default="")
        image = item.findtext("g:image_link", default="", namespaces=ns)
        if image:
            media = ET.SubElement(ad, "media")
            ET.SubElement(media, "url").text = image

        # Kenmerken (nieuw)
        kenmerken = ET.SubElement(ad, "kenmerken")
        ET.SubElement(kenmerken, "kenmerk", naam="Voorwaarde").text = KENMERK_VOORWAARDE

        # Verzendopties
        verzendopties = ET.SubElement(ad, "verzendopties")
        for optie in VERZENDOPTIES:
            o = ET.SubElement(verzendopties, "verzendoptie")
            ET.SubElement(o, "type").text = optie["type"]
            if "postcode" in optie:
                ET.SubElement(o, "postcode").text = optie["postcode"]
            if "kosten" in optie:
                ET.SubElement(o, "kosten").text = optie["kosten"]
            if "omschrijving" in optie:
                ET.SubElement(o, "omschrijving").text = optie["omschrijving"]

    return ET.tostring(mp_root, encoding="utf-8", xml_declaration=True)


@app.route("/feed")
def serve_feed():
    """Serveert de Marktplaats-feed via /feed"""
    google_root = fetch_google_feed()
    mp_xml = create_marktplaats_feed(google_root)
    return Response(mp_xml, mimetype="application/xml")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
