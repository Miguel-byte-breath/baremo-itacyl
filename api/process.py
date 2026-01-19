from http.server import BaseHTTPRequestHandler
import json
import pandas as pd
import re
import io

def motor_baremacion_itacyl(row):
    # Función de seguridad para números: si es None o texto, devuelve 0.0
    def n(key):
        val = row.get(key)
        try: return float(val) if val is not None else 0.0
        except: return 0.0

    nombre = str(row.get('name', 'SIN NOMBRE')).upper()
    
    # --- IS_valor (Metodología Rader) ---
    # Prioridad: Bibliografía externa para productos puros
    if any(kw in nombre for kw in ["COMPOST", "ESTIERCOL", "HUMUS", "ORGANIC", "TURBA"]):
        is_v = 15
    elif "NITRATO AMONICO" in nombre or "NAC" in nombre:
        is_v = 104
    elif "UREA" in nombre:
        is_v = 75
    else:
        # Cálculo Rader: IS = (N*1.65) + (P*0.5) + (K*1.9)
        is_v = int(round((n('n') * 1.65) + (n('p2o5') * 0.5) + (n('k2o') * 1.9)))

    # --- FASE I y II: EXENCIONES (Pto 5.3) ---
    kw_inh = ["DMPP", "NBPT", "INHIBIDOR", "ESTABILIZADO", "NOVATEC", "ENTEC", "NEXUR"]
    es_tec = row.get('nitrificationInhibitor') is True or row.get('ureaseInhibitor') is True
    if es_tec or any(k in nombre for k in kw_inh):
        return "10,0", "[C]", "Nulo", is_v

    # --- FASE III: ALGORITMO ACUMULATIVO ---
    baremo = 6.0
    if n('organicMatter') > 20: baremo += 3.0
    if n('s') > 2 or n('ammoniacalN') > 10: baremo += 2.0
    
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
    return str(final).replace('.', ','), tipo, "Verificado", is_v

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            # 1. Intentar leer el JSON
            raw_json = json.loads(post_data)
            
            # 2. Extraer la lista de productos (ITACyL suele enviarlos en 'items')
            if isinstance(raw_json, dict) and 'items' in raw_json:
                lista_productos = raw_json['items']
            elif isinstance(raw_json, list):
                lista_productos = raw_json
            else:
                raise Exception("El formato JSON no es una lista válida de productos.")

            df = pd.DataFrame(lista_productos)
            
            # 3. Aplicar Baremación
            df[['Baremo', 'Tipo', 'Riesgo', 'IS_valor']] = df.apply(
                lambda r: pd.Series(motor_baremacion_itacyl(r)), axis=1
            )
            
            # 4. Generar CSV de salida
            output = df[['name', 'Tipo', 'Riesgo', 'IS_valor', 'Baremo']]
            csv_str = output.to_csv(index=False, sep=';', decimal=',', encoding='utf-8-sig')
            
            self.send_response(200)
            self.send_header('Content-type', 'text/csv')
            self.send_header('Content-Disposition', 'attachment; filename="baremo_itacyl.csv"')
            self.end_headers()
            self.wfile.write(csv_str.encode('utf-8'))

        except Exception as e:
            # Si algo falla, devolvemos el error real para saber qué pasa
            self.send_response(200) # Usamos 200 para que el navegador muestre el texto
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(f"ERROR EN EL MOTOR: {str(e)}".encode())
