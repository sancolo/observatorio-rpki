# Observatorio RPKI
import sys
import pandas as pd
import requests
import time
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

ARCHIVO_DATOS  = sys.argv[1] if len(sys.argv) > 1 else "internet_enriquecida_rpki.csv"
ARCHIVO_SALIDA = sys.argv[2] if len(sys.argv) > 2 else "top_10_infractores.csv"
FECHA          = sys.argv[3] if len(sys.argv) > 3 else ""
PUSHGATEWAY    = sys.argv[4] if len(sys.argv) > 4 else "localhost:9091"

def obtener_nombre_peeringdb(asn):
    """
    Consulta la API pública de PeeringDB para obtener el nombre de la 
    organización y su sitio web dado un ASN.
    """
    url = f"https://peeringdb.com/api/net?asn={asn}"
    try:
        respuesta = requests.get(url, timeout=5)
        if respuesta.status_code == 200:
            datos = respuesta.json()
            if datos['data']:
                org_name = datos['data'][0].get('name', 'Desconocido')
                website = datos['data'][0].get('website', 'Sin web')
                return org_name, website
    except Exception as e:
        pass
    return "Desconocido (No en PeeringDB)", "-"

def generar_hallazgos_paper(archivo_csv, archivo_salida="top_10_infractores.csv", fecha="", pushgateway="localhost:9091"):
    print(f"Cargando dataset enriquecido ({archivo_csv})...\n")
    df = pd.read_csv(archivo_csv)

    # ==========================================
    # HALLAZGO 3: Métricas de Adopción Real (El más rápido de calcular)
    # ==========================================
    print("--- HALLAZGO 3: Tasa de Invalidez (Max-Length vs Origin Mismatch) ---")
    total_rutas = len(df)
    
    rutas_max_len = len(df[df['Estado_RPKI'] == 'Invalid: Max-Length Exceeded'])
    rutas_origin = len(df[df['Estado_RPKI'] == 'Invalid: Origin Mismatch'])
    
    pct_max_len = (rutas_max_len / total_rutas) * 100
    pct_origin = (rutas_origin / total_rutas) * 100
    
    print(f"Rutas inválidas por Max-Length: {rutas_max_len:,} ({pct_max_len:.2f}%)")
    print(f"Rutas inválidas por ASN Falso/Erróneo: {rutas_origin:,} ({pct_origin:.2f}%)")
    if rutas_max_len > rutas_origin:
        proporcion = rutas_max_len / rutas_origin if rutas_origin > 0 else 0
        print(f"-> Conclusión empírica: El error de Max-Length es {proporcion:.1f} veces más frecuente que el secuestro de ASN.\n")


    # ==========================================
    # HALLAZGO 1: El Top 10 de Infractores (Origin Mismatch)
    # ==========================================
    print("--- HALLAZGO 1: Top 10 ASNs originando rutas inválidas (Posibles Secuestros) ---")
    # Filtramos solo las rutas con Origin Mismatch
    df_origin_mismatch = df[df['Estado_RPKI'] == 'Invalid: Origin Mismatch']
    
    # Agrupamos por ASN y contamos cuántos prefijos está anunciando mal
    top_10_asn = df_origin_mismatch.groupby('ASN_BGP').size().reset_index(name='Cantidad_Prefijos_Invalidos')
    top_10_asn = top_10_asn.sort_values(by='Cantidad_Prefijos_Invalidos', ascending=False).head(10)
    
    # ==========================================
    # HALLAZGO 2: Identificación (Cruce con PeeringDB)
    # ==========================================
    print("\n--- HALLAZGO 2: Identificando a los actores en PeeringDB ---")
    print("Consultando API de PeeringDB... (esto puede tardar unos segundos)")
    
    resultados_finales = []
    
    for index, fila in top_10_asn.iterrows():
        asn = fila['ASN_BGP']
        cantidad = fila['Cantidad_Prefijos_Invalidos']
        
        # Consultamos PeeringDB
        nombre_org, website = obtener_nombre_peeringdb(asn)
        
        resultados_finales.append({
            'ASN': asn,
            'Organización': nombre_org,
            'Prefijos_Secuestrados_o_Erroneos': cantidad,
            'Sitio_Web': website
        })
        time.sleep(0.5) # Respetamos el rate-limit de la API pública
        
    df_top10 = pd.DataFrame(resultados_finales)
    
    # Mostrar la tabla final lista para el paper
    print("\nTabla Final para el trabajo de investigación:")
    print(df_top10.to_string(index=False))
    
    df_top10.to_csv(archivo_salida, index=False)
    print(f"\nReporte exportado a '{archivo_salida}'")

    exportar_top_infractores_prometheus(df_top10, fecha=fecha, ip_pushgateway=pushgateway)

def exportar_top_infractores_prometheus(df_top10, fecha="", ip_pushgateway="localhost:9091"):
    print("Inyectando el Top 10 de infractores en Prometheus...")
    registro = CollectorRegistry()

    metrica_top = Gauge('rpki_infractores_bgp',
                        'Cantidad de rutas inválidas (Origin Mismatch) por ASN',
                        ['asn', 'organizacion', 'fecha'],
                        registry=registro)

    for index, fila in df_top10.iterrows():
        asn = str(fila['ASN'])
        org = str(fila['Organización'])
        cantidad = fila['Prefijos_Secuestrados_o_Erroneos']
        metrica_top.labels(asn=asn, organizacion=org, fecha=fecha).set(cantidad)

    try:
        push_to_gateway(ip_pushgateway, job=f'observatorio_infractores_{fecha}', registry=registro)
        print("Éxito: Infractores inyectados para Grafana.")
    except Exception as e:
        print(f"Error al conectar con Pushgateway: {e}")

if __name__ == "__main__":
    try:
        generar_hallazgos_paper(ARCHIVO_DATOS, ARCHIVO_SALIDA, FECHA, PUSHGATEWAY)
    except FileNotFoundError:
        print(f"Error: No se encuentra {ARCHIVO_DATOS}. Debes ejecutar el pipeline de cruce primero.")


