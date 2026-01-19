from http.server import BaseHTTPRequestHandler
import json
import pandas as pd
import re
import io

def motor_baremacion_itacyl(row):
    # Función auxiliar para convertir valores a número de forma segura (evita errores con 'null')
    def safe_num(val):
        try: 
            return float(val) if val is not None else 0.0
        except: 
            return 0.0

    nombre = str(row.get('name', 'PRODUCTO DESCONOCIDO')).upper()
    
    # --- SUBMÓDULO: IS_valor (Metodología Rader) ---
    n = safe_num(row.get('n'))
    p = safe_num(row.get('p2o5'))
    k = safe_num(row.get('k2o'))

    # Datos bibliográficos fijos (Prioritarios)
    if any(kw in nombre for kw in ["COMPOST", "ESTIERCOL", "HUMUS", "ORGANIC"]): 
        IS_valor = 15
    elif "UREA" in nombre: 
        IS_valor = 75
    elif "NITRATO AMONICO" in nombre or "NAC" in nombre: 
        IS_valor = 104
    elif "NITRATO DE CALCIO" in nombre or "CALCINIT" in nombre: 
        IS_valor = 85
    else:
        # Cálculo Rader integrado (Anexo II)
        IS_valor = int(round((n * 1.65) + (p * 0.5) + (k * 1.9)))

    # --- FASE I Y II: NOTAS FIJAS / EXENCIONES TECNOLÓGICAS ---
    kw_inhibidores = ["DMPP", "NBPT", "INHIBIDOR", "ESTABILIZADO", "NOVATEC", "ENTEC", "NEXUR"]
    es_tec = row.get('nitrificationInhibitor') == True or row.get('ureaseInhibitor') == True
    if es_tec or any(k in nombre for k in kw_inhibidores):
        return "10,0", "[C]", "Nulo", IS_valor
    
    # --- FASE III: ALGORITMO ACUMULATIVO ---
    baremo = 6.0
    if safe_num(row.get('organicMatter')) > 20: baremo += 3.0
    if safe_num(row.get('s')) > 2 or safe_num(row.get('ammoniacalN')) > 10: baremo += 2.0
    
    # Bonus Microelementos
    kw_micros = ["QUELAT", "MICROS", "BORO", "ZINC", "HIERRO", "MANGANESO", "MAGNESIO"]
    tiene_micros = any(safe_num(row.get(m)) > 0 for m in ['fe', 'zn', 'mn', 'cu', 'b', 'mo']) or any(k in nombre for k in kw_micros)
    if tiene_micros: baremo += 1.5

    # ZVN (Umbral Proporcional 15%)
    # Si es abono de fondo (no cobertera), miramos N total. Si es cobertera, miramos N nítrico.
    val_n_zvn = n if not row.get('topDressing') else safe_num(row.get('nitricN'))
    if 1 <= val_n_zvn <= 15: baremo -= 1.5
    elif val_n_zvn > 15: baremo -= 3.0

    # Salinidad (Cis) - Matriz de 6 rangos
    if IS_valor < 20: baremo += 1.5
    elif IS_valor > 100: baremo -= 4.0
    elif 80 <= IS_valor <= 100: baremo -= 3.0
    elif 50 < IS_valor < 80: baremo -= 1.5

    res = round(min(max(baremo, 1.0), 10.0), 1)
    tipo = "[R]" if row.get('aggregateState') == 'L' else "[F]"
    return str(res).replace('.', ','), tipo, "Verificado", IS_valor

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data)
            
            # Gestión de formatos JSON de ITACyL (si vienen dentro de 'items')
            if isinstance(data, dict) and 'items' in data: data = data['items']
            if not isinstance(data, list): data = [data]
            
            df = pd.DataFrame(data)
            
            # Ejecutar motor fila a fila
            resultados = df.apply(lambda r: pd.Series(motor_baremacion_itacyl(r)), axis=1)
            df[['Baremo', 'Tipo', 'Riesgo', 'IS_valor']] = resultados
            
            # Preparar salida de 5 columnas (formato CSV ITACyL)
            output = df[['name', 'Tipo', 'Riesgo', 'IS_valor', 'Baremo']]
            csv_data = output.to_csv(index=False, sep=';', decimal=',', encoding='utf-8-sig')
            
            self.send_response(200)
            self.send_header('Content-type', 'text/csv')
            self.send_header('Content-Disposition', 'attachment; filename="baremo_itacyl.csv"')
            self.end_headers()
            self.wfile.write(csv_data.encode('utf-8'))
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f"Error técnico: {str(e)}".encode())
