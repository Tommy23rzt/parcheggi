#!/usr/bin/env python3
import csv
import json
import math
import zipfile
import time

import requests
import folium

# colori spenti per non coprire i nomi delle vie sottostanti
COLORI = {
    1: "#b8565b",
    2: "#3f6f96",
    3: "#4f8a63",
    4: "#c08a3e",
}
SPESSORE = 4
OPACITA = 0.55
ZOOM = 18

# Ritaglio sperimentale: accorcia la via sul tratto dove OpenStreetMap
# mappa la sosta. Disattivato perche' sul campo rende peggio la mappa:
# la zona appartiene alla via intera e i tratti OSM sono incompleti, quindi
# tagliare nasconde metri di sosta che esistono davvero. Con False la mappa
# torna a colorare la via per tutta la sua lunghezza.
RITAGLIA = False
RAGGIO_SOSTA = 20.0
DENSITA_POSTI = 0.2      # posti per metro, densita' tipica di sosta laterale
BANDA = (0.4, 2.5)       # tolleranza: il tratto OSM puo' valere da 0,4x a 2,5x la lunghezza attesa

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
    "Viale Rodolfi": "Viale Ferdinando Rodolfi",
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
    "Contrà Chinotto": "Via Antonio Chinotto",
    "Contrà S. Caterina": "Contra' Santa Caterina",
    "Contrà S. Chiara": "Contra' Santa Chiara",
    "Contrà S. Silvestro": "Contra' San Silvestro",
    "Contrà S. Tomaso": "Contra' San Tomaso",
    "Contrà Valmerlara": "Contra' Valmerlara",
    "Stradella Fossetta": "Stradella della Fossetta",
    "Viale X Giugno": "Viale Dieci Giugno",
}


def nome_osm(via):
    return SINONIMI.get(via, via)


def scarta_omonomi(tratti, distanza_max=800.0):
    """Togli i tratti che sono omonimi lontani dal resto della via.

    OSM ha piu' strade con lo stesso nome in punti diversi della
    provincia. Una via intera e' un unico percorso: se un pezzo sta a
    chilometri di distanza dagli altri pezzi, non e' la stessa strada
    che chiede la tabella. Per esempio "Via Quattro Novembre" (la
    Zona 3 "Via IV Novembre") ha 6 tratti nel centro e uno a 5,9 km,
    che e' un'altra via omonima.
    """
    if len(tratti) < 2:
        return tratti, []
    tenuti = []
    scartati = []
    for i, t in enumerate(tratti):
        vicino = False
        for j, u in enumerate(tratti):
            if i == j:
                continue
            if any(distanza_punto_seg(p, a, b) <= distanza_max
                   for p in t for a, b in zip(u, u[1:])):
                vicino = True
                break
        (tenuti if vicino else scartati).append(t)
    return (tenuti, scartati) if tenuti else (tratti, [])


def scarica_sosta_vicenza():
    """Scarica le aree di sosta mappate in OSM (servono a ritagliare le vie)."""
    query = (
        '[out:json][timeout:180];'
        'area["name"="Vicenza"]["boundary"="administrative"]["admin_level"="8"]->.b;'
        '(way["amenity"="parking"](area.b);'
        'way["highway"]["parking:street"](area.b););'
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


def carica_json(nome_file, scarica, etichetta):
    """Usa la cache locale, scarica solo se manca. Ritorna None se impossibile."""
    try:
        with open(nome_file, encoding="utf-8") as f:
            dati = json.load(f)
        if isinstance(dati, list):
            print(f"  cache locale: {len(dati)} {etichetta}")
            return dati
    except (OSError, json.JSONDecodeError):
        pass
    print(f"  scarico {etichetta} da Overpass...")
    dati = scarica()
    if dati is not None:
        try:
            with open(nome_file, "w", encoding="utf-8") as f:
                json.dump(dati, f)
        except OSError:
            pass
        print(f"  scaricati {len(dati)} {etichetta}")
    return dati


def distanza_punto_seg(p, a, b):
    """Distanza in metri dal punto p al segmento a-b, su piano locale."""
    lat0 = math.radians((a[0] + b[0]) / 2)
    kx = 111320 * math.cos(lat0)
    ky = 110540
    px, py = p[1] * kx, p[0] * ky
    ax, ay = a[1] * kx, a[0] * ky
    bx, by = b[1] * kx, b[0] * ky
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def indice_sosta(elementi, raggio):
    """Prepara i segmenti di sosta con bounding box, per filtri veloci."""
    out = []
    for e in elementi:
        pts = [(p["lat"], p["lon"]) for p in e.get("geometry") or [] if p]
        if len(pts) < 2:
            continue
        lat = [p[0] for p in pts]
        lon = [p[1] for p in pts]
        # il bbox e' in gradi, il raggio in metri: margine approssimato
        margine = raggio / 100000.0
        out.append({
            "segs": list(zip(pts, pts[1:])),
            "bbox": (min(lat) - margine, max(lat) + margine,
                     min(lon) - margine, max(lon) + margine),
        })
    return out


def lunghezza_m(a, b):
    """Distanza approssimata in metri fra due punti (lat, lon)."""
    lat0 = math.radians((a[0] + b[0]) / 2)
    dx = (b[1] - a[1]) * 111320 * math.cos(lat0)
    dy = (b[0] - a[0]) * 110540
    return math.hypot(dx, dy)


def lunghezza_poly(pts):
    """Lunghezza in metri di una polilinea."""
    return sum(lunghezza_m(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def ritaglia(coords, soste, raggio, passo_m=8.0):
    """Restituisce i tratti di coords che sono effettivamente coperti da sosta OSM.

    coords e' una lista di (lat, lon). Non inventa nulla: se OSM non ha sosta
    lungo la via, il tratto viene restituito intero cosi com'e'.
    """
    if len(coords) < 2:
        return [coords], 0.0
    campionati = []
    for i in range(len(coords) - 1):
        a, b = coords[i], coords[i + 1]
        n = max(2, int(lunghezza_m(a, b) / passo_m) + 1)
        for k in range(n):
            f = k / n
            campionati.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
    campionati.append(coords[-1])

    coperti = []
    for p in campionati:
        ok = False
        for s in soste:
            bb = s["bbox"]
            if not (bb[0] <= p[0] <= bb[1] and bb[2] <= p[1] <= bb[3]):
                continue
            for sa, sb in s["segs"]:
                if distanza_punto_seg(p, sa, sb) <= raggio:
                    ok = True
                    break
            if ok:
                break
        coperti.append(ok)

    if not any(coperti):
        return [coords], 0.0
    frazione = sum(coperti) / len(coperti)
    if frazione >= 0.90:
        return [coords], frazione

    # ricostruisce i tratti coperti, con i punti di confine come estremi
    tratti = []
    corrente = []
    for p, ok in zip(campionati, coperti):
        if ok:
            corrente.append(p)
        elif corrente:
            if len(corrente) >= 2:
                tratti.append(corrente)
            corrente = []
    if len(corrente) >= 2:
        tratti.append(corrente)
    return tratti, frazione


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
            vie.append((int(row["zona"]), row["via"].strip()))

    posti = {}
    try:
        with open("posti.csv", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                posti[(int(row["zona"]), row["via"].strip())] = row["posti"]
    except OSError:
        pass

    print("Geometrie delle vie di Vicenza:")
    elementi = carica_json("vicenza_strade.json", scarica_geometrie_vicenza,
                           "way di strade")
    if elementi is None:
        print("ERRORE: impossibile contattare Overpass. Riprova tra poco.")
        print("Comando: ./.venv/bin/python crea_mappa.py")
        raise SystemExit(1)

    soste = []
    if RITAGLIA:
        print("Aree di sosta (per ritagliare le vie dove i posti sono effettivi):")
        elementi_sosta = carica_json("vicenza_sosta.json", scarica_sosta_vicenza,
                                     "aree di sosta")
        if elementi_sosta:
            soste = indice_sosta(elementi_sosta, RAGGIO_SOSTA)

    # indicizza le geometrie per nome OSM
    per_nome = {}
    for e in elementi:
        n = e.get("tags", {}).get("name")
        g = e.get("geometry")
        if n and g:
            per_nome.setdefault(n, []).append(g)

    mappa = folium.Map(
        location=[45.5470, 11.5460], zoom_start=ZOOM,
        tiles="OpenStreetMap",
    )

    non_trovate = []
    ritagliate = []
    scartate = []
    scartate_omonimi = []
    esporta = []
    for zona, via in vie:
        geoms = per_nome.get(nome_osm(via), [])
        if not geoms:
            non_trovate.append((zona, via))
            print(f"[{zona}] MISS  {via}")
            continue
        vie_disegnate = [g for g in geoms if len(g) >= 2]
        vie_disegnate = [[(p["lat"], p["lon"]) for p in g if p]
                         for g in vie_disegnate]
        vie_disegnate, omonimi = scarta_omonomi(vie_disegnate)
        if omonimi:
            scartate_omonimi.append((zona, via, len(omonimi)))

        accettato = False
        coperta = 0.0
        tratti_osm = []
        if soste:
            # lunghezza che OSM dice effettivamente occupata da sosta
            for coords in vie_disegnate:
                tratti, frazione = ritaglia(coords, soste, RAGGIO_SOSTA)
                tratti_osm.append((coords, tratti, frazione))
            for coords, tratti, frazione in tratti_osm:
                if frazione >= 0.90:
                    coperta += lunghezza_poly(coords)
                elif 0 < frazione < 0.90:
                    coperta += sum(lunghezza_poly(t) for t in tratti)

            # la geometria OSM e' accettata solo se i posti ufficiali la confermano
            try:
                attesa = int(posti.get((zona, via), 0)) / DENSITA_POSTI
            except ValueError:
                attesa = 0.0
            if coperta > 0 and BANDA[0] * attesa <= coperta <= BANDA[1] * attesa:
                accettato = True
        else:
            for coords in vie_disegnate:
                tratti_osm.append((coords, None, 0.0))

        nota = ""
        if accettato:
            ritagliate.append(via)
            nota = f" - tratto con sosta ({coperta:.0f} m)"
        elif coperta > 0:
            scartate.append(via)

        n_posti = posti.get((zona, via), "")
        for coords, tratti, frazione in tratti_osm:
            if accettato:
                if frazione <= 0:
                    continue          # questo tratto non ha sosta OSM: non si disegna
                da_disegnare = tratti if frazione < 0.90 else [coords]
            else:
                da_disegnare = [coords]
            for t in da_disegnare:
                if len(t) < 2:
                    continue
                folium.PolyLine(
                    t,
                    color=COLORI[zona],
                    weight=SPESSORE,
                    opacity=OPACITA,
                    tooltip=(f"Zona {zona} - {via}"
                             + (f" - {n_posti} posti" if n_posti != "" else "")
                             + nota),
                ).add_to(mappa)
                esporta.append((zona, via, t, n_posti))
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
            f'background:{c};opacity:{OPACITA};border-radius:3px;'
            f'margin-right:6px;"></span>'
            f'Zona {zona}<br>'
        )
    if RITAGLIA:
        leggenda_html += (
            f'<div style="margin-top:6px;color:#666;font-size:12px;max-width:190px;">'
            f'La linea copre solo i tratti dove la sosta e\' documentata '
            f'in OpenStreetMap.</div>'
        )
    else:
        leggenda_html += (
            f'<div style="margin-top:6px;color:#666;font-size:12px;max-width:190px;">'
            f'Il colore indica la zona di sosta della via, per tutta la sua '
            f'lunghezza. Il numero nel riquadro e\' il totale dei posti.</div>'
        )
    leggenda_html += "</div>"
    mappa.get_root().html.add_child(folium.Element(leggenda_html))

    mappa.save("mappa.html")
    print(f"\nMappa salvata in mappa.html ({len(vie) - len(non_trovate)}/{len(vie)} vie)")
    esporta_kml_gpx(esporta)
    print(f"Ritagliate su tratto confermato dai posti ({len(ritagliate)}): "
          + ", ".join(ritagliate))
    if scartate:
        print(f"\nOSM mappa la sosta ma i posti non confermano il tratto, "
              f"via intera ({len(scartate)}): " + ", ".join(scartate))
    if scartate_omonimi:
        print("\nScartati tratti omonimi troppo lontani dalla via:")
        for zona, via, n in scartate_omonimi:
            print(f"  [zona {zona}] {via}: {n} tratto/i scartato/i")
    if non_trovate:
        print("\nVie NON trovate in OSM (da sistemare):")
        for zona, via in non_trovate:
            print(f"  [zona {zona}] {via}")


def esporta_kml_gpx(tratti):
    """Salva gli stessi tratti della mappa in KML e GPX.

    Il KML si carica su Google My Maps e mantiene i colori per zona;
    il GPX serve su OsmAnd e Organic Maps. Non servono librerie
    esterne: entrambi i formati sono XML scritto a mano.
    """
    from xml.sax.saxutils import escape

    def kml_colore(hexcolore):
        # KML vuole aabbggrr, quindi RGB rovesciato
        r, g, b = (hexcolore[i:i + 2] for i in (1, 3, 5))
        return f"ff{b}{g}{r}"

    # visibility 0 sull'icona: senza questo ogni LineString fa comparire
    # un pin predefinito, e con oltre 250 segmenti i pin coprono la mappa
    # nell'app Google Maps.
    stili = "".join(
        f'<Style id="zona{z}">'
        f'<IconStyle><visibility>0</visibility></IconStyle>'
        f'<LineStyle>'
        f'<color>{kml_colore(c)}</color><width>5</width>'
        f'</LineStyle></Style>'
        for z, c in sorted(COLORI.items())
    )

    # Un Placemark per segmento, come nella versione già verificata:
    # la guida Google elenca i MultiGeometries fra i dati che un KML può
    # perdere in import, e se My Maps li ignora le spezzature sparirebbero
    # senza avviso.
    placemark = []
    for zona, via, coords, n_posti in tratti:
        punti = " ".join(f"{lon},{lat},0" for lat, lon in coords)
        desc = f"Zona {zona}"
        if n_posti != "":
            desc += f" - {n_posti} posti"
        placemark.append(
            f'<Placemark><name>{escape(via)}</name>'
            f'<description>{escape(desc)}</description>'
            f'<styleUrl>#zona{zona}</styleUrl>'
            f'<LineString><tessellate>1</tessellate>'
            f'<coordinates>{punti}</coordinates></LineString></Placemark>'
        )

    with open("zone_sosta.kml", "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
                '<name>Zone di sosta Vicenza</name>'
                + stili + "".join(placemark) + '</Document></kml>\n')

    # KMZ = KML compresso. Google My Maps accetta entrambi, ma il KML
    # arriva dal browser come testo e il telefono lo apre a schermo
    # invece di scaricarlo, mentre il KMZ viene sempre scaricato.
    with zipfile.ZipFile("zone_sosta.kmz", "w", zipfile.ZIP_DEFLATED) as z:
        z.write("zone_sosta.kml", "doc.kml")

    with open("zone_sosta.gpx", "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<gpx version="1.1" creator="crea_mappa.py" '
                'xmlns="http://www.topografix.com/GPX/1/1">\n')
        for zona, via, coords, n_posti in tratti:
            f.write(f'  <trk><name>{escape(f"Zona {zona} - {via}")}</name>'
                    '<trkseg>\n')
            for lat, lon in coords:
                f.write(f'    <trkpt lat="{lat}" lon="{lon}"/>\n')
            f.write('  </trkseg></trk>\n')
        f.write('</gpx>\n')

    print(f"Esportati {len(tratti)} tratti in zone_sosta.kml, "
          f"zone_sosta.kmz e zone_sosta.gpx")


if __name__ == "__main__":
    main()
