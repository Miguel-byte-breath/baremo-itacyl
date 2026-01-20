from http.server import BaseHTTPRequestHandler
import json
import pandas as pd
import io

def motor_baremacion_itacyl(row):
    """
    MOTOR DE BAREMACIÓN AGRONÓMICA - ESCENARIO A
    Versión 1.3.9 | Filtro Selectivo por Composición (34.5/35 N)
    """
    # 0. PREPROCESAMIENTO
    nombre_raw = str(row.get('name', '')).strip()
    if not nombre_raw or nombre_raw.lower() == 'nan': 
        nombre_raw = "PRODUCTO SIN NOMBRE"
    
    nombre = nombre_raw.upper()
    nombre_protegido = f"'{nombre_raw}"

    def clean(val):
        if pd.isna(val) or val is None: return 0.0
        try: 
            if isinstance(val, str): val = val.replace(',', '.')
            return float(val)
        except: return 0.0

    # Carga de variables analíticas
    n = clean(row.get('n'))
    p = clean(row.get('p2o5'))
    k = clean(row.get('k2o'))
    n_nitrico = clean(row.get('nitricN'))
    n_amoniacal = clean(row.get('ammoniacalN'))
    om = clean(row.get('organicMatter'))
    azufre = clean(row.get('s'))
    siex_id = clean(row.get('materialSiexId'))

    # 1. CÁLCULO DEL ÍNDICE DE SALINIDAD (IS_v)
    IS_v = 0
    
    # EXCEPCIÓN A: Orgánicos y Enmiendas
    if any(kw in nombre for kw in ["COMPOST", "ESTIERCOL", "HUMUS", "ORGANIC"]):
        IS_v = 15
    
    # EXCEPCIÓN B: Nitratos Potásicos (Valor Tabulado 74)
    elif any(kw in nombre for kw in ["NITRATO POTASICO", "NIPO", "TECNOPLUS"]):
        IS_v = 74

    # EXCEPCIÓN C: NITRATO AMÓNICO PURO (Filtro por Nombre + Composición)
    # Solo si el nombre contiene la clave Y el nitrógeno es 34.5 o 35
    elif ("NITRATO AMONICO" in nombre or "NAC" in nombre) and (n == 34.5 or n == 35.0):
        IS_v = 104

    # PARA TODO LO DEMÁS (MINACTIV, KSC, ETC.): Cálculo por Rader
    if IS_v == 0:
        # Los MINACTIV (N=0) entrarán aquí y darán un valor bajo (aprox. 27)
        calc_rader = (n * 1.65) + (p * 0.5) + (k * 1.9)
        IS_v = int(round(min(max(calc_rader, 5), 140)))

    # 2. CLASIFICACIÓN TÉCNICA
    siex_e_ids = [1, 2, 3, 4, 5, 6, 7, 8, 10, 13, 19, 20, 21, 22]
    es_enm = (not pd.isna(row.get('yearPercent1'))) or (siex_id in siex_e_ids)
    es_cob = row.get('topDressing') is True
    is_liq = row.get('aggregateState') == 'L' or "SOLUB" in nombre
    
    if es_enm: tipo = "[E]"
    elif es_cob: tipo = "[C,R]" if is_liq else "[C]"
    else: tipo = "[R]" if is_liq else "[F]"

    # 3. BAREMACIÓN (10,0 Automático para Tecnologías o Enmiendas)
    kw_inh = ["DMPP", "NBPT", "INHIBIDOR", "NOVATEC", "ENTEC", "NEXUR"]
    es_tec = row.get('nitrificationInhibitor') is True or row.get('ureaseInhibitor') is True
    
    if es_enm or es_tec or any(kw in nombre for kw in kw_inh):
        return nombre_protegido, tipo, "Bajo", IS_v, "10,0"

    # Lógica acumulativa
    baremo = 6.0
    if om > 20: baremo += 3.0
    if azufre > 2 or n_amoniacal > 10: baremo += 2.0
    
    tiene_micros = any(clean(row.get(m)) > 0 for m in ['fe','zn','mn','cu','b','mo','mg'])
    if not tiene_micros and any(kw in nombre for kw in ["QUELAT", "MICROS", "MG"]):
        tiene_micros = True
    if tiene_micros: baremo += 1.5

    if p > 15: baremo += 1.0
    if k > 15: baremo += 1.0

    # 4. PENALIZACIONES
    val_n = n if (not es_cob and not es_enm) else n_nitrico
    riesgo = "Bajo"
    if 10 <= val_n <= 20: 
        baremo -= 1.5
        riesgo = "Medio"
    elif val_n > 20: 
        baremo -= 3.0
        riesgo = "Alto"

    # Riesgo Salinidad
    if IS_v < 20: baremo += 1.5
    elif 20 <= IS_v < 40: baremo += 0.5
    elif 60 < IS_v <= 80: baremo -= 0.5
    elif 80 < IS_v <= 100: baremo -= 1.5
    elif IS_v > 100: baremo -= 3.0

    final_score = round(min(max(baremo, 1.0), 10.0), 1)
    return nombre_protegido, tipo, riesgo, IS_v, str(final_score).replace('.', ',')

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            raw_json = json.loads(post_data)
            items = raw_json['items'] if isinstance(raw_json, dict) and 'items' in raw_json else raw_json
            df = pd.DataFrame(items)
            res_df = df.apply(lambda r: pd.Series(motor_baremacion_itacyl(r.to_dict())), axis=1)
            res_df.columns = ['name', 'Tipo', 'Riesgo', 'IS_valor', 'Baremo']
            output = io.BytesIO()
            res_df.to_csv(output, index=False, sep=';', decimal=',', encoding='utf-8-sig')
            self.send_response(200)
            self.send_header('Content-type', 'text/csv; charset=utf-8-sig')
            self.send_header('Content-Disposition', 'attachment; filename="baremo.csv"')
            self.end_headers()
            self.wfile.write(output.getvalue())
        except Exception as e:
            self.send_response(200)
            self.send_header('Content-type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(f"ERROR: {str(e)}".encode('utf-8'))
