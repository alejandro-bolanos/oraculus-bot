# OraculusBot 🤖

Bot de Zulip para competencias de machine learning tipo Kaggle con nuevo formato de datos.

## ✨ Características

- ✅ **Nuevo formato de datos**: Dataset maestro con columnas `id`, `clase_binaria`, `dataset`
- ✅ **Envíos simplificados**: Solo IDs predichos como positivos (sin matriz completa)
- ✅ **Submit desde Zulip**: Adjuntar archivos directamente en mensajes
- 📊 Cálculo de métricas usando matriz de ganancias personalizable
- 🏆 Sistema de badges y recompensas gamificado
- 👥 Roles diferenciados (estudiantes vs profesores)
- 📈 Leaderboards público y privado con fake submissions
- 🔒 Split automático público/privado desde datos maestros
- 📁 Gestión de archivos y detección de duplicados
- ⏰ Control de fechas límite
- 🧪 **Suite completa de tests** unitarios y de integración

## 🚀 Instalación

```bash
# Clonar el repositorio
git clone <repo-url>
cd oraculus-bot

# Instalar con uv (recomendado)
uv sync
```

## ⚙️ Configuración

### 1. Crear configuración inicial

```bash
# Generar archivo de configuración de ejemplo
uv run oraculus_bot.py --create-config
# o usando make
make run-config
```

### 2. Preparar datos maestros

**Nuevo formato requerido**: CSV con exactamente estas columnas:
- `id`: Identificador único del registro
- `clase_binaria`: Clase real (0 o 1)
- `dataset`: Split del dataset ("public" o "private")

```csv
id,clase_binaria,dataset
1,1,public
2,0,public
3,1,public
4,0,private
5,1,private
6,0,private
```

```bash
# Crear datos de demostración
make demo-data
```

### 3. Configurar Zulip

Edita `config.json` con tus credenciales de Zulip:

```json
{
  "zulip": {
    "email": "tu-bot@org.zulipchat.com",
    "api_key": "tu-api-key-aqui",
    "site": "https://tu-org.zulipchat.com"
  },
  "teachers": ["profesor1@uni.edu", "profesor2@uni.edu"],
  "master_data": {"path": "master_data.csv"}
}
```

## 🏃‍♂️ Uso

```bash
# Ejecutar el bot
uv run oraculus_bot.py --config mi_config.json
# o
make run
```

## 📝 Comandos

### Para Estudiantes

- `submit <nombre>` - Enviar modelo (adjuntar CSV con IDs positivos)
- `badges` - Ver badges ganados
- `list submits` - Listar envíos realizados
- `select <id>` - Seleccionar modelo para leaderboard final
- `help` - Mostrar ayuda

### Para Profesores

- `submit <nombre>` - Enviar y evaluar modelo (ver resultados completos)
- `duplicates` - Listar envíos duplicados por checksum
- `leaderboard full` - Leaderboard completo con scores privados
- `leaderboard public` - Leaderboard público
- `fake_submit add <nombre> <score>` - Agregar entrada falsa al leaderboard
- `fake_submit remove <nombre>` - Eliminar entrada falsa
- `help` - Mostrar ayuda para profesores

## 📄 Formato de Archivos

### Nuevo formato de envíos (CSV)

Los estudiantes deben enviar un CSV con **exactamente 1 columna sin encabezado**:
- Una fila por cada ID que predicen como **positivo** (clase 1)
- IDs que no aparecen en el archivo se consideran predichos como **negativos** (clase 0)

```csv
1
3
7
12
15
```

### Cómo enviar desde Zulip

1. **Comando en mensaje privado:**
   ```
   submit mi_modelo_v1
   ```

2. **Adjuntar archivo:** Usar el botón de adjuntar archivos en Zulip o arrastrar el CSV al chat

3. **El bot procesará automáticamente** el archivo adjunto y responderá con los resultados

## 🧪 Tests

El proyecto incluye una suite completa de tests unitarios y de integración.

```bash
# Instalar dependencias de desarrollo
make setup-dev

# Ejecutar todos los tests
make test

# Solo tests unitarios (rápidos)
make test-unit

# Solo tests de integración
make test-integration

# Tests con cobertura
make test-coverage

# Tests en modo watch (desarrollo)
make test-watch

# Verificación completa (lint + tests)
make check
```

## 🎯 Sistema de Badges

Badges automáticos incluidos:
- 🎯 **Primer Envío** - Tu primera submission
- ⭐ **Primera Selección** - Seleccionar tu primer modelo
- 🔟 **10 Envíos** - Alcanzar 10 submissions
- 🎖️ **50 Envíos** - Alcanzar 50 submissions  
- 💯 **100 Envíos** - Alcanzar 100 submissions
- 🥇 **Top 5 Público** - Estar en top 5 del leaderboard público
- 🚀 **Primer Umbral Alto** - Primera vez alcanzando umbral alto

## 📊 Matriz de Ganancias

Configurable en `config.json`:

```json
{
  "gain_matrix": {
    "tp": 100,  // Verdaderos positivos
    "tn": 10,   // Verdaderos negativos  
    "fp": -50,  // Falsos positivos
    "fn": -100  // Falsos negativos
  }
}
```

**Score = TP×100 + TN×10 + FP×(-50) + FN×(-100)**

## 🐍 Snippet para Jupyter Notebook

```python
import pandas as pd
import io
import zulip

def submit_to_oraculus(positive_ids, name, bot_email, user_email, api_key, site):
    """
    Envía lista de IDs positivos a OraculusBot
    
    Args:
        positive_ids: Lista o set de IDs predichos como positivos
        name: Nombre del modelo/envío
        bot_email: Email del bot de Zulip
        user_email: Tu email de Zulip
        api_key: Tu API key de Zulip
        site: URL del sitio Zulip
    """
    # Crear DataFrame con una columna
    df = pd.DataFrame(positive_ids, columns=['id'])
    
    client = zulip.Client(email=user_email, api_key=api_key, site=site)
    
    # Convertir a CSV bytes
    csv_data = io.BytesIO(df.to_csv(index=False, header=False).encode())
    
    # Subir archivo
    upload = client.upload_file(csv_data, filename=f"{name}.csv")
    if upload['result'] != 'success': 
        raise Exception(f"Upload error: {upload}")
    
    # Enviar mensaje con archivo adjunto
    msg = client.send_message({
        'type': 'private', 
        'to': bot_email,
        'content': f'submit {name}\n[{name}.csv]({upload["uri"]})'
    })
    if msg['result'] != 'success': 
        raise Exception(f"Send error: {msg}")
    
    print(f"✅ Modelo '{name}' enviado exitosamente!")

# Ejemplo de uso:
# positive_ids = [1, 3, 5, 7, 9, 12, 15]  # IDs que predices como clase 1
# submit_to_oraculus(
#     positive_ids, 
#     "mi_modelo_v1", 
#     "oraculus@org.zulipchat.com",
#     "tu-email@uni.edu", 
#     "tu-api-key", 
#     "https://org.zulipchat.com"
# )
```

## 🔧 Desarrollo

### Setup del entorno

```bash
# Instalar dependencias de desarrollo
make dev-install

# Pipeline completo de desarrollo  
make dev-test

# Formatear código
make format

# Verificar calidad
make lint

# Limpiar archivos temporales
make clean
```

### Estructura del proyecto

```
oraculus-bot/
├── oraculus_bot.py          # Bot principal
├── test_oraculus_bot.py     # Tests unitarios
├── test_integration.py      # Tests de integración  
├── pyproject.toml          # Configuración del proyecto
├── Makefile                # Comandos de desarrollo
├── config.json             # Configuración del bot
├── master_data.csv         # Datos maestros
├── logs/                   # Logs del bot
└── submissions/            # Archivos de envíos
```

## 📜 Licencia

MIT License - ver archivo [LICENSE](LICENSE) para detalles.

