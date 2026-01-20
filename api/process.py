from http.server import BaseHTTPRequestHandler
import json
import pandas as pd
import io
import re
import csv

def motor_baremacion_itacyl(row):
    """
    MOTOR DE BAREMACIÓN AGRONÓMICA - ESCENARIO A
    Versión 1.3.1 FINAL | Auditoría ITACyL
    Protección Anti-Excel (Apóstrofo) y Lógica SIEX 1.3.1
    """
    # 0. PREPROCESAMIENTO Y PROTECCIÓN DE INTEGRIDAD
    nombre_raw = str(row.get('name', '')).strip()
    if not nombre_raw or nombre_raw.lower() == 'nan': 
        nombre_raw = "PRODUCTO SIN NOMBRE"
    nombre = nombre_raw.upper()
    
    # PROTECCIÓN EXCEL: Forzamos formato texto con el apóstrofo (')
    nombre_protegido = f"'{nombre_raw}"

    def clean(val):
        if pd.isna(val) or val is None: return 0.0
        try: return float(val)
        except: return 0.0

    # Carga de variables analíticas primarias
    n, p2o5, k2o = clean(row.get('n')), clean(row.get('p2o5')), clean(row.get('k2o'))
    nitricN, ammoniacalN = clean(row.get('nitricN')), clean(row.get('ammoniacalN'))
    organicMatter, s = clean(row.get('organicMatter')), clean(row.get('s'))
    materialSiexId = clean(row.get('materialSiexId')) 

    micros_vals = {
        'fe': clean(row.get('fe')), 'zn': clean(row.get('zn')), 
        'mn': clean(row.get('mn')), 'cu': clean(row.get('cu')), 
        'b': clean(row.get('b')),   'mo': clean(row.get('mo')),
        'mg': clean(row.get('mg'))
    }

    # 1. ÍNDICE DE SALINIDAD (IS_v) - VALORES FIJOS Y FÓRMULA RADER
    def calcular_is(r):
        if any(k in nombre for k in ["COMPOST", "ESTIERCOL", "HUMUS", "ORGANIC"]): return 15
        if "NITRATO AMONICO" in nombre or "NAC" in nombre: return 104
        if "UREA" in nombre: return 75
        if any(k in nombre for k in ["NITRATO DE CALCIO", "CALCINIT"]): return 85
        if "NITRATO DE POTASIO" in nombre: return 74
        if "SULFATO POTASICO" in nombre or "SOP" in nombre: return 46
        if "SULFATO AMONICO" in nombre: return 69
        if "CLORURO" in nombre: return 116
        if "DAP" in nombre: return 34
        if "MAP" in nombre: return 30
        
        calc = (n * 1.65) + (p2o5 * 0.5) + (k2o * 1.9)
        return int(round(min(max(calc, 5), 140)))

    IS_v = calcular_is(row)

    # 2. CLASIFICACIÓN TÉCNICA Y NOTAS FIJAS
    # IDs SIEX autorizados para categoría [E] de forma directa
    siex_e_directos = [1, 2, 3, 4, 5, 6, 7, 8, 10, 13, 19, 20, 21, 22]
    
    # Criterio de Enmienda [E]: 
    # Requiere dato de mineralización (yearPercent1) O estar en la lista directa.
    # Los códigos 15 y 16 (abonos orgánicos/organominerales) requieren yearPercent1.
    has_min = not pd.isna(row.get('yearPercent1'))
    is_siex_e = materialSiexId in siex_e_directos
    
    es_enm = has_min or is_siex_e
    es_cob = row.get('topDressing') is True
    is_liq = row.get('aggregateState') == 'L' or "SOLUB" in nombre
    
    if es_enm: tipo = "[E]"
    elif any(k in nombre for k in ["NITRATO DE CALCIO", "CALCINIT", "SOLUTECK"]): tipo = "[C,R]"
    elif es_cob: tipo = "[C,R]" if is_liq else "[C]"
    else: tipo = "[R]" if is_liq else "[F]"

    # Tecnologías de Estabilización
    kw_inh = ["DMPP", "NBPT", "INHIBIDOR", "ESTABILIZADO", "NOVATEC", "ENTEC", "NEXUR"]
    es_tec = row.get('nitrificationInhibitor') is True or row.get('ureaseInhibitor') is True
    
    if es_enm or es_tec or any(k in nombre for k in kw_inh):
        return nombre_protegido, tipo, "Bajo", IS_v, "10,0"
    
    if tipo == "[C,R]" and any(k in nombre for k in ["NITRATO DE CALCIO", "SOLUTECK", "CALCINIT"]):
        return nombre_protegido, tipo, "Medio", IS_v, "9,5"

    # 3. ALGORITMO ACUMULATIVO
    baremo = 6.0
    if organicMatter > 20: baremo += 3.0
    if s > 2 or ammoniacalN > 10: baremo += 2.0
    
    tiene_micros = any(v > 0 for v in micros_vals.values())
    if not tiene_micros:
        kw_mic = ["QUELAT", "MICROS", "BORO", "ZINC", "HIERRO", "MANGANESO", "MAGNESIO", "MG"]
        tiene_micros = any(k in nombre for k in kw_mic)
    if tiene_micros: baremo += 1.5

    npk_match = re.search(r'(\d+)-(\d+)-(\d+)', nombre)
    if p2o5 > 15: baremo += 1.0
    elif p2o5 == 0 and npk_match and float(npk_match.group(2)) > 15: baremo += 1.0
    
    if k2o > 15: baremo += 1.0
    elif k2o == 0 and npk_match and float(npk_match.group(3)) > 15: baremo += 1.0

    # 4. PENALIZACIONES (ZVN y Salinidad)
    es_fondo = (not es_cob) and (not es_enm)
    val_n_eval = n if es_fondo else nitricN
    
    riesgo = "Bajo"
    if 10 <= val_n_eval <= 20: 
        baremo -= 1.5
        riesgo = "Medio"
    elif val_n_eval > 20: 
        baremo -= 3.0
        riesgo = "Alto"

    if IS_v < 20: baremo += 1.5
    elif 20 <= IS_v < 40: baremo += 0.5
    elif 40 <= IS_v <= 60: baremo += 0.0
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
            
            if isinstance(raw_json, dict) and 'items' in raw_json: lista = raw_json['items']
            elif isinstance(raw_json, list): lista = raw_json
            else: lista = [raw_json]

            df = pd.DataFrame(lista)
            res_df = df.apply(lambda r: pd.Series(motor_baremacion_itacyl(r)), axis=1)
            res_df.columns = ['name', 'Tipo', 'Riesgo', 'IS_valor', 'Baremo']
            
            output = io.BytesIO()
            res_df.to_csv(output, index=False, sep=';', decimal=',', encoding='utf-8-sig')
            
            self.send_response(200)
            self.send_header('Content-type', 'text/csv; charset=utf-8-sig')
            self.send_header('Content-Disposition', 'attachment; filename="baremo_itacyl.csv"')
            self.end_headers()
            self.wfile.write(output.getvalue())
        except Exception as e:
            self.send_response(200)
            self.send_header('Content-type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(f"ERROR: {str(e)}".encode('utf-8'))
