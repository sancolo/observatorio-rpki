# Observatorio RPKI
import sys
import re
import subprocess
import pandas as pd


def extraer_rutas_mrt(archivo_mrt):
    """
    Parsea un RIB dump MRT usando bgpdump (apt install bgpdump).
    bgpdump expone el prefijo en notación CIDR completa, a diferencia de
    mrtparse 2.x que no almacena el prefix length para TABLE_DUMP_V2.
    """
    print(f"Procesando archivo MRT: {archivo_mrt}...")
    rutas = {}  # dict prefix -> asn para deduplicar en O(1)

    try:
        proc = subprocess.Popen(
            ['bgpdump', '-M', str(archivo_mrt)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True
        )

        for i, linea in enumerate(proc.stdout):
            # Formato bgpdump -M para TABLE_DUMP_V2:
            # TABLE_DUMP2|timestamp|B|peer_ip|peer_as|prefix|aspath|origin|...
            partes = linea.strip().split('|')
            if len(partes) < 7 or partes[0] != 'TABLE_DUMP2' or partes[2] != 'B':
                continue

            prefijo   = partes[5]
            as_path_str = partes[6]

            if not prefijo or '/' not in prefijo or not as_path_str.strip():
                continue

            # Extraemos todos los ASNs numéricos del path (maneja AS-sets como {12345,678})
            asns = re.findall(r'\d+', as_path_str)
            if not asns:
                continue

            asn_origen = asns[-1]
            plen = int(prefijo.split('/')[1])

            # Guardamos solo la primera ruta por prefijo (mejor ruta del RIB)
            if prefijo not in rutas:
                rutas[prefijo] = {'Prefijo_BGP': prefijo, 'Longitud_BGP': plen, 'ASN_BGP': asn_origen}

            if i % 500000 == 0 and i > 0:
                print(f"  Procesadas {i:,} líneas...")

        proc.wait()

    except FileNotFoundError:
        print("Error: bgpdump no está instalado. Instalá con: sudo apt install bgpdump")
        sys.exit(1)
    except Exception as e:
        print(f"Error procesando MRT: {e}")

    df_bgp = pd.DataFrame(rutas.values()) if rutas else pd.DataFrame(
        columns=['Prefijo_BGP', 'Longitud_BGP', 'ASN_BGP']
    )
    print(f"Extracción completa. Rutas únicas encontradas: {len(df_bgp):,}")
    return df_bgp


if __name__ == "__main__":
    archivo_rib    = sys.argv[1] if len(sys.argv) > 1 else "rib.20260601.0000.bz2"
    archivo_salida = sys.argv[2] if len(sys.argv) > 2 else "tabla_bgp_global.csv"
    df_internet = extraer_rutas_mrt(archivo_rib)
    df_internet.to_csv(archivo_salida, index=False)
    print(f"Tabla exportada a {archivo_salida}")
