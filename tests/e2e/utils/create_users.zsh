#!/bin/zsh

# Colores
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_error() { echo -e "${RED}❌ Error: $1${NC}" >&2; }
print_warn()  { echo -e "${YELLOW}⚠️  $1${NC}" >&2; }

# === Cargar .env si existe ===
if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

# === Verificar dependencias ===
for cmd in curl jq; do
  if ! command -v $cmd &> /dev/null; then
    print_error "Comando requerido no encontrado: $cmd"
    exit 1
  fi
done

# === Verificar variables de entorno ===
: ${ZULIP_SITE:?"ZULIP_SITE no está definida (en .env o entorno)"}
: ${ZULIP_EMAIL:?"ZULIP_EMAIL no está definida (en .env o entorno)"}
: ${ZULIP_API_KEY:?"ZULIP_API_KEY no está definida (en .env o entorno)"}

# === Verificar argumentos ===
if [[ $# -eq 0 ]]; then
  print_error "Uso: $0 \"email1=Nombre Completo\" \"email2=Otro Nombre\" ..."
  exit 1
fi

# === Inicializar array JSON de salida ===
OUTPUT_USERS=()
SUCCESS_COUNT=0

# === Procesar cada usuario ===
for arg in "$@"; do
  if [[ ! "$arg" == *"="* ]]; then
    print_warn "Formato inválido (saltando): $arg"
    OUTPUT_USERS+=( "$(jq -n \
      --arg email "$arg" \
      '{email: $email, full_name: null, created: false, error: "invalid_format"}')" )
    continue
  fi

  USER_EMAIL="${arg%%=*}"
  USER_FULL_NAME="${arg#*=}"

  # Validar email simple
  if [[ ! "$USER_EMAIL" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]]; then
    print_warn "Email inválido: $USER_EMAIL"
    OUTPUT_USERS+=( "$(jq -n \
      --arg email "$USER_EMAIL" \
      --arg name "$USER_FULL_NAME" \
      '{email: $email, full_name: $name, created: false, error: "invalid_email"}')" )
    continue
  fi

  # Endpoint
  CREATE_URL="${ZULIP_SITE}/api/v1/users"
  GET_APIKEY_URL="${ZULIP_SITE}/api/v1/fetch_api_key"

  # === Crear usuario ===
  RESPONSE=$(curl -k -sSX POST "$CREATE_URL" \
    -u "${ZULIP_EMAIL}:${ZULIP_API_KEY}" \
    -d "email=${USER_EMAIL}" \
    -d "full_name=${USER_FULL_NAME}" \
    -d "password=${USER_EMAIL}" )

  if echo "$RESPONSE" | jq -e '.result == "success"' >/dev/null; then
    print_success "✅ Creado: $USER_EMAIL"
    CREATED=true
  elif echo "$RESPONSE" | jq -e '.msg | contains("already")' >/dev/null; then q
    print_warn "Usuario ya existe: $USER_EMAIL"
    CREATED=false
  else
    print_warn "Error al crear $USER_EMAIL: $(echo "$RESPONSE" | jq -r '.msg // "unknown"')"
    OUTPUT_USERS+=( "$(jq -n \
      --arg email "$USER_EMAIL" \
      --arg name "$USER_FULL_NAME" \
      --arg msg "$(echo "$RESPONSE" | jq -r '.msg // "unknown error"')" \
      '{email: $email, full_name: $name, created: false, error: $msg}')" )
    continue
  fi

  # === Obtener API key ===
  KEY_RESPONSE=$(curl -k -sSX POST "$GET_APIKEY_URL" \
    --data-urlencode "username=${USER_EMAIL}"  \
    --data-urlencode "password=${USER_EMAIL}" )

  if ! echo "$KEY_RESPONSE" | jq -e '.result == "success"' >/dev/null; then
    print_warn "No se pudo obtener API key para $USER_EMAIL: $(echo "$KEY_RESPONSE" | jq -r '.msg // "unknown"')"
    OUTPUT_USERS+=( "$(jq -n \
      --arg email "$USER_EMAIL" \
      --arg name "$USER_FULL_NAME" \
      '{email: $email, full_name: $name, created: $CREATED, error: "failed_to_fetch_key"}')" )
    continue
  fi

  API_KEY=$(echo "$KEY_RESPONSE" | jq -r '.api_key')
  
  # Agregar al resultado
  OUTPUT_USERS+=( "$(jq -n \
    --arg email "$USER_EMAIL" \
    --arg name "$USER_FULL_NAME" \
    --arg key "$API_KEY" \
    --arg created "$CREATED" \
    '{email: $email, full_name: $name, created: $created, api_key: $key}')" )

  (( SUCCESS_COUNT++ ))
done

# === Generar salida JSON final ===
jq -n \
  --arg site "$ZULIP_SITE" \
  --arg admin_email "$ZULIP_EMAIL" \
  --argjson users "$(printf '%s\n' "${OUTPUT_USERS[@]}" | jq -s '.') " \
  --argjson total "${#OUTPUT_USERS[@]}" \
  --argjson success "$SUCCESS_COUNT" \
  '{
    "status": "success",
    "zulip_server": $site,
    "request_by": $admin_email,
    "total_processed": $total,
    "created_or_fetched": $success,
    "users": $users
  }'