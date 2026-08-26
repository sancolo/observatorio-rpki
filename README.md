# Observatorio de Seguridad del Enrutamiento Global — RPKI

Pipeline automatizado que cruza diariamente la tabla de enrutamiento BGP global contra la base de Autorizaciones de Origen de Rutas (ROAs) validada criptográficamente, implementando el algoritmo de Validación de Origen de Rutas (ROV) definido en el **RFC 6811**.

> Trabajo de investigación — Universidad Tecnológica Nacional, Facultad Regional Bahía Blanca.  
> Paper de referencia: *"Observatorio de Seguridad del Enrutamiento Global: Análisis de la Adopción de RPKI mediante Validación de Origen de Rutas a Escala de Internet"*

---

## ¿Qué hace este sistema?

1. **Descarga** un snapshot de la tabla de enrutamiento BGP global (RouteViews, ~900 MB comprimido).
2. **Parsea** el formato binario MRT (RFC 6396) extrayendo prefijo y ASN de origen de cada ruta.
3. **Valida** cada prefijo BGP contra todos los ROAs del repositorio RPKI global usando un Árbol Radix, clasificando cada ruta como `Valid`, `Invalid: Origin Mismatch`, `Invalid: Max-Length Exceeded` o `NotFound`.
4. **Analiza** la distribución de ROAs holgados (*Loose ROAs*, [RFC 9319](https://www.rfc-editor.org/rfc/rfc9319)) por Registro Regional de Internet (RIR).
5. **Identifica** los 10 ASNs con mayor cantidad de prefijos inválidos por Origin Mismatch, enriquecidos con datos de organización de PeeringDB.
6. **Exporta** métricas a Prometheus Pushgateway para visualización en Grafana (dashboards incluidos).
7. **Genera** figuras científicas: violin plots, heatmaps e histogramas de distribución de prefijos.

---

## Arquitectura

```
RouteViews MRT (.bz2)
        │
        ▼
  procesar_mrt.py          ← Parseo del snapshot BGP binario
        │
        ▼
  tabla_bgp.csv
        │
  vrps.json ───────────────┐
  (Routinator / API)        │
                            ▼
                    cruce_rpki_bgp.py   ← Árbol Radix + RFC 6811
                            │
                            ▼
               internet_enriquecida_rpki.csv
                            │
               ┌────────────┴────────────┐
               ▼                         ▼
   analisis_cientifico.py       analisis_roas.py
   Top 10 Origin Mismatch       Loose ROA analysis
               │                         │
               ▼                         ▼
   top_10_infractores.csv    vrps_procesados.csv
                                         │
                                         ▼
                             graficar_riesgo_discreto.py
                                         │
                                         ▼
                   violin_ipv4/ipv6.png, heatmap_ipv4/ipv6.png
                   hist_preflen_ipv4/ipv6.png, hist_maxlen_ipv4/ipv6.png

Todos los pasos → Prometheus Pushgateway → Grafana
```

---

## Requisitos

### Software

| Componente | Versión mínima | Notas |
|---|---|---|
| Python | 3.9+ | Ver `requirements.txt` |
| [Routinator](https://routinator.docs.nlnetlabs.nl/) | 0.12+ | Validador RPKI local (NLnet Labs) |
| Prometheus Pushgateway | 1.4+ | Para exportación de métricas |
| Grafana | 9.0+ | Para visualización (opcional) |

### Dependencias Python

```bash
pip install -r requirements.txt
```

Principales: `pandas`, `mrtparse`, `radix`, `prometheus-client`, `matplotlib`, `requests`.

---

## Fuentes de datos

### Tabla de enrutamiento BGP — RouteViews

El pipeline descarga automáticamente los archivos RIB del [Proyecto RouteViews](http://www.routeviews.org/) (Universidad de Oregon). Los snapshots se publican en formato MRT comprimido con bzip2 cada 2 horas, con un retardo de ~24 horas.

```
http://archive.routeviews.org/bgpdata/YYYY.MM/RIBS/rib.YYYYMMDD.HHMM.bz2
```

### Base de ROAs — Routinator

Los VRPs (*Validated ROA Payloads*) se obtienen del validador local Routinator, que descarga y verifica criptográficamente el repositorio de ROAs de los cinco RIRs (ARIN, RIPE NCC, LACNIC, APNIC, AFRINIC).

```bash
# Exportar VRPs en formato JSON (requiere routinator corriendo como servicio)
curl http://127.0.0.1:8323/json -o vrps.json
```

---

## Instalación

```bash
# 1. Clonar el repositorio
git clone https://github.com/[USUARIO]/observatorio-rpki.git
cd observatorio-rpki

# 2. Crear entorno virtual e instalar dependencias
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Instalar y configurar Routinator (ver documentación oficial)
# https://routinator.docs.nlnetlabs.nl/en/stable/installation.html

# 4. Instalar Prometheus Pushgateway
# https://github.com/prometheus/pushgateway
```

---

## Uso

### Modo producción — pipeline completo

```bash
# Ejecutar el snapshot de las 00:00 UTC
./run_pipeline.sh 0000

# Argumentos opcionales:
#   $1 = HHMM del RIB de RouteViews (default: 0000)
#        Valores válidos: 0000 0200 0400 0600 0800 1000
#                         1200 1400 1600 1800 2000 2200
```

El script realiza automáticamente:
- Espera hasta 1 hora (reintentos cada 5 min) a que el archivo RIB esté disponible en RouteViews
- Descarga con fallback IPv4 si la conexión IPv6 falla
- Ejecuta los 4 pasos del pipeline en secuencia
- Exporta métricas a Prometheus Pushgateway
- Rota logs y limpia archivos temporales

**Crontab sugerido** (6 snapshots diarios, 2 horas tras cada slot UTC):

```cron
0  2 * * * /opt/observatorio_rpki/run_pipeline.sh 0000
0  4 * * * /opt/observatorio_rpki/run_pipeline.sh 0200
0  6 * * * /opt/observatorio_rpki/run_pipeline.sh 0400
0 14 * * * /opt/observatorio_rpki/run_pipeline.sh 1200
0 20 * * * /opt/observatorio_rpki/run_pipeline.sh 1800
0 22 * * * /opt/observatorio_rpki/run_pipeline.sh 2000
```

### Modo desarrollo — scripts individuales

```bash
# Paso 1: Parsear MRT binario → CSV
python3 procesar_mrt.py <rib.bz2> <salida.csv>

# Paso 2: Cruce BGP × RPKI (RFC 6811)
python3 cruce_rpki_bgp.py <bgp.csv> <vrps.json> <salida.csv> <FECHA> <pushgateway> <invalidos.csv>

# Paso 3a: Análisis de ROAs (Loose ROAs por RIR)
python3 analisis_roas.py <vrps.json> <salida.csv> <base_holgados>

# Paso 3b: Hallazgos científicos (Top 10 Origin Mismatch + PeeringDB)
python3 analisis_cientifico.py <internet_enriquecida.csv> <top10.csv> <FECHA> <pushgateway>

# Paso 4: Generación de figuras
python3 graficar_riesgo_discreto.py <vrps_procesados.csv> <base_graficos> <FECHA> <pushgateway>
```

### Completar el paper con datos reales

```bash
# Llena los placeholders [PCT_VALID], [TOTAL_PREFIJOS], etc. del paper
python3 completar_paper.py
# Lee: internet_enriquecida_rpki.csv, vrps_procesados_para_grafico.csv, top_10_infractores.csv
# Genera: paper_rpki_completo.md
```

---

## Archivos de salida

| Archivo | Descripción |
|---|---|
| `tabla_bgp_FECHA.csv` | Tabla de enrutamiento parseada (Prefijo_BGP, ASN_BGP, Longitud_BGP) |
| `internet_enriquecida_rpki_FECHA.csv` | Tabla BGP con columna Estado_RPKI para cada prefijo |
| `prefijos_invalidos_FECHA.csv` | Solo prefijos con estado Invalid (Origin Mismatch + Max-Length) |
| `vrps_procesados_FECHA.csv` | ROAs con columnas IP_Version, Gap_Riesgo, Trust_Anchor |
| `roas_holgados_FECHA_ipv4.csv` | ROAs holgados IPv4 (Gap_Riesgo > 0) ordenados por gap desc |
| `roas_holgados_FECHA_ipv6.csv` | ROAs holgados IPv6 (Gap_Riesgo > 0) ordenados por gap desc |
| `top_10_infractores_FECHA.csv` | Top 10 ASNs por Origin Mismatch con nombre de organización |
| `distribucion_loose_roas_FECHA_violin_ipv4.png` | Violin plot del gap de riesgo por RIR — IPv4 |
| `distribucion_loose_roas_FECHA_violin_ipv6.png` | Violin plot del gap de riesgo por RIR — IPv6 |
| `distribucion_loose_roas_FECHA_heatmap_ipv4.png` | Heatmap gap × RIR (escala log) — IPv4 |
| `distribucion_loose_roas_FECHA_heatmap_ipv6.png` | Heatmap gap × RIR (escala log) — IPv6 |
| `distribucion_loose_roas_FECHA_hist_preflen_ipv4.png` | Histograma de longitudes de prefijo por RIR — IPv4 |
| `distribucion_loose_roas_FECHA_hist_preflen_ipv6.png` | Histograma de longitudes de prefijo por RIR — IPv6 |
| `distribucion_loose_roas_FECHA_hist_maxlen_ipv4.png` | Histograma de maxLength por RIR — IPv4 |
| `distribucion_loose_roas_FECHA_hist_maxlen_ipv6.png` | Histograma de maxLength por RIR — IPv6 |

---

## Dashboards de Grafana

El directorio `grafana/` contiene dos dashboards listos para importar:

| Archivo | Descripción |
|---|---|
| `dashboard_rpki.json` | Panel principal: estados RPKI por fecha, Top 10 ASNs, distribución de prefijos por RIR |
| `dashboard_tendencias.json` | Series temporales: evolución de rutas válidas/inválidas, ROAs holgados/exactos, PrefixLen > /24 y > /48 |

**Para importar en Grafana:**  
*Dashboards → New → Import → subir el archivo JSON*

Los dashboards asumen Prometheus como datasource con métricas publicadas por el pipeline al Pushgateway.

---

## Contexto científico

### El problema de los Loose ROAs (RFC 9319)

Un ROA es **holgado** (*non-minimal*) cuando su `maxLength` es mayor que su `prefixLength`. El [RFC 9319](https://www.rfc-editor.org/rfc/rfc9319) (BCP 185, octubre 2022) establece que los operadores **SHOULD** evitar esta configuración, ya que habilita el *forged-origin sub-prefix attack*:

- En **IPv4**: un ROA con `prefixLength=/16` y `maxLength=/24` cubre implícitamente 2⁸ = 256 sub-prefijos.
- En **IPv6**: un ROA con `prefixLength=/32` y `maxLength=/48` (esquema típico ISP→cliente) cubre 2¹⁶ = 65.536 sub-redes `/48`.

Un adversario que anuncie cualquiera de esos sub-prefijos con el ASN correcto obtendrá estado `Valid` en ROV y será preferido por especificidad en BGP, redirigiendo tráfico de forma indetectable.

### Algoritmo implementado

El cruce BGP × RPKI sigue exactamente el procedimiento del RFC 6811, usando un Árbol Radix para búsquedas `search_covering` en O(log n). La política de validación es la más permisiva: basta un único ROA cubriente con ASN y longitud válidos para clasificar una ruta como `Valid`.

---

## Citar este trabajo

```bibtex
@article{observatorio_rpki_2026,
  title   = {Observatorio de Seguridad del Enrutamiento Global: Análisis de la
             Adopción de RPKI mediante Validación de Origen de Rutas a Escala de Internet},
  author  = {[NOMBRE APELLIDO]},
  institution = {Universidad Tecnológica Nacional -- Facultad Regional Bahía Blanca},
  year    = {2026},
  url     = {https://github.com/[USUARIO]/observatorio-rpki}
}
```

---

## Referencias normativas

- [RFC 4271](https://www.rfc-editor.org/rfc/rfc4271) — BGP-4
- [RFC 6480](https://www.rfc-editor.org/rfc/rfc6480) — An Infrastructure to Support Secure Internet Routing (RPKI)
- [RFC 6811](https://www.rfc-editor.org/rfc/rfc6811) — Route Origin Validation (ROV)
- [RFC 6396](https://www.rfc-editor.org/rfc/rfc6396) — Multi-Threaded Routing Toolkit (MRT) Routing Information Export Format
- [RFC 9319](https://www.rfc-editor.org/rfc/rfc9319) — The Use of maxLength in the RPKI (BCP 185)

---

## Licencia

MIT License — libre para uso académico y comercial con atribución.
