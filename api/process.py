from http.server import BaseHTTPRequestHandler
import json
import pandas as pd
import io
import csv

def motor_baremacion_itacyl(row):
    """
    MOTOR DE BAREMACIÓN AGRONÓMICA - ESCENARIO A
    Versión 1.3.3 | Estabilidad Total y Fix TECNOPLUS (Sin RE)
    """
    try:
        # 0. PREPROCESAMIENTO
        nombre_raw = str(row.get('name', '')).strip()
        if not nombre_raw or nombre_raw.lower() == 'nan': 
            nombre_raw = "PRODUCTO SIN NOMBRE"
        
        # Normalización manual (Más robusta que RE para Vercel)
        # Quitamos el símbolo de copyright y otros caracteres molestos
        nombre_busqueda = nombre_raw.upper().replace('®', '').replace('©', '').replace('™', '')
        nombre = nombre_raw.upper()
        nombre_protegido = f"'{nombre_raw}"

        def clean(val):
            if pd.isna(val) or val is None: return 0.0
            try: 
                if isinstance(val, str): val = val.replace(',', '.')
                return float(val)
            except: return 0.0

        # Variables analíticas
        n = clean(row.get('n'))
        p2o5 = clean(row.get('p2o5'))
        k2o = clean(row.get('k2o'))
        nitricN = clean(row.get('nitricN'))
        ammoniacalN = clean(row.get('ammoniacalN'))
        organicMatter = clean(row.get('organicMatter'))
        s = clean(row.get('s'))
        materialSiexId = clean(row.get('materialSiexId')) 

        # 1. CÁLCULO DEL ÍNDICE DE SALINIDAD (IS_v)
        def calcular_is():
            # Prioridad 1: Nombres comerciales/técnicos específicos
            if any(k in nombre_busqueda for k in ["COMPOST", "ESTIERCOL", "HUMUS", "ORGANIC"]): return 15
            
            # El fix para Herogra y Fertiberia (Nitrato Potásico)
            if any(k in nombre_busqueda for k in ["NITRATO POTASICO", "NIPO", "TECNOPLUS"]): return 74
            
            if "NITRATO AMONICO" in nombre_busqueda or "NAC" in nombre_busqueda: return 104
            if "UREA" in nombre_busqueda: return 75
            if any(k in nombre_busqueda for k in ["NITRATO DE CALCIO", "CALCINIT"]): return 85
            if "SULFATO POTASICO" in nombre_busqueda or "SOP" in nombre_busqueda: return 46
            if "SULFATO AMONICO" in nombre_busqueda: return 69
            if "CLORURO" in nombre_busqueda: return 116
            if "DAP" in nombre_busqueda: return 34
            if "MAP" in nombre_busqueda: return 30
            
            # Prioridad 2: Fórmula de Rader
            calc = (n * 1.65) + (p2o5 * 0.5) + (k2o * 1.9)
            return int(round(min(max(calc, 5), 140)))

        IS_v = calcular_is()

        # 2. CLASIFICACIÓN TÉCNICA
        siex_e_directos = [1, 2, 3, 4, 5, 6, 7, 8, 10, 13, 19, 20, 21, 22]
        has_min = not pd.isna(row.get('yearPercent1'))
        is_siex_e = materialSiexId in siex_e_directos
        
        es_enm = has_min or is_siex_e
        es_cob = row.get('topDressing') is True
        is_liq = row.get('aggregateState') == 'L' or "SOLUB" in nombre
        
        if es_enm: tipo = "[E]"
        elif any(k in nombre for k in ["NITRATO DE CALCIO", "CALCINIT", "SOLUTECK"]): tipo = "[C,R]"
        elif es_cob: tipo = "[C,R]" if is_liq else "[C]"
        else: tipo = "[R]" if is_liq else "[F]"

        # Tecnologías
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
        
        micros_list = ['fe', 'zn', 'mn', 'cu', 'b', 'mo', 'mg']
        tiene_micros = any(clean(row.get(m)) > 0 for m in micros_list)
        if not tiene_micros:
            kw_mic = ["QUELAT", "MICROS", "BORO", "ZINC", "HIERRO", "MANGANESO", "MAGNESIO", "MG"]
            tiene_micros = any(k in nombre for k in kw_mic)
        if tiene_micros: baremo += 1.5

        if p2o5 > 15: baremo += 1.0
        if k2o > 15: baremo += 1.0

        # 4. PENALIZACIONES
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
    
    except Exception as e:
        return f"ERROR_FILA: {str(e)}", "N/A", "N/A", 0, "0,0"

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            raw_json = json.loads(post_data)
            
            # Normalizar entrada de datos
            if isinstance(raw_json, dict) and 'items' in raw_json: lista = raw_json['items']
            elif isinstance(raw_json, list): lista = raw_json
            else: lista = [raw_json]

            df = pd.DataFrame(lista)
            
            # Ejecución con expansión de columnas obligatoria
            res_df = df.apply(lambda r: motor_baremacion_itacyl(r), axis=1, result_type='expand')
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
            self.wfile.write(f"ERROR_GENERAL: {str(e)}".encode('utf-8'))
