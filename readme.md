# OraculusBot 🤖

Bot de Zulip para competencias de machine learning tipo Kaggle.

## Características

- ✅ Manejo de envíos de modelos con validación automática
- 📊 Cálculo de métricas usando matriz de ganancias personalizable
- 🏆 Sistema de badges y recompensas
- 👥 Roles diferenciados (estudiantes vs profesores)
- 📈 Leaderboards público y privado
- 🔒 Split automático público/privado con semilla configurable
- 📁 Gestión de archivos y detección de duplicados
- ⏰ Control de fechas límite

## Instalación

```bash
# Clonar el repositorio
git clone <repo-url>
cd oraculus-bot

# Instalar dependencias con uv
uv sync

# Crear configuración inicial
uv run oraculus_bot.py --create-config
```

## Configuración

1. Edita el archivo `config.json` generado con tus datos de Zulip y configuraciones de la competencia.

2. Prepara el archivo maestro CSV con dos columnas (id, etiqueta_real) sin encabezados.

3. Configura los profesores en la lista `teachers` del archivo de configuración.

## Uso

```bash
# Ejecutar el bot
uv run oraculus_bot.py

# Con archivo de configuración personalizado
uv run oraculus_bot.py --config mi_config.json
```

## Comandos para Estudiantes

- `submit <nombre>` - Enviar modelo (adjuntar CSV)
- `badges` - Ver badges ganados
- `list submits` - Listar envíos realizados
- `select <id>` - Seleccionar modelo para leaderboard
- `help` - Mostrar ayuda

## Comandos para Profesores

- `submit <nombre>` - Enviar y evaluar modelo (ver resultados completos)
- `duplicates` - Listar envíos duplicados
- `leaderboard full` - Leaderboard con scores privados
- `leaderboard public` - Leaderboard público
- `fake_submit add <nombre> <score>` - Agregar entrada falsa
- `fake_submit remove <nombre>` - Eliminar entrada falsa
- `help` - Mostrar ayuda

## Formato de CSV

Los archivos CSV deben tener exactamente 2 columnas sin encabezados:
- Columna 1: ID (debe coincidir exactamente con el archivo maestro)
- Columna 2: Predicción binaria (0 o 1)

## Sistema de Badges

El bot incluye badges automáticos para:
- 🎯 Primer envío
- ⭐ Primera selección de modelo
- 🔟 10, 50, 100 envíos
- 🥇 Top 5 en leaderboard público
- 🚀 Primer umbral alto alcanzado

## Snippet para Jupyter Notebook

```python
import pandas as pd
import io
import zulip

def submit_to_oraculus(df, name, bot_email, user_email, api_key, site):
    """Envía DataFrame a OraculusBot (2 cols: id, pred binaria)"""
    if df.shape[1] != 2 or not all(p in [0,1] for p in df.iloc[:,1]):
        raise ValueError("2 columnas requeridas, predicciones deben ser 0/1")
    
    client = zulip.Client(email=user_email, api_key=api_key, site=site)
    csv_data = io.BytesIO(df.to_csv(index=False, header=False).encode())
    
    upload = client.upload_file(csv_data, filename=f"{name}.csv")
    if upload['result'] != 'success': raise Exception(f"Upload error: {upload}")
    
    msg = client.send_message({
        'type': 'private', 'to': bot_email,
        'content': f'submit {name}\n[{name}.csv]({upload["uri"]})'
    })
    if msg['result'] != 'success': raise Exception(f"Send error: {msg}")
    
    print(f"✅ '{name}' enviado!")

# Uso:
# submit_to_oraculus(df, "modelo_v1", "bot@org.zulipchat.com", 
#                   "you@email.com", "your-key", "https://org.zulipchat.com")
```

## Licencia

MIT License - ver archivo LICENSE para detalles.