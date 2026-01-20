from http.server import BaseHTTPRequestHandler
import json
import pandas as pd
import io
import re

def motor_baremacion_itacyl(row):
    """
    MOTOR DE BAREMACIÓN AGRONÓMICA - ESCENARIO A
    Versión 1.3.1 Final (20/01/2026) - Criterio SIEX 13 e Identidad de Texto
    """
    # 0. PREPROCESAMIENTO
    nombre_raw = str(row.get('name', '')).strip()
    if not nombre_raw or nombre_raw.lower() == 'nan': nombre_raw = "PRODUCTO SIN NOMBRE"
    nombre = nombre_raw.upper()

    def get_val(key):
        v = row.get(key)
        if pd.isna(v) or v is None: return 0.0
        try: return float(v)
        except: return 0.0

    # Carga de variables analíticas primarias
    n, p2o5, k2o = get_val('n'), get_val('p2o5'), get_val('k2o')
    nitricN, ammoniacalN = get_val('nitricN'), get_val('ammoniacalN')
    organicMatter, s = get_val('organicMatter'), get_val('s')
    materialSiexId = get_val('materialSiexId') # Variable normativa

    # 1. ÍNDICE DE SALINIDAD (IS_VALOR)
    if any(k in nombre for k in ["COMPOST", "ESTIERCOL", "HUMUS", "ORGANIC"]): is_v = 15
    elif "NITRATO AMONICO" in nombre or "NAC" in nombre: is_v = 104
    elif "UREA" in nombre: is_v = 75
    elif any(k in nombre for k in ["NITRATO DE CALCIO", "CALCINIT"]): is_v = 85
    elif "NITRATO DE POTASIO" in nombre: is_v = 74
    elif "SULFATO POTASICO" in nombre or "SOP" in nombre: is_v = 46
    elif "SULFATO AMONICO" in nombre: is_v = 69
    elif "CLORURO" in nombre: is_v = 116
    elif "DAP" in nombre: is_v = 34
    elif "MAP" in nombre: is_v = 30
    else:
        val_calc = (n * 1.65) + (p2o5 * 0.5) + (k2o * 1.9)
        is_v = int(round(min(max(val_calc, 5), 140)))

    # 2. CLASIFICACIÓN TÉCNICA Y NOTAS FIJAS
    es_enmienda = (not pd.isna(row.get('yearPercent1'))) or (materialSiexId == 13)
    es_cobertera = row.get('topDressing') is True
    is_liquid = row.get('aggregateState') == 'L' or "SOLUB" in nombre
    
    if es_enmienda: tipo = "[E]"
    elif any(k in nombre for k in ["NITRATO DE CALCIO", "CALCINIT", "SOLUTECK"]): tipo = "[C,R]"
    elif es_cobertera: tipo = "[C,R]" if is_liquid else "[C]"
    else: tipo = "[R]" if is_liquid else "[F]"

    # Verificación de Tecnologías de Estabilización
    kw_inh = ["DMPP", "NBPT", "INHIBIDOR", "ESTABILIZADO", "NOVATEC", "ENTEC", "NEXUR"]
    es_tec = row.get('nitrificationInhibitor') is True or row.get('ureaseInhibitor') is True
    
    if es_enmienda or es_tec or any(k in nombre for k in kw_inh):
        return f'="{nombre_raw}"', tipo, "Bajo", is_v, "10,0"
    
    if tipo == "[C,R]" and any(k in nombre for k in ["NITRATO DE CALCIO", "CALCINIT", "SOLUTECK"]):
        return f'="{nombre_raw}"', tipo, "Medio", is_v, "9,5"

    # 3. ALGORITMO ACUMULATIVO (Base 6.0)
    baremo = 6.0
    if organicMatter > 20: baremo += 3.0
    if s > 2 or ammoniacalN > 10: baremo += 2.0
    
    # Bonus Micros/Mg (Prioridad Analítica)
    micros_list = ['fe', 'zn', 'mn', 'cu', 'b', 'mo', 'mg']
    tiene_micros = any(get_val(m) > 0 for m in micros_list)
    if not tiene_micros:
        kw_micros = ["QUELAT", "MICROS", "BORO", "ZINC", "HIERRO", "MANGANESO", "MAGNESIO", "MG"]
        tiene_micros = any(k in nombre for k in kw_micros)
    if tiene_micros: baremo += 1.5

    # Bonus P/K (Sistema de Doble Validación)
    npk_match = re.search(r'(\d+)-(\d+)-(\d+)', nombre)
    if p2o5 > 15: baremo += 1.0
    elif p2o5 == 0 and npk_match and float(npk_match.group(2)) > 15: baremo += 1.0
    if k2o > 15: baremo += 1.0
    elif k2o == 0 and npk_match and float(npk_match.group(3)) > 15: baremo += 1.0

    # 4. PENALIZACIONES
    es_fondo = (not es_cobertera) and (not es_enmienda)
    val_n_eval = n if es_fondo else nitricN
    riesgo = "Bajo"
    if 10 <= val_n_eval <= 20: 
        baremo -= 1.5
        riesgo = "Medio"
    elif val_n_eval > 20: 
        baremo -= 3.0
        riesgo = "Alto"

    # Matriz Salinidad Cis (6 Rangos)
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
            
            if isinstance(raw_json, dict) and 'items' in raw_json:
                lista = raw_json['items']
            elif isinstance(raw_json, list):
                lista = raw_json
            else:
                lista = [raw_json]

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
