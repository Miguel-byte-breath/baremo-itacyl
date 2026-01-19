from http.server import BaseHTTPRequestHandler
import json
import pandas as pd
import math
import io

def motor_baremacion_itacyl(row):
    # Función de seguridad para números (maneja nulos, NaNs y textos)
    def n(key):
        val = row.get(key)
        if pd.isna(val) or val is None: return 0.0
        try: return float(val)
        except: return 0.0

    # Limpieza del nombre
    nombre_raw = str(row.get('name', '')).strip()
    if not nombre_raw or nombre_raw.lower() == 'nan':
        nombre_raw = "PRODUCTO SIN NOMBRE"
    
    nombre_up = nombre_raw.upper()
    
    # --- IS_valor (Metodología Rader) ---
    if any(kw in nombre_up for kw in ["COMPOST", "ESTIERCOL", "HUMUS", "ORGANIC", "TURBA"]):
        is_v = 15
    elif "NITRATO AMONICO" in nombre_up or "NAC" in nombre_up:
        is_v = 104
    elif "UREA" in nombre_up:
        is_v = 75
    elif "NITRATO DE CALCIO" in nombre_up or "CALCINIT" in nombre_up:
        is_v = 85
    else:
        calc = (n('n') * 1.65) + (n('p2o5') * 0.5) + (n('k2o') * 1.9)
        is_v = int(round(calc))

    # --- FASE I y II: EXENCIONES ---
    kw_inh = ["DMPP", "NBPT", "INHIBIDOR", "ESTABILIZADO", "NOVATEC", "ENTEC", "NEXUR"]
    es_tec = row.get('nitrificationInhibitor') is True or row.get('ureaseInhibitor') is True
    if es_tec or any(k in nombre_up for k in kw_inh):
        return f'="{nombre_raw}"', "[C]", "Nulo", is_v, "10,0"

    # --- FASE III: ALGORITMO ACUMULATIVO ---
    baremo = 6.0
    if n('organicMatter') > 20: baremo += 3.0
    if n('s') > 2 or n('ammoniacalN') > 10: baremo += 2.0
    
    kw_micros = ["QUELAT", "MICROS", "BORO", "ZINC", "HIERRO", "MANGANESO", "MAGNESIO"]
    tiene_micros = any(n(m) > 0 for m in ['fe', 'zn', 'mn', 'cu', 'b', 'mo', 'ca', 'mg']) or any(k in nombre_up for k in kw_micros)
    if tiene_micros: baremo += 1.5

    # ZVN (Umbral 15%)
    es_cobertera = row.get('topDressing') is True
    val_n_zvn = n('nitricN') if es_cobertera else n('n')
    if 1 <= val_n_zvn <= 15: baremo -= 1.5
    elif val_n_zvn > 15: baremo -= 3.0

    # Salinidad (Cis)
    if is_v < 20: baremo += 1.5
    elif is_v > 100: baremo -= 4.0
    elif 80 <= is_v <= 100: baremo -= 3.0
    elif 50 < is_v < 80: baremo -= 1.5

    final = round(min(max(baremo, 1.0), 10.0), 1)
    tipo = "[R]" if row.get('aggregateState') == 'L' else "[F]"
    
    return f'="{nombre_raw}"', tipo, "Verificado", is_v, str(final).replace('.', ',')

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            raw_json = json.loads(post_data)
            
            # Normalización del JSON
            if isinstance(raw_json, dict) and 'items' in raw_json:
                lista = raw_json['items']
            elif isinstance(raw_json, list):
                lista = raw_json
            else:
                lista = [raw_json]

            # Creamos DataFrame y limpiamos nulos críticos antes de procesar
            df = pd.DataFrame(lista)
            
            # Procesamos
            res_df = df.apply(lambda r: pd.Series(motor_baremacion_itacyl(r)), axis=1)
            res_df.columns = ['name', 'Tipo', 'Riesgo', 'IS_valor', 'Baremo']
            
            # LA SOLUCIÓN DEFINITIVA PARA EXCEL:
            # Usamos un buffer de memoria y forzamos utf-8-sig (BOM nativo de Pandas)
            output = io.BytesIO()
            res_df.to_csv(output, index=False, sep=';', decimal=',', encoding='utf-8-sig')
            csv_bytes = output.getvalue()
            
            self.send_response(200)
            self.send_header('Content-type', 'text/csv; charset=utf-8-sig')
            self.send_header('Content-Disposition', 'attachment; filename="baremo_itacyl.csv"')
            self.end_headers()
            self.wfile.write(csv_bytes)

        except Exception as e:
            self.send_response(200)
            self.send_header('Content-type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(f"ERROR: {str(e)}".encode('utf-8'))
