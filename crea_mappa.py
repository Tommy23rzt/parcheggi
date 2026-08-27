#!/usr/bin/env python3
import csv
import json
import time

import requests
import folium

COLORI = {1: "red", 2: "blue", 3: "green", 4: "orange"}

ENDPOINTS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

# nome usato nel PDF (chiave) -> nome reale in OpenStreetMap (valore)
SINONIMI = {
    "Contrà Mure Rocchetta": "Contra' Mure della Rocchetta",
    "Contrà Mure San Rocco": "Contra' Mure San Rocco",
    "Contrà S. Maria Nova": "Contra' Santa Maria Nova",
    "Contrà S.Rocco": "Contra' San Rocco",
    "Contrà Busato": "Contra' Giovanni Busato",
    "Contrà Borghetto": "Contra' del Borghetto",
    "Contrà Lodi": "Contra' Lodi",
    "Contra' Porta Nova": "Contra' Porta Nova",
    "Corso Fogazzaro": "Corso Antonio Fogazzaro",
    "Stradella Borghetto": "Stradella del Borghetto",
    "Porta S.Croce": "Contra' Porta Santa Croce",
    "Mure Corpus Domini": "Contra' Mure Corpus Domini",
    "Contrà Corpus Domini": "Contra' Corpus Domini",
    "Contrà S.Ambrogio": "Contra' Sant'Ambrogio",
    "Str.lla Soccorso Socc.to": "Stradella Soccorso Soccorsetto",
    "Contrà Mure Porta Nova": "Contra' Mure Porta Nova",
    "Via G.B. Vico": "Via Giambattista Vico",
    "Via Galilei": "Via Galileo Galilei",
    "Via Pacinotti": "Via Antonio Pacinotti",
    "Via Pagliarino": "Via Giambattista Pagliarino",
    "Via Pajello": "Via Bartolomeo Pajello",
    "Via Sarpi": "Via fra' Paolo Sarpi",
    "Via Tasso": "Via Torquato Tasso",
    "Via Torricelli": "Via Evangelista Torricelli",
    "Via Volta": "Via Alessandro Volta",
    "Viale D'Alviano": "Viale Bartolomeo d'Alviano",
    "Contrà S. Bortolo": "Contra' San Bortolo",
    "Contrà S. Francesco": "Contra' San Francesco",
    "Contrà Forti San Francesco": "Contra' dei Forti di San Francesco",
    "Contrà della Misericordia": "Contra' della Misericordia",
    "Contrà S. Marco": "Contra' San Marco",
    "Area Legione Gallieno": "Via Legione Gallieno",
    "Contrà Mure S. Domenico": "Contra' Mure San Domenico",
    "Contrà S.Domenico": "Contra' San Domenico",
    "Contrà Porta S.Lucia": "Contra' Porta Santa Lucia",
    "Contrà Porta Padova": "Contra' Porta Padova",
    "Contrà dei Torretti": "Contra' dei Torretti",
    "Contrà S. Pietro": "Contra' San Pietro",
    "Piazza S. Pietro": "Piazza San Pietro",
    "Via IV Novembre": "Via Quattro Novembre",
    "Contrà Burci": "Contra' dei Burci",
    "Contrà S. Caterina": "Contra' Santa Caterina",
    "Contrà S. Chiara": "Contra' Santa Chiara",
    "Contrà S. Silvestro": "Contra' San Silvestro",
    "Contrà S. Tomaso": "Contra' San Tomaso",
    "Contrà Valmerlara": "Contra' Valmerlara",
    "Stradella Fossetta": "Contra' della Fossetta",
    "Viale X Giugno": "Viale Dieci Giugno",
}


def nome_osm(via):
    return SINONIMI.get(via, via)


def scarica_geometrie_vicenza():
    """Scarica tutte le geometry delle vie di Vicenza, con retry sui mirror."""
    query = (
        '[out:json][timeout:180];'
        'area["name"="Vicenza"]["boundary"="administrative"]["admin_level"="8"]->.b;'
        'way["highway"]["name"](area.b);'
        'out geom;'
    )
    for _ in range(4):
        for ep in ENDPOINTS:
            try:
                r = requests.get(ep, params={"data": query}, timeout=200)
                if r.status_code != 200:
                    continue
                data = r.json()
                if "elements" in data:
                    return data["elements"]
            except (requests.RequestException, json.JSONDecodeError):
                continue
        time.sleep(4)
    return None


def main():
    vie = []
    with open("vie.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            vie.append((int(row["zona"]), row["via"]))

    print("Scarico le geometrie delle vie di Vicenza da Overpass...")
    elementi = None
    try:
        with open("vicenza_strade.json", encoding="utf-8") as f:
            elementi_ = json.load(f)
        if isinstance(elementi_, list):
            elementi = elementi_
            print(f"Usate geometrie locali ({len(elementi)} way)")
    except (OSError, json.JSONDecodeError):
        elementi = None

    if elementi is None:
        elementi = scarica_geometrie_vicenza()
        if elementi is not None:
            try:
                with open("vicenza_strade.json", "w", encoding="utf-8") as f:
                    json.dump(elementi, f)
            except OSError:
                pass
    if elementi is None:
        print("ERRORE: impossibile contattare Overpass. Riprova tra poco.")
        print("Comando: ./.venv/bin/python crea_mappa.py")
        raise SystemExit(1)

    # indicizza le geometrie per nome OSM
    per_nome = {}
    for e in elementi:
        n = e.get("tags", {}).get("name")
        g = e.get("geometry")
        if n and g:
            per_nome.setdefault(n, []).append(g)

    mappa = folium.Map(
        location=[45.5470, 11.5460], zoom_start=15,
        tiles="OpenStreetMap",
    )

    non_trovate = []
    disegnate = 0
    for zona, via in vie:
        geoms = per_nome.get(nome_osm(via), [])
        if not geoms:
            non_trovate.append((zona, via))
            print(f"[{zona}] MISS  {via}")
            continue
        for g in geoms:
            coords = [(p["lat"], p["lon"]) for p in g if p]
            if len(coords) < 2:
                continue
            folium.PolyLine(
                coords,
                color=COLORI[zona],
                weight=5,
                opacity=0.9,
                tooltip=f"Zona {zona} - {via}",
            ).add_to(mappa)
        disegnate += 1
        print(f"[{zona}] OK    {via}")

    leggenda_html = """
    <div style="position:fixed; top:10px; right:10px; z-index:9999;
                background:white; padding:10px; border-radius:8px;
                box-shadow:0 0 8px rgba(0,0,0,.3); font-family:sans-serif; font-size:14px;">
      <b>Zona di sosta</b><br>"""
    for zona in sorted(COLORI):
        c = COLORI[zona]
        leggenda_html += (
            f'<span style="display:inline-block;width:14px;height:14px;'
            f'background:{c};border-radius:3px;margin-right:6px;"></span>'
            f'Zona {zona}<br>'
        )
    leggenda_html += "</div>"
    mappa.get_root().html.add_child(folium.Element(leggenda_html))

    mappa.save("mappa.html")
    print(f"\nMappa salvata in mappa.html ({disegnate}/{len(vie)} vie disegnate)")
    if non_trovate:
        print("\nVie NON trovate in OSM (da sistemare):")
        for zona, via in non_trovate:
            print(f"  [zona {zona}] {via}")


if __name__ == "__main__":
    main()
