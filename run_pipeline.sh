#!/bin/bash
# Ejecución automática de un snapshot del Observatorio RPKI.
#
# Uso:
#   run_pipeline.sh [HHMM]
#
# HHMM: hora del RIB de RouteViews a procesar (default: 0000).
# RouteViews publica RIBs cada 2 horas: 0000, 0200, 0400, ..., 2200.
#
# Crontab sugerido para 6 snapshots diarios:
#   0  2 * * * /opt/observatorio_rpki/run_pipeline.sh 0000
#   0  4 * * * /opt/observatorio_rpki/run_pipeline.sh 0200
#   0  6 * * * /opt/observatorio_rpki/run_pipeline.sh 0400
#   0 14 * * * /opt/observatorio_rpki/run_pipeline.sh 1200
#   0 20 * * * /opt/observatorio_rpki/run_pipeline.sh 1800
#   0  2 * * * /opt/observatorio_rpki/run_pipeline.sh 0000  # (repetir el de medianoche)

set -e

# --- Función de descarga con fallback IPv4 ---
# Intenta la descarga sin restricción de IP (curl prefiere IPv6).
# Si falla o la velocidad cae por debajo de 1KB/s durante 120s, reintenta
# forzando IPv4. Retorna 0 si la descarga fue exitosa, 1 si ambos fallaron.
_curl_descarga() {
    local ip_flag="$1"
    local url="$2"
    local dest="$3"
    local label="${ip_flag:-(auto)}"
    echo "[descarga] Intentando con $label..." | tee -a "$LOG_FILE"
    curl \
        $ip_flag \
        --progress-bar \
        --location \
        --retry 2 \
        --retry-delay 30 \
        --connect-timeout 60 \
        --max-time 7200 \
        --speed-limit 1024 \
        --speed-time 120 \
        --write-out "\n[INFO] HTTP: %{http_code} | bytes: %{size_download} | velocidad: %{speed_download} B/s | tiempo: %{time_total}s\n" \
        -o "$dest" \
        "$url" \
        2>&1 | tee -a "$LOG_FILE"
    return ${PIPESTATUS[0]}
}

# --- Configuración ---
WORKSPACE_DIR="/opt/observatorio_rpki"
PYTHON_ENV="/opt/observatorio_rpki/venv/bin/python3"
ROUTINATOR_API="http://127.0.0.1:8323"
PUSHGATEWAY="localhost:9091"
DIAS_RETENCION=7   # días que se conservan los jobs en el Pushgateway

# --- Fecha y hora ---
# RouteViews usa timestamps UTC. Usamos date -u para que la fecha del RIB
# coincida con el nombre del archivo en el servidor, independientemente del
# huso horario local del servidor.
HHMM=${1:-0000}
YEAR=$(date -u +%Y)
MONTH=$(date -u +%m)
DAY=$(date -u +%d)
FECHA="${YEAR}${MONTH}${DAY}_${HHMM}"

# --- Rutas de archivos ---
mkdir -p "$WORKSPACE_DIR/logs" "$WORKSPACE_DIR/datos_crudos" "$WORKSPACE_DIR/datos_procesados"
LOG_FILE="$WORKSPACE_DIR/logs/pipeline_${FECHA}.log"

MRT_URL="http://archive.routeviews.org/bgpdata/${YEAR}.${MONTH}/RIBS/rib.${YEAR}${MONTH}${DAY}.${HHMM}.bz2"
MRT_FILE="$WORKSPACE_DIR/datos_crudos/rib_${FECHA}.bz2"
JSON_ROAS="$WORKSPACE_DIR/datos_crudos/vrps_${FECHA}.json"
CSV_BGP="$WORKSPACE_DIR/datos_procesados/tabla_bgp_${FECHA}.csv"
CSV_ENRIQUECIDA="$WORKSPACE_DIR/datos_procesados/internet_enriquecida_rpki_${FECHA}.csv"
CSV_INVALIDOS="$WORKSPACE_DIR/datos_procesados/prefijos_invalidos_${FECHA}.csv"
CSV_VRPS_GRAFICO="$WORKSPACE_DIR/datos_procesados/vrps_procesados_${FECHA}.csv"
BASE_HOLGADOS="$WORKSPACE_DIR/datos_procesados/roas_holgados_${FECHA}"
CSV_TOP10="$WORKSPACE_DIR/datos_procesados/top_10_infractores_${FECHA}.csv"
BASE_GRAFICOS="$WORKSPACE_DIR/datos_procesados/distribucion_loose_roas_${FECHA}"

echo "==================================================" >> $LOG_FILE
echo "[$(date +'%Y-%m-%d %H:%M:%S')] Iniciando Observatorio RPKI — snapshot $FECHA" >> $LOG_FILE

# --- 1. Ingesta de datos ---
echo "[1/4] Verificando disponibilidad del RIB en RouteViews..." | tee -a $LOG_FILE
echo "      URL: $MRT_URL" | tee -a $LOG_FILE

# Esperar hasta 1 hora (12 intentos cada 5 min) a que el archivo esté disponible.
# Usa HEAD (-I) para no descargar el cuerpo del archivo en la verificación.
# El "|| true" evita que set -e mate el script si curl falla (timeout, red, etc.)
INTENTOS=12
ESPERA=300   # segundos entre intentos
HTTP_STATUS="000"
for intento in $(seq 1 $INTENTOS); do
    HTTP_STATUS=$(curl -s --ipv4 -I -o /dev/null -w "%{http_code}" \
        --connect-timeout 15 --max-time 30 "$MRT_URL" 2>>"$LOG_FILE") || true
    echo "[1/4] Intento $intento/$INTENTOS — HTTP $HTTP_STATUS" | tee -a $LOG_FILE
    if [ "$HTTP_STATUS" = "200" ]; then
        echo "[1/4] Archivo disponible." | tee -a $LOG_FILE
        break
    fi
    echo "[1/4] No disponible aún. Reintentando en 5 min..." | tee -a $LOG_FILE
    sleep $ESPERA
done

if [ "$HTTP_STATUS" != "200" ]; then
    echo "[ERROR] Archivo RIB no disponible tras 1 hora (último HTTP: $HTTP_STATUS). Abortando." | tee -a $LOG_FILE
    exit 1
fi

echo "[1/4] Descargando RIB de RouteViews ($HHMM UTC)..." | tee -a $LOG_FILE
if ! _curl_descarga "" "$MRT_URL" "$MRT_FILE"; then
    echo "[1/4] Descarga falló (posible problema IPv6). Reintentando con IPv4..." | tee -a $LOG_FILE
    rm -f "$MRT_FILE"
    if ! _curl_descarga "--ipv4" "$MRT_URL" "$MRT_FILE"; then
        echo "[ERROR] La descarga falló con IPv4 y IPv6. Abortando." | tee -a $LOG_FILE
        rm -f "$MRT_FILE"
        exit 1
    fi
fi

# Verificar que el archivo descargado tenga tamaño razonable (>10MB)
FILESIZE=$(stat -c%s "$MRT_FILE" 2>/dev/null || echo 0)
if [ "$FILESIZE" -lt 10485760 ]; then
    echo "[ERROR] Archivo descargado demasiado pequeño (${FILESIZE} bytes). Posible descarga incompleta." | tee -a $LOG_FILE
    rm -f "$MRT_FILE"
    exit 1
fi
echo "[1/4] RIB descargado correctamente ($(( FILESIZE / 1048576 )) MB)." | tee -a $LOG_FILE

echo "[1/4] Extrayendo VRPs desde el validador RPKI local..." | tee -a $LOG_FILE
VRP_HTTP=$(curl -s -o "$JSON_ROAS" \
    --connect-timeout 30 --max-time 300 \
    -w "%{http_code}" \
    "$ROUTINATOR_API/json" 2>>"$LOG_FILE") || true
echo "[1/4] Routinator HTTP $VRP_HTTP | $(wc -c < "$JSON_ROAS" 2>/dev/null || echo 0) bytes" | tee -a "$LOG_FILE"
if [ "$VRP_HTTP" != "200" ]; then
    echo "[ERROR] No se pudo obtener VRPs de Routinator (HTTP $VRP_HTTP). ¿Está corriendo el servicio?" | tee -a "$LOG_FILE"
    echo "        Verificar con: systemctl status routinator  |  curl $ROUTINATOR_API/json" | tee -a "$LOG_FILE"
    rm -f "$JSON_ROAS"
    exit 1
fi
VRP_SIZE=$(wc -c < "$JSON_ROAS")
if [ "$VRP_SIZE" -lt 10240 ]; then
    echo "[ERROR] Archivo VRP demasiado pequeño (${VRP_SIZE} bytes). Routinator puede estar inicializando." | tee -a "$LOG_FILE"
    rm -f "$JSON_ROAS"
    exit 1
fi
echo "[1/4] VRPs extraídos correctamente ($(( VRP_SIZE / 1024 )) KB)." | tee -a "$LOG_FILE"

# --- 2. Procesamiento ---
echo "[2/4] Decodificando MRT binario a CSV..." | tee -a $LOG_FILE
$PYTHON_ENV $WORKSPACE_DIR/procesar_mrt.py $MRT_FILE $CSV_BGP >> $LOG_FILE 2>&1

# --- 3. Cruce BGP × RPKI ---
echo "[3/4] Ejecutando cruce criptográfico (Árbol Radix RFC 6811)..." | tee -a $LOG_FILE
$PYTHON_ENV $WORKSPACE_DIR/cruce_rpki_bgp.py $CSV_BGP $JSON_ROAS $CSV_ENRIQUECIDA $FECHA $PUSHGATEWAY $CSV_INVALIDOS >> $LOG_FILE 2>&1

# --- 4. Análisis y visualización ---
echo "[4/4] Generando hallazgos científicos y métricas..." | tee -a $LOG_FILE
$PYTHON_ENV $WORKSPACE_DIR/analisis_roas.py $JSON_ROAS $CSV_VRPS_GRAFICO $BASE_HOLGADOS >> $LOG_FILE 2>&1
$PYTHON_ENV $WORKSPACE_DIR/analisis_cientifico.py $CSV_ENRIQUECIDA $CSV_TOP10 $FECHA $PUSHGATEWAY >> $LOG_FILE 2>&1
$PYTHON_ENV $WORKSPACE_DIR/graficar_riesgo_discreto.py $CSV_VRPS_GRAFICO $BASE_GRAFICOS $FECHA $PUSHGATEWAY >> $LOG_FILE 2>&1

# --- 5. Limpieza de archivos locales ---
echo "[Limpieza] Rotando archivos crudos voluminosos..." | tee -a $LOG_FILE
rm -f $MRT_FILE $CSV_BGP
mv $JSON_ROAS "$WORKSPACE_DIR/datos_procesados/vrps_${FECHA}.json"

# --- 6. Limpieza de jobs viejos en el Pushgateway ---
# Eliminamos los jobs del snapshot de hace DIAS_RETENCION+1 días para mantener
# una ventana deslizante de DIAS_RETENCION días en Prometheus.
FECHA_PURGA=$(date -u -d "${DIAS_RETENCION} days ago" +%Y%m%d)
for HHMM_PURGA in 0000 0200 0400 0600 0800 1000 1200 1400 1600 1800 2000 2200; do
    FECHA_JOB="${FECHA_PURGA}_${HHMM_PURGA}"
    for JOB in observatorio_diario observatorio_infractores observatorio_estadistica observatorio_histogramas; do
        curl -s -X DELETE "http://${PUSHGATEWAY}/metrics/job/${JOB}_${FECHA_JOB}" || true
    done
done

echo "[$(date +'%Y-%m-%d %H:%M:%S')] Pipeline completado: snapshot $FECHA" >> $LOG_FILE
