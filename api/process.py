from http.server import BaseHTTPRequestHandler
import json
import pandas as pd
import re
import io

def motor_baremacion_itacyl(row):
    nombre = str(row.get('name', '')).upper()
    
    # --- SUBMÓDULO: IS_valor (Rader) ---
    def calcular_is_rader(r):
        n = r.get('n', 0) if r.get('n') else 0
        p = r.get('p2o5', 0) if r.get('p2o5') else 0
        k = r.get('k2o', 0) if r.get('k2o') else 0
        # Datos bibliográficos
        if any(kw in nombre for kw in ["COMPOST", "ESTIERCOL", "HUMUS", "ORGANIC"]): return 15
        if "UREA" in nombre: return 75
        if "NITRATO AMONICO" in nombre or "NAC" in nombre: return 104
        # Cálculo Rader
        return int(round((n * 1.65) + (p * 0.5) + (k * 1.9)))

    IS_valor = calcular_is_rader(row)

    # --- FASE I Y II: NOTAS FIJAS ---
    kw_inhibidores = ["DMPP", "NBPT", "INHIBIDOR", "ESTABILIZADO", "NOVATEC", "ENTEC", "NEXUR"]
    if row.get('nitrificationInhibitor') or row.get('ureaseInhibitor') or any(k in nombre for k in kw_inhibidores):
        return "10,0", "[C]", "Nulo", IS_valor
    
    if pd.notnull(row.get('yearPercent1')) or any(k in nombre for k in ["COMPOST", "ESTIERCOL"]):
        return "10,0", "[E]", "Nulo", IS_valor

    # --- FASE III: ALGORITMO ---
    baremo = 6.0
    if (row.get('organicMatter') or 0) > 20: baremo += 3.0
    if (row.get('s') or 0) > 2 or (row.get('ammoniacalN') or 0) > 10: baremo += 2.0
    
    # ZVN (Umbral 15%)
    es_fondo = (not row.get('topDressing')) and (not row.get('yearPercent1'))
    val_n = row.get('n', 0) if es_fondo else row.get('nitricN', 0)
    val_n = val_n if val_n else 0
    if 1 <= val_n <= 15: baremo -= 1.5
    elif val_n > 15: baremo -= 3.0

    # Salinidad (Cis)
    if IS_valor < 20: baremo += 1.5
    elif IS_valor > 100: baremo -= 4.0
    elif 80 <= IS_valor <= 100: baremo -= 3.0
    elif 50 < IS_valor < 80: baremo -= 1.5

    res = round(min(max(baremo, 1.0), 10.0), 1)
    tipo = "[R]" if row.get('aggregateState') == 'L' else "[F]"
    return str(res).replace('.', ','), tipo, "Verificado", IS_valor

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        
        # Cargar JSON y procesar
        data = json.loads(post_data)
        if isinstance(data, dict) and 'items' in data: data = data['items']
        
        df = pd.DataFrame(data)
        df[['Baremo', 'Tipo', 'Riesgo', 'IS']] = df.apply(lambda r: pd.Series(motor_baremacion_itacyl(r)), axis=1)
        
        output = df[['name', 'Tipo', 'Riesgo', 'IS', 'Baremo']]
        csv_data = output.to_csv(index=False, sep=';', decimal=',')
        
        self.send_response(200)
        self.send_header('Content-type', 'text/csv')
        self.send_header('Content-Disposition', 'attachment; filename="baremo_itacyl.csv"')
        self.end_headers()
        self.wfile.write(csv_data.encode('utf-8'))
