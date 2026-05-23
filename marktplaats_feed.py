from flask import Flask, Response
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
    try:
        resp = requests.get(SPREADSHEET_CSV_URL, timeout=20)
        resp.raise_for_status()
        f = io.StringIO(resp.text)
        reader = csv.DictReader(f)
        data = {}
        for row in reader:
            row_low = {k.lower().strip(): v for k, v in row.items() if k}
            id_val = row_low.get('id', '').strip()
            if not id_val: continue
            imgs = [row_low.get(f'image_{i}', '').strip() for i in range(1, 11) 
                    if row_low.get(f'image_{i}', '').strip().startswith('http')]
            data[id_val] = {
                "images": imgs, 
                "brand": row_low.get('brand', ''), 
                "gtin": row_low.get('gtin', ''), 
                "mpn": row_low.get('mpn', '')
            }
        return data
    except: return {}

def clean_text(text, max_len=None):
    if not text: return ""
    
    # 1. Verwijder HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    
    # 2. Vervang bekende probleem-entiteiten door normale tekens
    text = text.replace("&nbsp;", " ").replace("\xa0", " ")
    
    # 3. Decodeer alles naar platte tekst (zet &amp; om naar &)
    # We doen dit herhaaldelijk om 'double encoding' te voorkomen
    text = html.unescape(text)
    text = html.unescape(text)
    
    # 4. CRUCIAL: Zet alle losse '&' tekens om naar de XML-veilige '&amp;'
    # We doen dit handmatig omdat sommige parsers vallen over de automatische conversie
    text = text.replace("&", "&amp;")
    
    # 5. Verwijder dubbele spaties en vreemde witruimte
    text = " ".join(text.split())
    
    if max_len: 
        text = text[:max_len].strip()
        
    return text
    
def create_marktplaats_feed(google_root, spreadsheet_data):
    ADMARKT_NS = "http://admarkt.marktplaats.nl/schemas/1.0"
    ET.register_namespace('admarkt', ADMARKT_NS)
    root = ET.Element(f"{{{ADMARKT_NS}}}ads")

    items = google_root.findall(".//item")
    if not items:
        channel = google_root.find(".//channel")
        if channel is not None: items = channel.findall(".//item")

    for item in items:
        ad = ET.SubElement(root, f"{{{ADMARKT_NS}}}ad")
        v_id = (item.findtext("g:id", default="", namespaces=NS) or item.findtext("id", "")).strip()
        extra = spreadsheet_data.get(v_id, {})

        # 1. vendorId
        ET.SubElement(ad, f"{{{ADMARKT_NS}}}vendorId").text = v_id[:50]
        # 2. title
        ET.SubElement(ad, f"{{{ADMARKT_NS}}}title").text = clean_text(item.findtext("title", ""), 60)
        # 3. description
        ET.SubElement(ad, f"{{{ADMARKT_NS}}}description").text = clean_text(item.findtext("description", ""), 4000)
        # 4. categoryId
        ET.SubElement(ad, f"{{{ADMARKT_NS}}}categoryId").text = CATEGORY_ID
        
        # 5 & 6. URLs
        link = item.findtext("link", "").strip()
        ET.SubElement(ad, f"{{{ADMARKT_NS}}}url").text = link
        ET.SubElement(ad, f"{{{ADMARKT_NS}}}vanityUrl").text = link
        
        # 7. sellerName
        ET.SubElement(ad, f"{{{ADMARKT_NS}}}sellerName").text = SELLER_NAME
        
        # 8 & 9. Price
        raw_p = (item.findtext("g:price", default="", namespaces=NS) or item.findtext("price", "")).strip()
        price_cents = "0"
        if raw_p:
            try:
                val = float(raw_p.replace("EUR", "").replace(",", ".").strip())
                price_cents = str(int(round(val * 100)))
            except: pass
        ET.SubElement(ad, f"{{{ADMARKT_NS}}}price").text = price_cents
        ET.SubElement(ad, f"{{{ADMARKT_NS}}}priceType").text = "FIXED_PRICE"

        # 10. Media
        media_el = ET.SubElement(ad, f"{{{ADMARKT_NS}}}media")
        main_img = (item.findtext("g:image_link", default="", namespaces=NS) or item.findtext("image_link", "")).strip()
        if main_img:
            ET.SubElement(media_el, f"{{{ADMARKT_NS}}}image", url=main_img)
        for img in extra.get("images", []):
            if img != main_img:
                ET.SubElement(media_el, f"{{{ADMARKT_NS}}}image", url=img)

        # 11. Budget
        budget_el = ET.SubElement(ad, f"{{{ADMARKT_NS}}}budget")
        ET.SubElement(budget_el, f"{{{ADMARKT_NS}}}cpc").text = "5"  # Aangepast: Minimum CPC is 2 (2 cent)
        ET.SubElement(budget_el, f"{{{ADMARKT_NS}}}autobid").text = "true"

        # 12. Shipping
        shipping_el = ET.SubElement(ad, f"{{{ADMARKT_NS}}}shippingOptions")
        cost = "695" if int(price_cents) < 4900 else "0"
        s1 = ET.SubElement(shipping_el, f"{{{ADMARKT_NS}}}shippingOption")
        ET.SubElement(s1, f"{{{ADMARKT_NS}}}shippingType").text = "SHIP"
        ET.SubElement(s1, f"{{{ADMARKT_NS}}}cost").text = cost
        ET.SubElement(s1, f"{{{ADMARKT_NS}}}time").text = "2d-5d"
        s2 = ET.SubElement(shipping_el, f"{{{ADMARKT_NS}}}shippingOption")
        ET.SubElement(s2, f"{{{ADMARKT_NS}}}shippingType").text = "PICKUP"
        ET.SubElement(s2, f"{{{ADMARKT_NS}}}location").text = "8921EG" # Aangepast: postcode toegevoegd voor afhaallocatie foutmelding

        # 13, 14, 15. Contact/Status
        ET.SubElement(ad, f"{{{ADMARKT_NS}}}phoneNumber").text = PHONE_NUMBER
        ET.SubElement(ad, f"{{{ADMARKT_NS}}}emailAdvertiser").text = EMAIL_ADVERTISER
        ET.SubElement(ad, f"{{{ADMARKT_NS}}}status").text = "ACTIVE"
        
        # 16+. Attributes (GTIN, MPN, Brand, Condition)
        # GTIN minLength is meestal 8, maar we checken op 1 voor de zekerheid
        gtin_val = clean_text(extra.get("gtin", ""))
        if len(gtin_val) >= 2:
            ET.SubElement(ad, f"{{{ADMARKT_NS}}}gtin").text = gtin_val[:50]
            
        # MPN FIX: Moet minimaal 2 tekens zijn
        mpn_val = clean_text(extra.get("mpn", ""))
        if len(mpn_val) >= 2:
            ET.SubElement(ad, f"{{{ADMARKT_NS}}}mpn").text = mpn_val[:70]
            
        brand_val = clean_text(extra.get("brand", ""))
        if brand_val:
            ET.SubElement(ad, f"{{{ADMARKT_NS}}}brand").text = brand_val[:70]
            
        ET.SubElement(ad, f"{{{ADMARKT_NS}}}condition").text = CONDITION

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)

@app.route("/feed.xml")
def feed():
    try:
        xml_output = create_marktplaats_feed(fetch_google_feed(), fetch_spreadsheet_data())
        return Response(xml_output, mimetype="application/xml")
    except Exception as e:
        return Response(f"<error>{str(e)}</error>", status=500, mimetype="application/xml")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
