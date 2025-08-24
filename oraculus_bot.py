#!/usr/bin/env python3
"""
OraculusBot - Bot de Zulip para competencias tipo Kaggle
Ejecutar con: uv run oraculus_bot.py
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import zulip
from sklearn.metrics import confusion_matrix


# Configurar adaptadores de datetime para SQLite (Python 3.12+)
def adapt_datetime(dt):
    """Convertir datetime a string para SQLite"""
    return dt.isoformat()


def convert_datetime(s):
    """Convertir string de SQLite a datetime"""
    return datetime.fromisoformat(s.decode())


# Registrar adaptadores
sqlite3.register_adapter(datetime, adapt_datetime)
sqlite3.register_converter("datetime", convert_datetime)


class OraculusBot:
    def __init__(self, config_path: str):
        self.config = self._load_config(config_path)

        # Configurar logging
        self._setup_logging()

        self.logger.info(f"Iniciando OraculusBot con configuración: {config_path}")

        self.client = zulip.Client(
            email=self.config["zulip"]["email"],
            api_key=self.config["zulip"]["api_key"],
            site=self.config["zulip"]["site"],
        )
        self.db_path = self.config["database"]["path"]

        self.logger.info(f"Conectado a Zulip como {self.config['zulip']['email']}")
        self.logger.info(f"Base de datos: {self.db_path}")

        self.init_database()
        self.load_master_data()

    def _setup_logging(self):
        """Configura el sistema de logging"""
        # Crear directorio de logs si no existe
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        # Configurar formato de log
        log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

        # Configurar logger principal
        self.logger = logging.getLogger("OraculusBot")
        self.logger.setLevel(logging.INFO)

        # Handler para archivo
        file_handler = logging.FileHandler(
            log_dir / f"oraculus_bot_{datetime.now().strftime('%Y%m%d')}.log",
            encoding="utf-8",
        )
        file_handler.setLevel(logging.INFO)
        file_formatter = logging.Formatter(log_format)
        file_handler.setFormatter(file_formatter)

        # Handler para consola
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        console_handler.setFormatter(console_formatter)

        # Agregar handlers
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

        # Evitar duplicación de logs
        self.logger.propagate = False

    def _load_config(self, config_path: str) -> dict:
        """Carga la configuración desde archivo JSON"""
        try:
            with open(config_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            # Como el logger aún no está configurado, usamos logging básico
            logging.basicConfig(level=logging.ERROR)
            logging.error(f"Error cargando configuración: {e}")
            raise

    def _get_db_connection(self):
        """Obtener conexión a la base de datos con configuración apropiada"""
        return sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES)

    def init_database(self):
        """Inicializa la base de datos SQLite"""
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()

            # Tabla de envíos
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    user_email TEXT,
                    user_full_name TEXT,
                    submission_name TEXT,
                    timestamp DATETIME,
                    file_checksum TEXT,
                    file_path TEXT,
                    public_score REAL,
                    private_score REAL,
                    tp INTEGER,
                    tn INTEGER,
                    fp INTEGER,
                    fn INTEGER,
                    positives_predicted INTEGER,
                    threshold_category TEXT,
                    is_selected BOOLEAN DEFAULT FALSE
                )
            """
            )

            # Tabla de badges
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_badges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    badge_name TEXT,
                    earned_at DATETIME,
                    UNIQUE(user_id, badge_name)
                )
            """
            )

            # Tabla de fake submissions
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS fake_submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE,
                    public_score REAL,
                    threshold_category TEXT
                )
            """
            )

            conn.commit()
            conn.close()

            self.logger.info("Base de datos inicializada correctamente")

        except Exception as e:
            self.logger.error(f"Error inicializando base de datos: {e}")
            raise

    def load_master_data(self):
        """Carga los datos maestros con nuevo formato (id, clase_binaria, dataset)"""
        try:
            master_path = self.config["master_data"]["path"]
            self.master_df = pd.read_csv(master_path)

            # Validar columnas requeridas
            expected_cols = ["id", "clase_binaria", "dataset"]
            if not all(col in self.master_df.columns for col in expected_cols):
                raise ValueError(f"El archivo maestro debe tener columnas: {expected_cols}")

            # Crear conjuntos público y privado
            public_mask = self.master_df["dataset"] == "public"
            private_mask = self.master_df["dataset"] == "private"

            self.public_df = self.master_df[public_mask].copy()
            self.private_df = self.master_df[private_mask].copy()

            # Crear conjuntos de IDs para validación
            self.public_ids = set(self.public_df["id"])
            self.private_ids = set(self.private_df["id"])
            self.all_ids = set(self.master_df["id"])

            # Obtener IDs positivos (clase_binaria = 1) para validar submissions
            self.positive_ids = set(self.master_df[self.master_df["clase_binaria"] == 1]["id"])

            self.logger.info(f"Datos maestros cargados: {len(self.master_df)} registros")
            self.logger.info(f"Público: {len(self.public_df)}, Privado: {len(self.private_df)}")
            self.logger.info(f"IDs positivos totales: {len(self.positive_ids)}")

        except Exception as e:
            self.logger.error(f"Error cargando datos maestros: {e}")
            raise

    def calculate_scores(self, predicted_positive_ids: set[int]) -> tuple[dict, dict]:
        """Calcula scores público y privado usando matriz de ganancias"""
        gain_matrix = self.config["gain_matrix"]

        def calculate_score_for_dataset(dataset_df):
            """Calcula métricas para un dataset específico"""
            if len(dataset_df) == 0:
                return {"score": 0, "tp": 0, "tn": 0, "fp": 0, "fn": 0}

            # Crear vectores de predicción basados en IDs
            true_labels = dataset_df["clase_binaria"].values

            # Predecir 1 si el ID está en predicted_positive_ids, 0 si no
            predicted_labels = [
                1 if id_ in predicted_positive_ids else 0 for id_ in dataset_df["id"]
            ]

            # Calcular matriz de confusión
            cm = confusion_matrix(true_labels, predicted_labels, labels=[0, 1])
            tn, fp, fn, tp = cm.ravel()

            # Calcular score usando matriz de ganancias
            score = (
                tp * gain_matrix["tp"]
                + tn * gain_matrix["tn"]
                + fp * gain_matrix["fp"]
                + fn * gain_matrix["fn"]
            )

            return {
                "score": score,
                "tp": int(tp),
                "tn": int(tn),
                "fp": int(fp),
                "fn": int(fn),
            }

        public_results = calculate_score_for_dataset(self.public_df)
        private_results = calculate_score_for_dataset(self.private_df)

        return public_results, private_results

    def get_threshold_category(self, score: float) -> str:
        """Determina la categoría basada en umbrales de ganancia"""
        thresholds = self.config["gain_thresholds"]
        for threshold in sorted(thresholds, key=lambda x: x["min_score"], reverse=True):
            if score >= threshold["min_score"]:
                return threshold["category"]
        return thresholds[-1]["category"]  # Categoría más baja por defecto

    def save_submission(
        self,
        user_info: dict,
        submission_name: str,
        file_path: str,
        checksum: str,
        public_results: dict,
        private_results: dict,
        positives_predicted: int,
        threshold_category: str,
    ):
        """Guarda un envío en la base de datos"""
        conn = self._get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO submissions (
                user_id, user_email, user_full_name, submission_name,
                timestamp, file_checksum, file_path, public_score, private_score,
                tp, tn, fp, fn, positives_predicted, threshold_category
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                user_info["user_id"],
                user_info["email"],
                user_info["full_name"],
                submission_name,
                datetime.now(),
                checksum,
                file_path,
                float(public_results["score"]),
                float(private_results["score"]),
                private_results["tp"],
                private_results["tn"],
                private_results["fp"],
                private_results["fn"],
                positives_predicted,
                threshold_category,
            ),
        )

        submission_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return submission_id

    def check_and_award_badges(
        self,
        user_id: int,
        submission_count: int,
        public_score: float,
        is_first_selection: bool = False,
    ):
        """Verifica y otorga badges basado en logros"""
        conn = self._get_db_connection()
        cursor = conn.cursor()

        badges_to_award = []

        # Badge primer envío
        if submission_count == 1:
            badges_to_award.append("first_submission")

        # Badge primera selección de modelo
        if is_first_selection:
            badges_to_award.append("first_model_selection")

        # Badges por cantidad de envíos
        badge_thresholds = [
            (10, "submissions_10"),
            (50, "submissions_50"),
            (100, "submissions_100"),
        ]
        for threshold, badge_name in badge_thresholds:
            if submission_count == threshold:
                badges_to_award.append(badge_name)

        # Badge top 5 público
        cursor.execute(
            """
            SELECT COUNT(*) FROM submissions
            WHERE public_score > ? AND is_selected = TRUE
        """,
            (public_score,),
        )
        rank = cursor.fetchone()[0] + 1

        if rank <= 5:
            badges_to_award.append("top_5_public")

        # Badge primer umbral alto
        thresholds = sorted(
            self.config["gain_thresholds"], key=lambda x: x["min_score"], reverse=True
        )
        if len(thresholds) > 1 and public_score >= thresholds[1]["min_score"]:
            cursor.execute(
                "SELECT COUNT(*) FROM submissions WHERE user_id = ? AND public_score >= ?",
                (user_id, thresholds[1]["min_score"]),
            )
            if cursor.fetchone()[0] == 1:  # Primera vez alcanzando este umbral
                badges_to_award.append("high_threshold_first")

        # Insertar badges nuevos
        new_badges = []
        for badge_name in badges_to_award:
            try:
                cursor.execute(
                    """
                    INSERT INTO user_badges (user_id, badge_name, earned_at)
                    VALUES (?, ?, ?)
                """,
                    (user_id, badge_name, datetime.now()),
                )
                new_badges.append(badge_name)
            except sqlite3.IntegrityError:
                pass  # Badge ya existe

        conn.commit()
        conn.close()

        return new_badges

    def _extract_file_from_message(self, message: dict) -> tuple[str | None, bytes | None]:
        """Extraer archivo adjunto del mensaje de Zulip"""
        content = message["content"]

        # Buscar archivos adjuntos en el mensaje
        # Patrón para enlaces de archivos de Zulip: [filename](url)
        file_pattern = r"\[([^\]]+\.csv)\]\(([^)]+)\)"
        matches = re.findall(file_pattern, content, re.IGNORECASE)

        if not matches:
            return None, None

        filename, file_url = matches[0]

        try:
            # Si es una URL de Zulip, usar las credenciales del bot
            if self.config["zulip"]["site"] in file_url:
                # Usar la API de Zulip para descargar el archivo
                response = requests.get(
                    file_url, auth=(self.config["zulip"]["email"], self.config["zulip"]["api_key"])
                )
            else:
                # URL externa
                response = requests.get(file_url)

            response.raise_for_status()
            return filename, response.content

        except Exception as e:
            self.logger.error(f"Error descargando archivo desde {file_url}: {e}")
            return None, None

    def _save_submission_file(
        self,
        user_id: int,
        submission_name: str,
        filename: str,
        content: bytes,
        is_teacher: bool = False,
    ) -> str:
        """Guarda el archivo de envío en el sistema de archivos"""
        base_path = Path(self.config["submissions"]["path"])

        if is_teacher:
            user_dir = base_path / "teachers" / str(user_id)
        else:
            user_dir = base_path / "students" / str(user_id)

        user_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(
            c for c in submission_name if c.isalnum() or c in (" ", "-", "_")
        ).rstrip()
        file_path = user_dir / f"{timestamp}_{safe_name}_{filename}"

        with open(file_path, "wb") as f:
            f.write(content)

        return str(file_path)

    def process_submit(self, message: dict, is_teacher: bool = False) -> str:
        """Procesa comando submit"""
        user_email = message["sender_email"]
        submission_name = ""

        try:
            self.logger.info(f"Procesando submit de {user_email} (profesor: {is_teacher})")

            # Verificar fecha límite (solo para estudiantes)
            if not is_teacher:
                deadline = datetime.fromisoformat(self.config["competition"]["deadline"])
                if datetime.now() > deadline:
                    self.logger.warning(f"Envío fuera de fecha límite de {user_email}")
                    return "❌ La fecha límite para envíos ha expirado"

            # Extraer nombre del envío
            parts = message["content"].strip().split(" ", 1)
            if len(parts) < 2:
                return (
                    "❌ Formato incorrecto. Uso: `submit <nombre_envio>` y adjunta el archivo CSV"
                )

            submission_name = parts[1].split("\n")[0].strip()  # Tomar solo la primera línea
            self.logger.info(f"Nombre del envío: {submission_name}")

            # Extraer archivo del mensaje
            filename, file_content = self._extract_file_from_message(message)

            if not file_content:
                return "❌ Debes adjuntar un archivo CSV. Usa el formato: `submit <nombre>` y adjunta el archivo CSV."

            if not filename.lower().endswith(".csv"):
                return "❌ El archivo debe ser un CSV"

            # Guardar archivo
            file_path = self._save_submission_file(
                message["sender_id"], submission_name, filename, file_content, is_teacher
            )

            # Calcular checksum
            checksum = hashlib.sha256(file_content).hexdigest()
            self.logger.info(f"Archivo guardado: {file_path}, checksum: {checksum[:16]}...")

            # Leer y validar CSV
            try:
                df = pd.read_csv(file_path, header=None)
            except Exception as e:
                return f"❌ Error leyendo el archivo CSV: {e!s}"

            # Validar que tenga exactamente una columna (IDs)
            if df.shape[1] != 1:
                self.logger.warning(
                    f"CSV con formato incorrecto de {user_email}: {df.shape[1]} columnas"
                )
                return "❌ El CSV debe tener exactamente 1 columna con los IDs predichos como positivos"

            # Obtener IDs predichos como positivos
            predicted_positive_ids = set(df.iloc[:, 0].astype(int))

            # Validar que todos los IDs existan en el dataset maestro
            invalid_ids = predicted_positive_ids - self.all_ids
            if invalid_ids:
                self.logger.warning(f"IDs inválidos en envío de {user_email}")
                return (
                    f"❌ IDs inválidos encontrados: {len(invalid_ids)} IDs no existen en el dataset"
                )

            # Calcular scores
            self.logger.info(f"Calculando scores para {submission_name}")
            public_results, private_results = self.calculate_scores(predicted_positive_ids)
            threshold_category = self.get_threshold_category(public_results["score"])
            positives_predicted = len(predicted_positive_ids)

            self.logger.info(
                f"Scores calculados - Público: {public_results['score']:.4f}, Privado: {private_results['score']:.4f}"
            )

            user_info = {
                "user_id": message["sender_id"],
                "email": message["sender_email"],
                "full_name": message["sender_full_name"],
            }

            if is_teacher:
                # Para profesores: solo mostrar resultados
                self.logger.info(f"Envío de profesor completado: {submission_name}")
                response = f"📊 **Resultados para {submission_name}**\n\n"
                response += f"📊 **Público:** {public_results['score']:.4f}\n"
                response += f"🔒 **Privado:** {private_results['score']:.4f}\n"
                response += f"🎯 **Categoría:** {threshold_category}\n"
                response += f"📈 **Positivos predichos:** {positives_predicted}\n"
                response += f"🔢 **Matriz confusión privada:** TP={private_results['tp']}, TN={private_results['tn']}, FP={private_results['fp']}, FN={private_results['fn']}\n"
                return response
            else:
                # Para estudiantes: guardar y otorgar badges
                submission_id = self.save_submission(
                    user_info,
                    submission_name,
                    file_path,
                    checksum,
                    public_results,
                    private_results,
                    positives_predicted,
                    threshold_category,
                )

                self.logger.info(f"Envío guardado con ID: {submission_id}")

                # Contar envíos del usuario
                conn = self._get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT COUNT(*) FROM submissions WHERE user_id = ?",
                    (message["sender_id"],),
                )
                submission_count = cursor.fetchone()[0]
                conn.close()

                # Verificar badges
                new_badges = self.check_and_award_badges(
                    message["sender_id"], submission_count, public_results["score"]
                )

                if new_badges:
                    self.logger.info(f"Nuevos badges otorgados a {user_email}: {new_badges}")

                # Obtener configuración de respuesta por umbral
                threshold_config = next(
                    t for t in self.config["gain_thresholds"] if t["category"] == threshold_category
                )

                response = (
                    f"🎯 **{threshold_config['message']}** {threshold_config.get('emoji', '')}\n\n"
                )
                response += f"🆔 **ID Envío:** {submission_id}\n"
                response += f"📊 **Score Público:** {public_results['score']:.4f}\n"
                response += f"📈 **Positivos Predichos:** {positives_predicted}\n"

                if new_badges:
                    badge_configs = self.config.get("badges", {})
                    response += "\n🏆 **Nuevos Badges:**\n"
                    for badge in new_badges:
                        badge_info = badge_configs.get(badge, {"name": badge, "emoji": "🏅"})
                        response += f"{badge_info['emoji']} {badge_info['name']}\n"

                return response

        except Exception as e:
            self.logger.error(f"Error procesando envío '{submission_name}' de {user_email}: {e}")
            return f"❌ Error procesando envío: {e!s}"

    def process_badges(self, user_id: int) -> str:
        """Lista badges del usuario"""
        conn = self._get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT badge_name, earned_at FROM user_badges
            WHERE user_id = ? ORDER BY earned_at DESC
        """,
            (user_id,),
        )

        badges = cursor.fetchall()
        conn.close()

        if not badges:
            return "🏆 No tienes badges aún. ¡Sigue enviando modelos para ganarlos!"

        response = "🏆 **Tus Badges:**\n\n"
        badge_configs = self.config.get("badges", {})

        for badge_name, earned_at in badges:
            badge_info = badge_configs.get(badge_name, {"name": badge_name, "emoji": "🏅"})
            date_str = earned_at.strftime("%d/%m/%Y")
            response += f"{badge_info['emoji']} **{badge_info['name']}** - {date_str}\n"

        return response

    def process_list_submits(self, user_id: int) -> str:
        """Lista envíos del usuario"""
        conn = self._get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, submission_name, timestamp, public_score,
                   threshold_category, is_selected FROM submissions
            WHERE user_id = ? ORDER BY timestamp DESC
        """,
            (user_id,),
        )

        submissions = cursor.fetchall()
        conn.close()

        if not submissions:
            return "📋 No tienes envíos registrados"

        response = "📋 **Tus Envíos:**\n\n"
        for sub in submissions:
            selected_mark = "⭐" if sub[5] else ""
            response += f"`{sub[0]}` - **{sub[1]}** {selected_mark}\n"
            response += f"   📅 {sub[2]} | 🎯 {sub[4]}\n\n"

        return response

    def process_select(self, user_id: int, message_content: str) -> str:
        """Selecciona un modelo para el leaderboard"""
        try:
            parts = message_content.strip().split(" ", 1)
            if len(parts) < 2:
                return "❌ Formato incorrecto. Uso: `select <id_submit>`"

            submission_id = int(parts[1])

            conn = self._get_db_connection()
            cursor = conn.cursor()

            # Verificar que el envío existe y pertenece al usuario
            cursor.execute(
                """
                SELECT id FROM submissions
                WHERE id = ? AND user_id = ?
            """,
                (submission_id, user_id),
            )

            if not cursor.fetchone():
                conn.close()
                return "❌ Envío no encontrado o no te pertenece"

            # Desmarcar selección anterior
            cursor.execute(
                """
                UPDATE submissions SET is_selected = FALSE
                WHERE user_id = ?
            """,
                (user_id,),
            )

            # Marcar nueva selección
            cursor.execute(
                """
                UPDATE submissions SET is_selected = TRUE
                WHERE id = ? AND user_id = ?
            """,
                (submission_id, user_id),
            )

            # Verificar si es la primera selección para badge
            cursor.execute(
                """
                SELECT COUNT(*) FROM user_badges
                WHERE user_id = ? AND badge_name = 'first_model_selection'
            """,
                (user_id,),
            )

            is_first_selection = cursor.fetchone()[0] == 0

            conn.commit()
            conn.close()

            # Otorgar badge si es primera selección
            if is_first_selection:
                self.check_and_award_badges(user_id, 0, 0, is_first_selection=True)
                return f"✅ Modelo {submission_id} seleccionado\n🏆 ¡Badge desbloqueado: Primera Selección de Modelo!"

            return f"✅ Modelo {submission_id} seleccionado para el leaderboard"

        except ValueError:
            return "❌ El ID del envío debe ser un número"
        except Exception as e:
            return f"❌ Error: {e!s}"

    def process_duplicates(self) -> str:
        """Lista envíos duplicados (solo profesores)"""
        conn = self._get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT file_checksum, COUNT(*),
                   GROUP_CONCAT(DISTINCT user_email) as users,
                   GROUP_CONCAT(submission_name) as names
            FROM submissions
            GROUP BY file_checksum
            HAVING COUNT(DISTINCT user_id) > 1
        """
        )

        duplicates = cursor.fetchall()
        conn.close()

        if not duplicates:
            return "✅ No se encontraron envíos duplicados"

        response = "🔍 **Envíos Duplicados:**\n\n"
        for checksum, _count, users, names in duplicates:
            response += f"**Checksum:** `{checksum[:16]}...`\n"
            response += f"**Usuarios:** {users}\n"
            response += f"**Envíos:** {names}\n\n"

        return response

    def process_leaderboard_full(self) -> str:
        """Leaderboard completo (solo profesores)"""
        conn = self._get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            WITH user_stats AS (
                SELECT
                    user_id,
                    user_full_name,
                    user_email,
                    COUNT(*) as total_submissions,
                    MAX(CASE WHEN is_selected = 1 THEN private_score END) as selected_private_score,
                    MAX(private_score) as best_private_score,
                    MAX(public_score) as best_public_score
                FROM submissions
                GROUP BY user_id, user_full_name, user_email
            ),
            final_scores AS (
                SELECT
                    *,
                    COALESCE(selected_private_score, best_private_score) as final_score
                FROM user_stats
            )
            SELECT
                user_full_name,
                final_score,
                total_submissions,
                best_public_score,
                best_private_score
            FROM final_scores
            ORDER BY final_score DESC
        """
        )

        results = cursor.fetchall()
        conn.close()

        if not results:
            return "📊 No hay submissions en el leaderboard"

        response = f"🏆 **Leaderboard Completo - {self.config['competition']['name']}**\n\n"
        response += "| Pos | Nombre | Score Final | Envíos | Mejor Público | Mejor Privado |\n"
        response += "|---|---|---|---|---|---|\n"

        for i, (name, final_score, count, best_public, best_private) in enumerate(results, 1):
            response += f"| {i} | {name} | {final_score:.4f} | {count} | {best_public:.4f} | {best_private:.4f} |\n"

        return response

    def process_leaderboard_public(self) -> str:
        """Leaderboard público"""
        conn = self._get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            WITH real_submissions AS (
                SELECT
                    user_full_name as name,
                    MAX(public_score) as best_public
                FROM submissions
                GROUP BY user_id, user_full_name
            ),
            fake_submissions_ AS (
                SELECT
                    name,
                    public_score as best_public
                FROM fake_submissions
            ),
            combined AS (
                SELECT name, best_public FROM real_submissions
                UNION ALL
                SELECT name, best_public FROM fake_submissions_
            )
            SELECT name, best_public
            FROM combined
            ORDER BY best_public DESC
        """
        )

        results = cursor.fetchall()
        conn.close()

        if not results:
            return "📊 No hay submissions en el leaderboard público"

        response = f"🌟 **Leaderboard Público - {self.config['competition']['name']}**\n\n"
        response += "| Pos | Nombre | Score | Categoría |\n"
        response += "|---|---|---|---|\n"

        for i, (name, score) in enumerate(results, 1):
            category = self.get_threshold_category(score)
            response += f"| {i} | {name} | {score:.4f} | {category.title()} |\n"

        return response

    def process_fake_submit(self, message_content: str) -> str:
        """Maneja fake submissions (solo profesores)"""
        parts = message_content.strip().split()

        if len(parts) < 2:
            return "❌ Formato incorrecto. Uso: `fake_submit add <name> <public_score>` o `fake_submit remove <name>`"

        action = parts[1]

        if action == "add":
            if len(parts) < 4:
                return "❌ Formato incorrecto. Uso: `fake_submit add <name> <public_score>`"

            name = parts[2]
            try:
                public_score = float(parts[3])
            except ValueError:
                return "❌ El score público debe ser un número"

            category = self.get_threshold_category(public_score)

            conn = self._get_db_connection()
            cursor = conn.cursor()

            try:
                cursor.execute(
                    """
                    INSERT INTO fake_submissions (name, public_score, threshold_category)
                    VALUES (?, ?, ?)
                """,
                    (name, public_score, category),
                )
                conn.commit()
                conn.close()
                return f"✅ Fake submission agregado: {name} con score {public_score:.4f}"
            except sqlite3.IntegrityError:
                conn.close()
                return "❌ Ya existe un fake submission con ese nombre"

        elif action == "remove":
            if len(parts) < 3:
                return "❌ Formato incorrecto. Uso: `fake_submit remove <name>`"

            name = parts[2]

            conn = self._get_db_connection()
            cursor = conn.cursor()

            cursor.execute("DELETE FROM fake_submissions WHERE name = ?", (name,))

            if cursor.rowcount > 0:
                conn.commit()
                conn.close()
                return f"✅ Fake submission '{name}' eliminado"
            else:
                conn.close()
                return "❌ No se encontró un fake submission con ese nombre"

        return "❌ Acción no válida. Use 'add' o 'remove'"

    def get_help_message(self, is_teacher: bool) -> str:
        """Genera mensaje de ayuda"""
        competition = self.config["competition"]

        if is_teacher:
            return f"""🤖 **OraculusBot - Ayuda para Profesores**

**Competencia:** {competition["name"]}
**Descripción:** {competition["description"]}
**Fecha límite:** {competition["deadline"]}

**Comandos disponibles:**
• `submit <nombre>` - Enviar modelo y ver resultados completos
• `duplicates` - Listar envíos duplicados
• `leaderboard full` - Leaderboard completo con scores privados
• `leaderboard public` - Leaderboard público
• `fake_submit add <name> <score>` - Agregar entrada falsa al leaderboard
• `fake_submit remove <name>` - Eliminar entrada falsa
• `help` - Mostrar esta ayuda"""
        else:
            return f"""🤖 **OraculusBot - Ayuda para Estudiantes**

**Competencia:** {competition["name"]}
**Descripción:** {competition["description"]}
**Fecha límite:** {competition["deadline"]}

**Comandos disponibles:**
• `submit <nombre>` - Enviar modelo (adjuntar CSV)
• `badges` - Ver tus badges ganados
• `list submits` - Listar tus envíos
• `select <id>` - Seleccionar modelo para leaderboard
• `help` - Mostrar esta ayuda

**Formato CSV:** 1 columna con los IDs que predices como positivos (sin encabezado)"""

    def is_teacher(self, email: str) -> bool:
        """Verifica si un usuario es profesor"""
        return email in self.config["teachers"]

    def handle_message(self, message: dict):
        """Maneja mensajes recibidos"""
        # Solo procesar mensajes privados
        if message["type"] != "private":
            return

        sender_email = message["sender_email"]

        # IMPORTANTE: Ignorar mensajes del propio bot para evitar loops infinitos
        if sender_email == self.config["zulip"]["email"]:
            return

        content = message["content"].strip().lower()
        is_teacher = self.is_teacher(sender_email)

        self.logger.info(
            f"Mensaje recibido de {sender_email}: {content[:50]}{'...' if len(content) > 50 else ''}"
        )

        # Procesar comandos
        try:
            if content.startswith("submit "):
                response = self.process_submit(message, is_teacher)
            elif content == "badges" and not is_teacher:
                self.logger.info(f"Comando badges de {sender_email}")
                response = self.process_badges(message["sender_id"])
            elif content == "list submits" and not is_teacher:
                self.logger.info(f"Comando list submits de {sender_email}")
                response = self.process_list_submits(message["sender_id"])
            elif content.startswith("select ") and not is_teacher:
                self.logger.info(f"Comando select de {sender_email}")
                response = self.process_select(message["sender_id"], message["content"])
            elif content == "duplicates" and is_teacher:
                self.logger.info(f"Comando duplicates de profesor {sender_email}")
                response = self.process_duplicates()
            elif content == "leaderboard full" and is_teacher:
                self.logger.info(f"Comando leaderboard full de profesor {sender_email}")
                response = self.process_leaderboard_full()
            elif content == "leaderboard public" and is_teacher:
                self.logger.info(f"Comando leaderboard public de profesor {sender_email}")
                response = self.process_leaderboard_public()
            elif content.startswith("fake_submit ") and is_teacher:
                self.logger.info(f"Comando fake_submit de profesor {sender_email}")
                response = self.process_fake_submit(message["content"])
            elif content == "help":
                self.logger.info(f"Comando help de {sender_email}")
                response = self.get_help_message(is_teacher)
            else:
                self.logger.info(f"Comando no reconocido de {sender_email}: {content}")
                response = self.get_help_message(is_teacher)

            # Enviar respuesta
            self.client.send_message({"type": "private", "to": sender_email, "content": response})

            self.logger.info(f"Respuesta enviada a {sender_email}")

        except Exception as e:
            self.logger.error(f"Error manejando mensaje de {sender_email}: {e}")
            error_response = "❌ Error interno del bot. El administrador ha sido notificado."
            self.client.send_message(
                {"type": "private", "to": sender_email, "content": error_response}
            )

    def run(self):
        """Ejecuta el bot"""
        self.logger.info(
            f"OraculusBot iniciado para la competencia: {self.config['competition']['name']}"
        )
        self.logger.info(f"Fecha límite: {self.config['competition']['deadline']}")
        self.logger.info(f"Profesores configurados: {len(self.config['teachers'])}")
        self.logger.info("Escuchando mensajes privados...")
        self.logger.info("Logs guardándose en: logs/")

        try:
            self.client.call_on_each_message(self.handle_message)
        except KeyboardInterrupt:
            self.logger.info("Bot detenido por usuario")
        except Exception as e:
            self.logger.error(f"Error fatal en el bot: {e}")
            raise


def create_config_template():
    """Crea un archivo de configuración de ejemplo"""
    config = {
        "zulip": {
            "email": "bot@example.com",
            "api_key": "your-api-key-here",
            "site": "https://your-org.zulipchat.com",
        },
        "database": {"path": "oraculus.db"},
        "teachers": ["teacher1@example.com", "teacher2@example.com"],
        "master_data": {"path": "master_data.csv"},
        "submissions": {"path": "./submissions"},
        "gain_matrix": {"tp": 1.0, "tn": 0.5, "fp": -0.1, "fn": -0.5},
        "gain_thresholds": [
            {
                "min_score": 100,
                "category": "excellent",
                "message": "¡Excelente modelo!",
                "emoji": "🏆",
            },
            {
                "min_score": 50,
                "category": "good",
                "message": "Buen trabajo",
                "emoji": "👍",
            },
            {
                "min_score": 0,
                "category": "basic",
                "message": "Sigue intentando",
                "emoji": "💪",
            },
        ],
        "badges": {
            "first_submission": {"name": "Primer Envío", "emoji": "🎯"},
            "first_model_selection": {"name": "Primera Selección", "emoji": "⭐"},
            "submissions_10": {"name": "10 Envíos", "emoji": "🔟"},
            "submissions_50": {"name": "50 Envíos", "emoji": "🎖️"},
            "submissions_100": {"name": "100 Envíos", "emoji": "💯"},
            "top_5_public": {"name": "Top 5 Público", "emoji": "🥇"},
            "high_threshold_first": {"name": "Primer Umbral Alto", "emoji": "🚀"},
        },
        "competition": {
            "name": "Mi Competencia ML",
            "description": "Competencia de machine learning usando OraculusBot",
            "deadline": "2025-12-31T23:59:59",
        },
    }

    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    # Configurar logging básico para esta función
    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
    logging.info("Archivo config.json creado exitosamente")


def main():
    parser = argparse.ArgumentParser(description="OraculusBot - Bot de Zulip para competencias ML")
    parser.add_argument("--config", "-c", help="Archivo de configuración")
    parser.add_argument(
        "--create-config",
        action="store_true",
        help="Crear archivo de configuración de ejemplo",
    )

    args = parser.parse_args()

    if args.create_config:
        create_config_template()
        return

    if not args.config or not os.path.exists(args.config):
        parser.print_help()
        return

    try:
        # Configurar logging básico para main
        logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
        bot = OraculusBot(args.config)
        bot.run()
    except KeyboardInterrupt:
        logging.info("Bot detenido por usuario")
    except Exception as e:
        logging.error(f"Error fatal: {e}")
        raise


if __name__ == "__main__":
    main()
