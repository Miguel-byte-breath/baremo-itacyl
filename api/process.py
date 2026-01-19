from http.server import BaseHTTPRequestHandler
import json
import pandas as pd
import math
import re

def motor_baremacion_itacyl(row):
    def safe_num(key):
        val = row.get(key)
        if val is None or str(val).lower() == 'nan' or str(val).strip() == '':
            return 0.0
        try:
            f_val = float(val)
            return f_val if not math.isnan(f_val) else 0.0
        except:
            return 0.0

    # Capturamos el nombre y nos aseguramos de que sea texto limpio
    nombre_original = str(row.get('name', 'SIN NOMBRE')).upper()
    
    # --- DETERMINACIÓN DEL IS_valor ---
    n_val = safe_num('n')
    p_val = safe_num('p2o5')
    k_val = safe_num('k2o')

    if any(kw in nombre_original for kw in ["COMPOST", "ESTIERCOL", "HUMUS", "ORGANIC", "TURBA"]):
        is_v = 15
    elif "NITRATO AMONICO" in nombre_original or "NAC" in nombre_original:
        is_v = 104
    elif "UREA" in nombre_original:
        is_v = 75
    elif "NITRATO DE CALCIO" in nombre_original or "CALCINIT" in nombre_original:
        is_v = 85
    else:
        calc = (n_val * 1.65) + (p_val * 0.5) + (k_val * 1.9)
        is_v = int(round(calc)) if not math.isnan(calc) else 0

    # --- FASE I y II: EXENCIONES ---
    kw_inh = ["DMPP", "NBPT", "INHIBIDOR", "ESTABILIZADO", "NOVATEC", "ENTEC", "NEXUR"]
    es_tec = row.get('nitrificationInhibitor') is True or row.get('ureaseInhibitor') is True
    if es_tec or any(k in nombre_original for k in kw_inh):
        return f'="{nombre_original}"', "[C]", "Nulo", is_v, "10,0"

    # --- FASE III: ALGORITMO ACUMULATIVO ---
    baremo = 6.0
    if safe_num('organicMatter') > 20: baremo += 3.0
    if safe_num('s') > 2 or safe_num('ammoniacalN') > 10: baremo += 2.0
    
    kw_micros = ["QUELAT", "MICROS", "BORO", "ZINC", "HIERRO", "MANGANESO", "MAGNESIO"]
    tiene_micros = any(safe_num(m) > 0 for m in ['fe', 'zn', 'mn', 'cu', 'b', 'mo']) or any(k in nombre_original for k in kw_micros)
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
    
    # Mantenemos el truco de las comillas para evitar fechas en Excel
    return f'="{nombre_original}"', tipo, "Verificado", is_v, str(final).replace('.', ',')

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
            
            # Aplicamos la baremación
            res_df = df.apply(lambda r: pd.Series(motor_baremacion_itacyl(r)), axis=1)
            res_df.columns = ['name', 'Tipo', 'Riesgo', 'IS_valor', 'Baremo']
            
            # Generamos el CSV como cadena de texto
            csv_str = res_df.to_csv(index=False, sep=';', decimal=',', encoding='utf-8')
            
            # LA CLAVE: Prependemos el BOM (\ufeff) al convertir a bytes
            # Esto le dice a Excel: "Usa UTF-8"
            csv_bytes = b'\xef\xbb\xbf' + csv_str.encode('utf-8')
            
            self.send_response(200)
            self.send_header('Content-type', 'text/csv; charset=utf-8')
            self.send_header('Content-Disposition', 'attachment; filename="baremo_itacyl.csv"')
            self.end_headers()
            self.wfile.write(csv_bytes)

        except Exception as e:
            self.send_response(200)
            self.send_header('Content-type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(f"ERROR: {str(e)}".encode('utf-8'))
