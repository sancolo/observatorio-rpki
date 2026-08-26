import sys
import json
import pandas as pd
import ipaddress

ARCHIVO_JSON   = sys.argv[1] if len(sys.argv) > 1 else "vrps_globales.json"
ARCHIVO_SALIDA = sys.argv[2] if len(sys.argv) > 2 else "vrps_procesados_para_grafico.csv"
BASE_HOLGADOS  = sys.argv[3] if len(sys.argv) > 3 else "roas_holgados"

def cargar_y_procesar_vrps(archivo):
    print("Cargando base de datos criptográfica global...")
    with open(archivo, 'r') as f:
        datos = json.load(f)
    
    # Extraemos la lista de ROAs (dependiendo del formato exacto del validador)
    roas = datos.get('roas', [])
    
    registros = []
    for roa in roas:
        # Routinator suele usar 'prefix', 'maxLength', 'asn'
        prefijo_str = roa.get('prefix')
        max_len = roa.get('maxLength')
        asn = roa.get('asn')
        ta = roa.get('ta', 'Desconocido') # Trust Anchor (ARIN, RIPE, etc.)
        
        try:
            red = ipaddress.ip_network(prefijo_str)
            version = red.version
            prefix_len = red.prefixlen
            
            # Cálculo de la Variable Científica: El Gap de Flexibilidad
            gap_longitud = max_len - prefix_len
            
            registros.append({
                'Prefijo': prefijo_str,
                'ASN': asn,
                'Trust_Anchor': ta,
                'IP_Version': f'IPv{version}',
                'Prefijo_Base': prefix_len,
                'Max_Length': max_len,
                'Gap_Riesgo': gap_longitud
            })
        except ValueError:
            continue # Ignorar prefijos mal formados (raro en RPKI, pero buena práctica)
            
    # Convertimos la lista de diccionarios en un poderoso DataFrame de Pandas
    df = pd.DataFrame(registros)
    return df

def generar_estadisticas(df, archivo_salida="vrps_procesados_para_grafico.csv"):
    print("\n--- RESUMEN ESTADÍSTICO DE CIENCIA DE DATOS RPKI ---")

    total_roas = len(df)
    print(f"Total de ROAs analizados: {total_roas:,}")

    print("\nAdopción por Protocolo:")
    print(df['IP_Version'].value_counts(normalize=True).mul(100).round(2).astype(str) + '%')

    print("\nAnálisis de Vulnerabilidad (Loose ROAs):")
    roas_estrictos = len(df[df['Gap_Riesgo'] == 0])
    roas_holgados  = len(df[df['Gap_Riesgo'] > 0])

    print(f"ROAs Estrictos (Max-Length = Prefix-Length): {roas_estrictos:,} ({(roas_estrictos/total_roas)*100:.2f}%)")
    print(f"ROAs Holgados (Permiten subredes, mayor riesgo): {roas_holgados:,} ({(roas_holgados/total_roas)*100:.2f}%)")

    df.to_csv(archivo_salida, index=False)
    print(f"\nDataset limpio exportado a '{archivo_salida}'")

def exportar_roas_holgados(df, base_salida):
    """Exporta los ROAs con Gap_Riesgo > 0 en un CSV por versión IP."""
    columnas = ['Prefijo', 'ASN', 'Trust_Anchor', 'Prefijo_Base', 'Max_Length', 'Gap_Riesgo']
    for version in ['IPv4', 'IPv6']:
        df_holgados = df[(df['IP_Version'] == version) & (df['Gap_Riesgo'] > 0)][columnas]
        df_holgados = df_holgados.sort_values(['Trust_Anchor', 'Gap_Riesgo'], ascending=[True, False])
        salida = f"{base_salida}_{version.lower()}.csv"
        df_holgados.to_csv(salida, index=False)
        print(f"ROAs holgados {version}: {len(df_holgados):,} registros → {salida}")


if __name__ == "__main__":
    try:
        df_vrp = cargar_y_procesar_vrps(ARCHIVO_JSON)
        generar_estadisticas(df_vrp, ARCHIVO_SALIDA)
        exportar_roas_holgados(df_vrp, BASE_HOLGADOS)
    except FileNotFoundError:
        print(f"Error: No se encontró el archivo {ARCHIVO_JSON}. Debes exportarlo de tu validador.")


