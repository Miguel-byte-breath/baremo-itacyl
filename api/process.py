from http.server import BaseHTTPRequestHandler
import json
import pandas as pd
import io

def motor_baremacion_itacyl(row):
    """
    MOTOR DE BAREMACIÓN AGRONÓMICA - ESCENARIO A
    Versión 1.3.9 | SOLUCIÓN RADICAL DE TIPADO
    """
    # 0. LIMPIEZA AGRESIVA DE DATOS (Asegura que sean números)
    def to_float(val):
        if pd.isna(val) or val is None: return 0.0
        try:
            # Elimina espacios y cambia comas por puntos antes de convertir
            s_val = str(val).replace(',', '.').strip()
            return float(s_val)
        except: return 0.0

    # Extraemos y convertimos CADA valor antes de empezar
    n = to_float(row.get('n'))
    p = to_float(row.get('p2o5'))
    k = to_float(row.get('k2o'))
    n_nit = to_float(row.get('nitricN'))
    n_amo = to_float(row.get('ammoniacalN'))
    mo = to_float(row.get('organicMatter'))
    s = to_float(row.get('s'))
    siex = to_float(row.get('materialSiexId'))
    
    nombre_raw = str(row.get('name', '')).strip()
    nombre = nombre_raw.upper()
    nombre_protegido = f"'{nombre_raw}"

    # 1. CÁLCULO DEL ÍNDICE DE SALINIDAD (IS_v)
    IS_v = 0
    
    # Prioridad A: Identificación por nombre (Búsqueda por contenido)
    if any(kw in nombre for kw in ["COMPOST", "ESTIERCOL", "HUMUS", "ORGANIC"]):
        IS_v = 15
    elif any(kw in nombre for kw in ["NITRATO POTASICO", "NIPO", "TECNOPLUS"]):
        IS_v = 74
    
    # Prioridad B: NITRATO AMÓNICO PURO (Solo si tiene Nitrógeno alto)
    # Si el producto tiene N=0 (como los MINACTIV de la imagen), esta línea se ignora
    elif ("NITRATO AMONICO" in nombre or "NAC" in nombre) and n > 25:
        IS_v = 104

    # Prioridad C: TODO LO DEMÁS (Incluso si se llama Nitramon o Nitrosulf pero tiene N bajo)
    if IS_v == 0:
        # Aquí entrarán los MINACTIV (0-15-10) y KSC II (N=0)
        IS_v = int(round((n * 1.65) + (p * 0.5) + (k * 1.9)))
        # Seguridad: nunca por debajo de 5 ni por encima de 140
        IS_v = min(max(IS_v, 5), 140)

    # 2. CLASIFICACIÓN TÉCNICA
    siex_e_ids = [1, 2, 3, 4, 5, 6, 7, 8, 10, 13, 19, 20, 21, 22]
    has_min = row.get('yearPercent1') is not None and not pd.isna(row.get('yearPercent1'))
    es_enm = has_min or (siex in siex_e_ids)
    es_cob = row.get('topDressing') is True
    is_liq = row.get('aggregateState') == 'L' or "SOLUB" in nombre
    
    if es_enm: tipo = "[E]"
    elif es_cob: tipo = "[C,R]" if is_liq else "[C]"
    else: tipo = "[R]" if is_liq else "[F]"

    # 3. BAREMO (10,0 Automático para Tecnologías)
    kw_inh = ["DMPP", "NBPT", "INHIBIDOR", "NOVATEC", "ENTEC", "NEXUR"]
    es_tec = row.get('nitrificationInhibitor') is True or row.get('ureaseInhibitor') is True
    
    if es_enm or es_tec or any(kw in nombre for kw in kw_inh):
        return nombre_protegido, tipo, "Bajo", IS_v, "10,0"

    # Algoritmo Acumulativo
    puntos = 6.0
    if mo > 20: puntos += 3.0
    if s > 2 or n_amo > 10: puntos += 2.0
    
    # Micros (Búsqueda en columnas y nombre)
    has_mic = any(to_float(row.get(m)) > 0 for m in ['fe','zn','mn','cu','b','mo','mg'])
    if not has_mic and any(kw in nombre for kw in ["QUELAT", "MICROS", "MG"]):
        has_mic = True
    if has_mic: puntos += 1.5

    if p > 15: puntos += 1.0
    if k > 15: puntos += 1.0

    # 4. PENALIZACIONES
    val_n_final = n if (not es_cob and not es_enm) else n_nit
    riesgo = "Bajo"
    if 10 <= val_n_final <= 20: 
        puntos -= 1.5
        riesgo = "Medio"
    elif val_n_final > 20: 
        puntos -= 3.0
        riesgo = "Alto"

    # Impacto Salinidad en Nota
    if IS_v < 20: puntos += 1.5
    elif 20 <= IS_v < 40: puntos += 0.5
    elif 60 < IS_v <= 80: puntos -= 0.5
    elif 80 < IS_v <= 100: puntos -= 1.5
    elif IS_v > 100: puntos -= 3.0

    final = round(min(max(puntos, 1.0), 10.0), 1)
    return nombre_protegido, tipo, riesgo, IS_v, str(final).replace('.', ',')

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            raw_json = json.loads(post_data)
            items = raw_json['items'] if isinstance(raw_json, dict) and 'items' in raw_json else raw_json
            df = pd.DataFrame(items)
            
            # Procesamos forzando que no se arrastren estados
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
            self.end_headers()
            self.wfile.write(f"ERROR: {str(e)}".encode('utf-8'))
