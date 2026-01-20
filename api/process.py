from http.server import BaseHTTPRequestHandler
import json
import pandas as pd
import math
import io
import re

def motor_baremacion_itacyl(row):
    # --- LIMPIEZA DE NULOS (Sincronizado con Anexo III) ---
    def get_val(key):
        v = row.get(key)
        if pd.isna(v) or v is None: return 0.0
        try: return float(v)
        except: return 0.0

    nombre_raw = str(row.get('name', '')).strip()
    if not nombre_raw or nombre_raw.lower() == 'nan': nombre_raw = "PRODUCTO SIN NOMBRE"
    nombre = nombre_raw.upper()

    # 1. DETERMINACIÓN DEL IS_VALOR (RADER + BIBLIOGRÁFICO)
    n = get_val('n')
    p2o5 = get_val('p2o5')
    k2o = get_val('k2o')
    
    if any(k in nombre for k in ["COMPOST", "ESTIERCOL", "HUMUS", "ORGANIC", "TURBA"]): is_v = 15
    elif "NITRATO AMONICO" in nombre or "NAC" in nombre: is_v = 104
    elif "UREA" in nombre: is_v = 75
    elif "NITRATO DE CALCIO" in nombre or "CALCINIT" in nombre: is_v = 85
    elif "NITRATO DE POTASIO" in nombre: is_v = 74
    elif "SULFATO POTASICO" in nombre or "SOP" in nombre: is_v = 46
    elif "SULFATO AMONICO" in nombre: is_v = 69
    elif "CLORURO" in nombre: is_v = 116
    elif "DAP" in nombre: is_v = 34
    elif "MAP" in nombre: is_v = 30
    else:
        val_calc = (n * 1.65) + (p2o5 * 0.5) + (k2o * 1.9)
        is_v = int(round(min(max(val_calc, 5), 140)))

    # 2. CLASIFICACIÓN DE TIPO (Jerarquía Doc. Técnico)
    es_enmienda = not pd.isna(row.get('yearPercent1'))
    es_cobertera = row.get('topDressing') is True
    is_liquid = row.get('aggregateState') == 'L' or "SOLUB" in nombre
    
    if es_enmienda: tipo = "[E]"
    elif "NITRATO DE CALCIO" in nombre or "CALCINIT" in nombre or "SOLUTECK" in nombre: tipo = "[C,R]"
    elif es_cobertera: tipo = "[C,R]" if is_liquid else "[C]"
    else: tipo = "[R]" if is_liquid else "[F]"

    # 3. NOTAS FIJAS (Pto 5.3)
    kw_inh = ["DMPP", "NBPT", "INHIBIDOR", "ESTABILIZADO", "NOVATEC", "ENTEC", "NEXUR"]
    es_tec = row.get('nitrificationInhibitor') is True or row.get('ureaseInhibitor') is True
    
    if es_enmienda or es_tec or any(k in nombre for k in kw_inh):
        return f'="{nombre_raw}"', tipo, "Bajo", is_v, "10,0"
    if tipo == "[C,R]" and ("NITRATO DE CALCIO" in nombre or "SOLUTECK" in nombre):
        return f'="{nombre_raw}"', tipo, "Medio", is_v, "9,5"

    # 4. ALGORITMO ACUMULATIVO (Base 6.0)
    baremo = 6.0
    if get_val('organicMatter') > 20: baremo += 3.0
    if get_val('s') > 2 or get_val('ammoniacalN') > 10: baremo += 2.0
    
    kw_micros = ["QUELAT", "MICROS", "BORO", "ZINC", "HIERRO", "MANGANESO", "MAGNESIO"]
    tiene_micros = any(get_val(m) > 0 for m in ['fe', 'zn', 'mn', 'cu', 'b', 'mo']) or any(k in nombre for k in kw_micros)
    if tiene_micros: baremo += 1.5

    # Bonus Riqueza P/K (Regex)
    npk_match = re.search(r'(\d+)-(\d+)-(\d+)', nombre)
    if npk_match:
        if float(npk_match.group(2)) > 15: baremo += 1.0
        if float(npk_match.group(3)) > 15: baremo += 1.0

    # 5. PENALIZACIONES (ZVN 10% y Salinidad)
    es_fondo = (not es_cobertera) and (not es_enmienda)
    val_n = n if es_fondo else get_val('nitricN')
    
    riesgo = "Bajo"
    if 10 <= val_n <= 20: 
        baremo -= 1.5
        riesgo = "Medio"
    elif val_n > 20: 
        baremo -= 3.0
        riesgo = "Alto"

    if is_v < 20: baremo += 1.5
    elif 20 <= is_v < 40: baremo += 0.5
    elif 40 <= is_v <= 60: baremo += 0.0
    elif 60 < is_v <= 80: baremo -= 0.5
    elif 80 < is_v <= 100: baremo -= 1.5
    elif is_v > 100: baremo -= 3.0

    final = round(min(max(baremo, 1.0), 10.0), 1)
    return f'="{nombre_raw}"', tipo, riesgo, is_v, str(final).replace('.', ',')

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            raw_json = json.loads(post_data)
            lista = raw_json['items'] if isinstance(raw_json, dict) and 'items' in raw_json else (raw_json if isinstance(raw_json, list) else [raw_json])
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
