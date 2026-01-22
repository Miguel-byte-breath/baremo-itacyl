from http.server import BaseHTTPRequestHandler
import json
import pandas as pd
import io
import re

def motor_baremacion_itacyl(row):
    """
    SISTEMA DE BAREMACIÓN AGRONÓMICA AUTOMATIZADO - Versión 1.5.0 (Consolidada Final)
    Fecha: 21/01/2026 | Escenario A: Suelos Francos y Arcillosos
    
    FIXES:
    1. Nitratos/Tecnoplus: Protección 9,5 (Bypass de símbolos ®).
    2. IS: Excepción Nitramon/Nitrosulf (Umbral n > 33).
    3. Encoding: Limpieza de Ã¡ y símbolos especiales.
    """
    
    # -------------------------------------------------------------------------
    # FASE 0: PREPROCESAMIENTO Y LIMPIEZA SEMÁNTICA
    # -------------------------------------------------------------------------
    def fix_encoding(text):
        try:
            # Repara caracteres rotos comunes (Ã¡ -> á)
            return text.encode('latin-1').decode('utf-8')
        except:
            return text

    nombre_raw = fix_encoding(str(row.get('name', '')).strip())
    if not nombre_raw or nombre_raw.lower() == 'nan':
        nombre_raw = "PRODUCTO SIN NOMBRE"
    
    # nombre_search: Variable limpia para búsquedas (sin símbolos ® o ™)
    nombre = nombre_raw.upper().replace('®', '').replace('™', '').replace('©', '')
    nombre_protegido = f"'{nombre_raw}" # Formato para Excel

    def clean(val):
        if pd.isna(val) or val is None: return 0.0
        try:
            if isinstance(val, str): val = val.replace(',', '.')
            return float(val)
        except: return 0.0

    # Carga de variables analíticas
    n = clean(row.get('n'))
    p2o5 = clean(row.get('p2o5'))
    k2o = clean(row.get('k2o'))
    nitricN = clean(row.get('nitricN'))
    ammoniacalN = clean(row.get('ammoniacalN'))
    organicMatter = clean(row.get('organicMatter'))
    s = clean(row.get('s'))
    materialSiexId = clean(row.get('materialSiexId'))
    
    micros_vals = {
        'fe': clean(row.get('fe')), 'zn': clean(row.get('zn')),
        'mn': clean(row.get('mn')), 'cu': clean(row.get('cu')),
        'b': clean(row.get('b')), 'mo': clean(row.get('mo')),
        'mg': clean(row.get('mg'))
    }

    # -------------------------------------------------------------------------
    # FASE I: CÁLCULO DEL ÍNDICE DE SALINIDAD (IS_v)
    # -------------------------------------------------------------------------
    def calcular_is():
        # Excepción Nitramon/Nitrosulf
        es_excepcion_marca = any(k in nombre for k in ["NITRAMON", "NITROSULF"])
        
        if any(k in nombre for k in ["NITRATO POTASICO", "NIPO", "TECNOPLUS"]): return 74
        
        # Umbral n > 33 protege al NAC 27 (Nitramon)
        if not es_excepcion_marca:
            if ("NITRATO AMONICO" in nombre or "NAC" in nombre) and n > 33: return 104
            
        if "UREA" in nombre: return 75
        if any(k in nombre for k in ["NITRATO DE CALCIO", "CALCINIT", "CALCILIQ"]): return 65
        if "SULFATO POTASICO" in nombre or "SOP" in nombre: return 46
        if "SULFATO AMONICO" in nombre: return 69
        if "CLORURO" in nombre: return 116
        if "DAP" in nombre: return 34
        if "MAP" in nombre: return 30
        
        calc = (n * 1.65) + (p2o5 * 0.5) + (k2o * 1.9)
        return int(round(min(max(calc, 5), 140)))

    IS_v = calcular_is()

    # -------------------------------------------------------------------------
    # FASE II: CLASIFICACIÓN DE USO
    # -------------------------------------------------------------------------
    siex_e_directos = [1, 2, 3, 4, 5, 6, 7, 8, 10, 13, 19, 20, 21, 22]
    has_min = not pd.isna(row.get('yearPercent1'))
    is_siex_e = materialSiexId in siex_e_directos
    
    es_enm = has_min or is_siex_e
    es_cob = row.get('topDressing') is True
    es_riego = row.get('diluted') is True or row.get('aggregateState') == 'L' or "SOLUB" in nombre

    if es_enm: tipo = "[E]"
    elif es_cob: tipo = "[C,R]" if es_riego else "[C]"
    else: tipo = "[R]" if es_riego else "[F]"

    # -------------------------------------------------------------------------
    # FASE III: BAREMO - BYPASS DE EXCELENCIA E INHIBIDORES (10,0)
    # -------------------------------------------------------------------------
    kw_inh = ["DMPP", "NBPT", "INHIBIDOR", "ESTABILIZADO", "NOVATEC", "ENTEC", "NEXUR", "RHIZOVIT", "EXCELIS"]
    if es_enm or row.get('nitrificationInhibitor') or row.get('ureaseInhibitor') or any(k in nombre for k in kw_inh):
        return nombre_protegido, tipo, "Bajo", IS_v, "10,0"

    # FIX CRÍTICO: PROTECCIÓN NITRATOS DE CALCIO Y TECNOPLUS (9,5)
    # Buscamos en 'nombre' (que ya no tiene símbolos ®)
    kw_calcio = ["NITRATO DE CALCIO", "CALCINIT", "CALCILIQ", "TECNOPLUS", "SOLUTECK"]
    if any(k in nombre for k in kw_calcio) and tipo != "[F]":
        return nombre_protegido, tipo, "Medio", IS_v, "9,5"

    # -------------------------------------------------------------------------
    # FASE IV: LÓGICA ACUMULATIVA (Base 6.0)
    # -------------------------------------------------------------------------
    baremo = 6.0
    if organicMatter > 20: baremo += 3.0
    if s > 2 or ammoniacalN > 10: baremo += 2.0
    
    has_mic = any(v > 0 for v in micros_vals.values()) or any(k in nombre for k in ["QUELAT", "MICROS", "MG"])
    if has_mic: baremo += 1.5
    if p2o5 > 7: baremo += 1.0
    if k2o > 7: baremo += 1.0

    # -------------------------------------------------------------------------
    # FASE V: PENALIZACIONES
    # -------------------------------------------------------------------------
    val_n_eval = n if tipo == "[F]" else nitricN
    riesgo = "Bajo"
    if 10 <= val_n_eval <= 20:
        baremo -= 1.5
        riesgo = "Medio"
    elif val_n_eval > 20:
        baremo -= 3.0
        riesgo = "Alto"

    if IS_v < 20: baremo += 1.5
    elif 20 <= IS_v < 40: baremo += 0.5
    elif 60 < IS_v <= 80: baremo -= 0.5
    elif 80 < IS_v <= 100: baremo -= 1.5
    elif IS_v > 100: baremo -= 3.0

    final = round(min(max(baremo, 1.0), 10.0), 1)
    return nombre_protegido, tipo, riesgo, IS_v, str(final).replace('.', ',')

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
            self.send_header('Content-Disposition', 'attachment; filename="baremo_v150_consolidado.csv"')
            self.end_headers()
            self.wfile.write(output.getvalue())
            
        except Exception as e:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(f"ERROR: {str(e)}".encode('utf-8'))
