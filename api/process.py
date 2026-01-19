from http.server import BaseHTTPRequestHandler
import json
import pandas as pd
import math
import re

def motor_baremacion_itacyl(row):
    # Función de seguridad total para números
    def safe_num(key):
        val = row.get(key)
        if val is None or str(val).lower() == 'nan' or str(val).strip() == '':
            return 0.0
        try:
            f_val = float(val)
            return f_val if not math.isnan(f_val) else 0.0
        except:
            return 0.0

    nombre = str(row.get('name', 'SIN NOMBRE')).upper()
    
    # --- DETERMINACIÓN DEL IS_valor ---
    n_val = safe_num('n')
    p_val = safe_num('p2o5')
    k_val = safe_num('k2o')

    # Prioridad: Datos bibliográficos para productos puros
    if any(kw in nombre for kw in ["COMPOST", "ESTIERCOL", "HUMUS", "ORGANIC", "TURBA"]):
        is_v = 15
    elif "NITRATO AMONICO" in nombre or "NAC" in nombre:
        is_v = 104
    elif "UREA" in nombre:
        is_v = 75
    elif "NITRATO DE CALCIO" in nombre or "CALCINIT" in nombre:
        is_v = 85
    else:
        # Cálculo Rader con protección contra NaN
        calc = (n_val * 1.65) + (p_val * 0.5) + (k_val * 1.9)
        is_v = int(round(calc)) if not math.isnan(calc) else 0

    # --- FASE I y II: EXENCIONES ---
    kw_inh = ["DMPP", "NBPT", "INHIBIDOR", "ESTABILIZADO", "NOVATEC", "ENTEC", "NEXUR"]
    es_tec = row.get('nitrificationInhibitor') is True or row.get('ureaseInhibitor') is True
    if es_tec or any(k in nombre for k in kw_inh):
        return "10,0", "[C]", "Nulo", is_v

    # --- FASE III: ALGORITMO ACUMULATIVO ---
    baremo = 6.0
    if safe_num('organicMatter') > 20: baremo += 3.0
    if safe_num('s') > 2 or safe_num('ammoniacalN') > 10: baremo += 2.0
    
    # Bonus Microelementos
    kw_micros = ["QUELAT", "MICROS", "BORO", "ZINC", "HIERRO", "MANGANESO", "MAGNESIO"]
    tiene_micros = any(safe_num(m) > 0 for m in ['fe', 'zn', 'mn', 'cu', 'b', 'mo']) or any(k in nombre for k in kw_micros)
    if tiene_micros: baremo += 1.5

    # ZVN (Umbral 15%)
    es_cobertera = row.get('topDressing') is True
    val_n_zvn = safe_num('nitricN') if es_cobertera else n_val
    if 1 <= val_n_zvn <= 15: baremo -= 1.5
    elif val_n_zvn > 15: baremo -= 3.0

    # Salinidad (Cis)
    if is_v < 20: baremo += 1.5
    elif is_v > 100: baremo -= 4.0
    elif 80 <= is_v <= 100: baremo -= 3.0
    elif 50 < is_v < 80: baremo -= 1.5

    final = round(min(max(baremo, 1.0), 10.0), 1)
    tipo = "[R]" if row.get('aggregateState') == 'L' else "[F]"
    return str(final).replace('.', ','), tipo, "Verificado", is_v

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            raw_json = json.loads(post_data)
            
            # Normalización de la estructura JSON
            if isinstance(raw_json, dict) and 'items' in raw_json:
                lista = raw_json['items']
            elif isinstance(raw_json, list):
                lista = raw_json
            else:
                lista = [raw_json]

            df = pd.DataFrame(lista)
            
            # Ejecutar Baremación
            df[['Baremo', 'Tipo', 'Riesgo', 'IS_valor']] = df.apply(
                lambda r: pd.Series(motor_baremacion_itacyl(r)), axis=1
            )
            
            # Generar CSV
            output = df[['name', 'Tipo', 'Riesgo', 'IS_valor', 'Baremo']]
            csv_str = output.to_csv(index=False, sep=';', decimal=',', encoding='utf-8-sig')
            
            self.send_response(200)
            self.send_header('Content-type', 'text/csv')
            self.send_header('Content-Disposition', 'attachment; filename="baremo_itacyl.csv"')
            self.end_headers()
            self.wfile.write(csv_str.encode('utf-8'))

        except Exception as e:
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            error_msg = f"ERROR DETECTADO: {str(e)}\n\nConsejo: Revisa que el JSON no esté vacío."
            self.wfile.write(error_msg.encode('utf-8'))
