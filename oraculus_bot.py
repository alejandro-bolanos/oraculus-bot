#!/usr/bin/env python3
"""
OraculusBot - Bot de Zulip para competencias tipo Kaggle
Ejecutar con: uv run oraculus_bot.py
"""

import os
import json
import sqlite3
import hashlib
import pandas as pd
import numpy as np
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import zulip
import argparse
from sklearn.model_selection import train_test_split
from sklearn.metrics import confusion_matrix


class OraculusBot:
    def __init__(self, config_path: str):
        self.config = self._load_config(config_path)
        
        # Configurar logging
        self._setup_logging()
        
        self.logger.info(f"Iniciando OraculusBot con configuración: {config_path}")
        
        self.client = zulip.Client(
            email=self.config['zulip']['email'],
            api_key=self.config['zulip']['api_key'],
            site=self.config['zulip']['site']
        )
        self.db_path = self.config['database']['path']
        
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
        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        
        # Configurar logger principal
        self.logger = logging.getLogger('OraculusBot')
        self.logger.setLevel(logging.INFO)
        
        # Handler para archivo
        file_handler = logging.FileHandler(
            log_dir / f"oraculus_bot_{datetime.now().strftime('%Y%m%d')}.log",
            encoding='utf-8'
        )
        file_handler.setLevel(logging.INFO)
        file_formatter = logging.Formatter(log_format)
        file_handler.setFormatter(file_formatter)
        
        # Handler para consola
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(console_formatter)
        
        # Agregar handlers
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        
        # Evitar duplicación de logs
        self.logger.propagate = False
        
    def _load_config(self, config_path: str) -> Dict:
        """Carga la configuración desde archivo JSON"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            # Como el logger aún no está configurado, usamos logging básico
            logging.basicConfig(level=logging.ERROR)
            logging.error(f"Error cargando configuración: {e}")
            raise
    
    def init_database(self):
        """Inicializa la base de datos SQLite"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Tabla de envíos
            cursor.execute('''
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
                    estimulos INTEGER,
                    threshold_category TEXT,
                    is_selected BOOLEAN DEFAULT FALSE
                )
            ''')
            
            # Tabla de badges
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_badges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    badge_name TEXT,
                    earned_at DATETIME,
                    UNIQUE(user_id, badge_name)
                )
            ''')
            
            # Tabla de fake submissions
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS fake_submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE,
                    public_score REAL,
                    threshold_category TEXT
                )
            ''')
            
            conn.commit()
            conn.close()
            
            self.logger.info("Base de datos inicializada correctamente")
            
        except Exception as e:
            self.logger.error(f"Error inicializando base de datos: {e}")
            raise
    
    def load_master_data(self):
        """Carga los datos maestros para calcular scores"""
        try:
            master_path = self.config['master_data']['path']
            self.master_df = pd.read_csv(master_path, header=None, names=['id', 'true_label'])
            
            # Split público/privado usando la semilla configurada
            seed = self.config['master_data']['seed']
            self.public_ids, self.private_ids = train_test_split(
                self.master_df['id'].values,
                test_size=0.7,
                random_state=seed
            )
            
            self.public_set = set(self.public_ids)
            self.private_set = set(self.private_ids)
            
            self.logger.info(f"Datos maestros cargados: {len(self.master_df)} registros")
            self.logger.info(f"Split - Público: {len(self.public_set)}, Privado: {len(self.private_set)}")
            
        except Exception as e:
            self.logger.error(f"Error cargando datos maestros: {e}")
            raise
    
    def calculate_scores(self, predictions_df: pd.DataFrame) -> Tuple[Dict, Dict]:
        """Calcula scores público y privado usando matriz de ganancias"""
        master_dict = dict(zip(self.master_df['id'], self.master_df['true_label']))
        pred_dict = dict(zip(predictions_df.iloc[:, 0], predictions_df.iloc[:, 1]))
        
        gain_matrix = self.config['gain_matrix']
        
        def calculate_score_for_set(id_set):
            y_true = [master_dict[id_] for id_ in id_set if id_ in pred_dict]
            y_pred = [pred_dict[id_] for id_ in id_set if id_ in pred_dict]
            
            if not y_true:
                return {'score': 0, 'tp': 0, 'tn': 0, 'fp': 0, 'fn': 0}
            
            cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
            tn, fp, fn, tp = cm.ravel()
            
            score = (tp * gain_matrix['tp'] + 
                    tn * gain_matrix['tn'] + 
                    fp * gain_matrix['fp'] + 
                    fn * gain_matrix['fn'])
            
            return {'score': score, 'tp': int(tp), 'tn': int(tn), 'fp': int(fp), 'fn': int(fn)}
        
        public_results = calculate_score_for_set(self.public_set)
        private_results = calculate_score_for_set(self.private_set)
        
        return public_results, private_results
    
    def get_threshold_category(self, score: float) -> str:
        """Determina la categoría basada en umbrales de ganancia"""
        thresholds = self.config['gain_thresholds']
        for threshold in sorted(thresholds, key=lambda x: x['min_score'], reverse=True):
            if score >= threshold['min_score']:
                return threshold['category']
        return thresholds[-1]['category']  # Categoría más baja por defecto
    
    def save_submission(self, user_info: Dict, submission_name: str, file_path: str, 
                       checksum: str, public_results: Dict, private_results: Dict, 
                       estimulos: int, threshold_category: str):
        """Guarda un envío en la base de datos"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO submissions (
                user_id, user_email, user_full_name, submission_name,
                timestamp, file_checksum, file_path, public_score, private_score,
                tp, tn, fp, fn, estimulos, threshold_category
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_info['user_id'], user_info['email'], user_info['full_name'],
            submission_name, datetime.now(), checksum, file_path,
            public_results['score'], private_results['score'],
            private_results['tp'], private_results['tn'], 
            private_results['fp'], private_results['fn'],
            estimulos, threshold_category
        ))
        
        submission_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return submission_id
    
    def check_and_award_badges(self, user_id: int, submission_count: int, 
                              public_score: float, is_first_selection: bool = False):
        """Verifica y otorga badges basado en logros"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        badges_to_award = []
        
        # Badge primer envío
        if submission_count == 1:
            badges_to_award.append('first_submission')
        
        # Badge primera selección de modelo
        if is_first_selection:
            badges_to_award.append('first_model_selection')
        
        # Badges por cantidad de envíos
        badge_thresholds = [(10, 'submissions_10'), (50, 'submissions_50'), (100, 'submissions_100')]
        for threshold, badge_name in badge_thresholds:
            if submission_count == threshold:
                badges_to_award.append(badge_name)
        
        # Badge top 5 público
        cursor.execute('''
            SELECT COUNT(*) FROM submissions 
            WHERE public_score > ? AND is_selected = TRUE
        ''', (public_score,))
        rank = cursor.fetchone()[0] + 1
        
        if rank <= 5:
            badges_to_award.append('top_5_public')
        
        # Badge primer umbral alto
        thresholds = sorted(self.config['gain_thresholds'], key=lambda x: x['min_score'], reverse=True)
        if len(thresholds) > 1 and public_score >= thresholds[1]['min_score']:
            cursor.execute('SELECT COUNT(*) FROM submissions WHERE user_id = ? AND public_score >= ?',
                          (user_id, thresholds[1]['min_score']))
            if cursor.fetchone()[0] == 1:  # Primera vez alcanzando este umbral
                badges_to_award.append('high_threshold_first')
        
        # Insertar badges nuevos
        new_badges = []
        for badge_name in badges_to_award:
            try:
                cursor.execute('''
                    INSERT INTO user_badges (user_id, badge_name, earned_at)
                    VALUES (?, ?, ?)
                ''', (user_id, badge_name, datetime.now()))
                new_badges.append(badge_name)
            except sqlite3.IntegrityError:
                pass  # Badge ya existe
        
        conn.commit()
        conn.close()
        
        return new_badges
    
    def process_submit(self, message: Dict, is_teacher: bool = False) -> str:
        """Procesa comando submit"""
        user_email = message['sender_email']
        submission_name = ""
        
        try:
            self.logger.info(f"Procesando submit de {user_email} (profesor: {is_teacher})")
            
            # Extraer nombre del envío
            parts = message['content'].strip().split(' ', 1)
            if len(parts) < 2:
                return "❌ Formato incorrecto. Uso: `submit <nombre_envio>`"
            
            submission_name = parts[1].strip()
            self.logger.info(f"Nombre del envío: {submission_name}")
            
            # Verificar archivo adjunto
            if not message.get('attachments'):
                self.logger.warning(f"No hay archivo adjunto en envío de {user_email}")
                return "❌ Debes adjuntar un archivo CSV"
            
            attachment = message['attachments'][0]
            if not attachment['name'].endswith('.csv'):
                self.logger.warning(f"Archivo no CSV enviado por {user_email}: {attachment['name']}")
                return "❌ El archivo debe ser un CSV"
            
            # Verificar fecha límite (solo para estudiantes)
            if not is_teacher:
                deadline = datetime.fromisoformat(self.config['competition']['deadline'])
                if datetime.now() > deadline:
                    self.logger.warning(f"Envío fuera de fecha límite de {user_email}")
                    return "❌ La fecha límite para envíos ha expirado"
            
            # Descargar y validar archivo
            self.logger.info(f"Descargando archivo: {attachment['name']}")
            file_content = self.client.get_file_content(attachment['url'])
            file_path = self._save_submission_file(message['sender_id'], submission_name, 
                                                 attachment['name'], file_content, is_teacher)
            
            # Calcular checksum
            checksum = hashlib.sha256(file_content).hexdigest()
            self.logger.info(f"Archivo guardado: {file_path}, checksum: {checksum[:16]}...")
            
            # Leer y validar CSV
            df = pd.read_csv(file_path, header=None)
            if df.shape[1] != 2:
                self.logger.warning(f"CSV con formato incorrecto de {user_email}: {df.shape[1]} columnas")
                return "❌ El CSV debe tener exactamente 2 columnas (id, predicción)"
            
            # Validar IDs
            submitted_ids = set(df.iloc[:, 0])
            expected_ids = set(self.master_df['id'])
            
            if submitted_ids != expected_ids:
                missing = expected_ids - submitted_ids
                extra = submitted_ids - expected_ids
                self.logger.warning(f"IDs incorrectos en envío de {user_email}: faltan {len(missing)}, sobran {len(extra)}")
                msg = "❌ IDs incorrectos en el archivo:\n"
                if missing:
                    msg += f"Faltan: {len(missing)} IDs\n"
                if extra:
                    msg += f"Sobran: {len(extra)} IDs\n"
                return msg
            
            # Validar valores binarios
            predictions = df.iloc[:, 1]
            if not all(pred in [0, 1] for pred in predictions):
                self.logger.warning(f"Predicciones no binarias en envío de {user_email}")
                return "❌ Las predicciones deben ser valores binarios (0 o 1)"
            
            # Calcular scores
            self.logger.info(f"Calculando scores para {submission_name}")
            public_results, private_results = self.calculate_scores(df)
            threshold_category = self.get_threshold_category(public_results['score'])
            estimulos = int(predictions.sum())
            
            self.logger.info(f"Scores calculados - Público: {public_results['score']:.4f}, Privado: {private_results['score']:.4f}")
            
            user_info = {
                'user_id': message['sender_id'],
                'email': message['sender_email'],
                'full_name': message['sender_full_name']
            }
            
            if is_teacher:
                # Para profesores: solo mostrar resultados
                self.logger.info(f"Envío de profesor completado: {submission_name}")
                response = f"📊 **Resultados para {submission_name}**\n\n"
                response += f"🔓 **Público:** {public_results['score']:.4f}\n"
                response += f"🔒 **Privado:** {private_results['score']:.4f}\n"
                response += f"🎯 **Categoría:** {threshold_category}\n"
                response += f"📈 **Estímulos:** {estimulos}\n"
                return response
            else:
                # Para estudiantes: guardar y otorgar badges
                submission_id = self.save_submission(
                    user_info, submission_name, file_path, checksum,
                    public_results, private_results, estimulos, threshold_category
                )
                
                self.logger.info(f"Envío guardado con ID: {submission_id}")
                
                # Contar envíos del usuario
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) FROM submissions WHERE user_id = ?', (message['sender_id'],))
                submission_count = cursor.fetchone()[0]
                conn.close()
                
                # Verificar badges
                new_badges = self.check_and_award_badges(
                    message['sender_id'], submission_count, public_results['score']
                )
                
                if new_badges:
                    self.logger.info(f"Nuevos badges otorgados a {user_email}: {new_badges}")
                
                # Obtener configuración de respuesta por umbral
                threshold_config = next(
                    t for t in self.config['gain_thresholds'] 
                    if t['category'] == threshold_category
                )
                
                response = f"🎯 **{threshold_config['message']}** {threshold_config.get('emoji', '')}\n\n"
                response += f"📊 **Score Público:** {public_results['score']:.4f}\n"
                response += f"🆔 **ID Envío:** {submission_id}\n"
                response += f"📈 **Estímulos:** {estimulos}\n"
                
                if new_badges:
                    badge_configs = self.config.get('badges', {})
                    response += f"\n🏆 **Nuevos Badges:**\n"
                    for badge in new_badges:
                        badge_info = badge_configs.get(badge, {'name': badge, 'emoji': '🏅'})
                        response += f"{badge_info['emoji']} {badge_info['name']}\n"
                
                return response
                
        except Exception as e:
            self.logger.error(f"Error procesando envío '{submission_name}' de {user_email}: {e}")
            return f"❌ Error procesando envío: {str(e)}"
    
    def _save_submission_file(self, user_id: int, submission_name: str, 
                             filename: str, content: bytes, is_teacher: bool = False) -> str:
        """Guarda el archivo de envío en el sistema de archivos"""
        base_path = Path(self.config['submissions']['path'])
        
        if is_teacher:
            user_dir = base_path / "teachers" / str(user_id)
        else:
            user_dir = base_path / "students" / str(user_id)
        
        user_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c for c in submission_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
        file_path = user_dir / f"{timestamp}_{safe_name}_{filename}"
        
        with open(file_path, 'wb') as f:
            f.write(content)
        
        return str(file_path)
    
    def process_badges(self, user_id: int) -> str:
        """Lista badges del usuario"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT badge_name, earned_at FROM user_badges 
            WHERE user_id = ? ORDER BY earned_at DESC
        ''', (user_id,))
        
        badges = cursor.fetchall()
        conn.close()
        
        if not badges:
            return "🏆 No tienes badges aún. ¡Sigue enviando modelos para ganarlos!"
        
        response = "🏆 **Tus Badges:**\n\n"
        badge_configs = self.config.get('badges', {})
        
        for badge_name, earned_at in badges:
            badge_info = badge_configs.get(badge_name, {'name': badge_name, 'emoji': '🏅'})
            date_str = datetime.fromisoformat(earned_at).strftime("%d/%m/%Y")
            response += f"{badge_info['emoji']} **{badge_info['name']}** - {date_str}\n"
        
        return response
    
    def process_list_submits(self, user_id: int) -> str:
        """Lista envíos del usuario"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, submission_name, timestamp, public_score, 
                   threshold_category, is_selected FROM submissions 
            WHERE user_id = ? ORDER BY timestamp DESC
        ''', (user_id,))
        
        submissions = cursor.fetchall()
        conn.close()
        
        if not submissions:
            return "📋 No tienes envíos registrados"
        
        response = "📋 **Tus Envíos:**\n\n"
        for sub in submissions:
            selected_mark = "⭐" if sub[5] else ""
            response += f"`{sub[0]}` - **{sub[1]}** {selected_mark}\n"
            response += f"   📅 {sub[2][:19]} | 📊 {sub[3]:.4f} | 🎯 {sub[4]}\n\n"
        
        return response
    
    def process_select(self, user_id: int, message_content: str) -> str:
        """Selecciona un modelo para el leaderboard"""
        try:
            parts = message_content.strip().split(' ', 1)
            if len(parts) < 2:
                return "❌ Formato incorrecto. Uso: `select <id_submit>`"
            
            submission_id = int(parts[1])
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Verificar que el envío existe y pertenece al usuario
            cursor.execute('''
                SELECT id FROM submissions 
                WHERE id = ? AND user_id = ?
            ''', (submission_id, user_id))
            
            if not cursor.fetchone():
                conn.close()
                return "❌ Envío no encontrado o no te pertenece"
            
            # Desmarcar selección anterior
            cursor.execute('''
                UPDATE submissions SET is_selected = FALSE 
                WHERE user_id = ?
            ''', (user_id,))
            
            # Marcar nueva selección
            cursor.execute('''
                UPDATE submissions SET is_selected = TRUE 
                WHERE id = ? AND user_id = ?
            ''', (submission_id, user_id))
            
            # Verificar si es la primera selección para badge
            cursor.execute('''
                SELECT COUNT(*) FROM user_badges 
                WHERE user_id = ? AND badge_name = 'first_model_selection'
            ''', (user_id,))
            
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
            return f"❌ Error: {str(e)}"
    
    def process_duplicates(self) -> str:
        """Lista envíos duplicados (solo profesores)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT file_checksum, COUNT(*), 
                   GROUP_CONCAT(DISTINCT user_email) as users,
                   GROUP_CONCAT(submission_name) as names
            FROM submissions 
            GROUP BY file_checksum 
            HAVING COUNT(DISTINCT user_id) > 1
        ''')
        
        duplicates = cursor.fetchall()
        conn.close()
        
        if not duplicates:
            return "✅ No se encontraron envíos duplicados"
        
        response = "🔍 **Envíos Duplicados:**\n\n"
        for checksum, count, users, names in duplicates:
            response += f"**Checksum:** `{checksum[:16]}...`\n"
            response += f"**Usuarios:** {users}\n"
            response += f"**Envíos:** {names}\n\n"
        
        return response
    
    def process_leaderboard_full(self) -> str:
        """Leaderboard completo (solo profesores)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Obtener mejor score para cada usuario
        cursor.execute('''
            WITH user_best AS (
                SELECT 
                    user_id,
                    user_full_name,
                    user_email,
                    COUNT(*) as total_submissions,
                    CASE 
                        WHEN MAX(CASE WHEN is_selected = 1 THEN private_score END) IS NOT NULL 
                        THEN MAX(CASE WHEN is_selected = 1 THEN private_score END)
                        ELSE MAX(private_score)
                    END as final_score,
                    MAX(private_score) as best_private,
                    MAX(public_score) as best_public,
                    (SELECT id FROM submissions s2 WHERE s2.user_id = s1.user_id AND s2.private_score = MAX(s1.private_score) LIMIT 1) as best_submission_id
                FROM submissions s1
                GROUP BY user_id
            )
            SELECT * FROM user_best ORDER BY final_score DESC
        ''')
        
        results = cursor.fetchall()
        conn.close()
        
        if not results:
            return "📊 No hay envíos en el leaderboard"
        
        response = f"🏆 **Leaderboard Completo - {self.config['competition']['name']}**\n\n"
        
        for i, (user_id, name, email, submissions, final_score, best_private, best_public, best_id) in enumerate(results, 1):
            response += f"**{i}.** {name}\n"
            response += f"   📧 {email}\n"
            response += f"   🎯 Score Final: {final_score:.4f}\n"
            response += f"   📊 Mejor Envío: #{best_id} (Pub: {best_public:.4f}, Priv: {best_private:.4f})\n"
            response += f"   📈 Total Envíos: {submissions}\n\n"
        
        return response
    
    def process_leaderboard_public(self) -> str:
        """Leaderboard público (solo profesores)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Incluir fake submissions
        cursor.execute('''
            WITH real_submissions AS (
                SELECT 
                    user_full_name as name,
                    MAX(public_score) as best_public,
                    (SELECT threshold_category FROM submissions s2 
                     WHERE s2.user_id = s1.user_id AND s2.public_score = MAX(s1.public_score) LIMIT 1) as category
                FROM submissions s1
                GROUP BY user_id
            ),
            fake_submissions AS (
                SELECT name, public_score as best_public, threshold_category as category
                FROM fake_submissions
            ),
            combined AS (
                SELECT name, best_public, category FROM real_submissions
                UNION ALL
                SELECT name, best_public, category FROM fake_submissions
            )
            SELECT * FROM combined ORDER BY best_public DESC
        ''')
        
        results = cursor.fetchall()
        conn.close()
        
        if not results:
            return "📊 No hay datos para el leaderboard público"
        
        response = f"🌟 **Leaderboard Público - {self.config['competition']['name']}**\n\n"
        
        # Obtener mensajes de umbral
        threshold_messages = {t['category']: t['message'] for t in self.config['gain_thresholds']}
        
        for i, (name, score, category) in enumerate(results, 1):
            message = threshold_messages.get(category, category)
            response += f"**{i}.** {name} - {message}\n"
        
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
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            try:
                cursor.execute('''
                    INSERT INTO fake_submissions (name, public_score, threshold_category)
                    VALUES (?, ?, ?)
                ''', (name, public_score, category))
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
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('DELETE FROM fake_submissions WHERE name = ?', (name,))
            
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
        competition = self.config['competition']
        
        if is_teacher:
            return f"""🤖 **OraculusBot - Ayuda para Profesores**

**Competencia:** {competition['name']}
**Descripción:** {competition['description']}
**Fecha límite:** {competition['deadline']}

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

**Competencia:** {competition['name']}
**Descripción:** {competition['description']}
**Fecha límite:** {competition['deadline']}

**Comandos disponibles:**
• `submit <nombre>` - Enviar modelo (adjuntar CSV)
• `badges` - Ver tus badges ganados
• `list submits` - Listar tus envíos
• `select <id>` - Seleccionar modelo para leaderboard
• `help` - Mostrar esta ayuda

**Formato CSV:** 2 columnas sin encabezado (id, predicción_binaria)"""
    
    def is_teacher(self, email: str) -> bool:
        """Verifica si un usuario es profesor"""
        return email in self.config['teachers']
    
    def handle_message(self, message: Dict):
        """Maneja mensajes recibidos"""
        # Solo procesar mensajes privados
        if message['type'] != 'private':
            return
        
        sender_email = message['sender_email']
        
        # IMPORTANTE: Ignorar mensajes del propio bot para evitar loops infinitos
        if sender_email == self.config['zulip']['email']:
            return
            
        content = message['content'].strip().lower()
        is_teacher = self.is_teacher(sender_email)
        
        self.logger.info(f"Mensaje recibido de {sender_email}: {content[:50]}{'...' if len(content) > 50 else ''}")
        
        # Procesar comandos
        try:
            if content.startswith('submit '):
                response = self.process_submit(message, is_teacher)
            elif content == 'badges' and not is_teacher:
                self.logger.info(f"Comando badges de {sender_email}")
                response = self.process_badges(message['sender_id'])
            elif content == 'list submits' and not is_teacher:
                self.logger.info(f"Comando list submits de {sender_email}")
                response = self.process_list_submits(message['sender_id'])
            elif content.startswith('select ') and not is_teacher:
                self.logger.info(f"Comando select de {sender_email}")
                response = self.process_select(message['sender_id'], message['content'])
            elif content == 'duplicates' and is_teacher:
                self.logger.info(f"Comando duplicates de profesor {sender_email}")
                response = self.process_duplicates()
            elif content == 'leaderboard full' and is_teacher:
                self.logger.info(f"Comando leaderboard full de profesor {sender_email}")
                response = self.process_leaderboard_full()
            elif content == 'leaderboard public' and is_teacher:
                self.logger.info(f"Comando leaderboard public de profesor {sender_email}")
                response = self.process_leaderboard_public()
            elif content.startswith('fake_submit ') and is_teacher:
                self.logger.info(f"Comando fake_submit de profesor {sender_email}")
                response = self.process_fake_submit(message['content'])
            elif content == 'help':
                self.logger.info(f"Comando help de {sender_email}")
                response = self.get_help_message(is_teacher)
            else:
                self.logger.info(f"Comando no reconocido de {sender_email}: {content}")
                response = self.get_help_message(is_teacher)
            
            # Enviar respuesta
            self.client.send_message({
                'type': 'private',
                'to': sender_email,
                'content': response
            })
            
            self.logger.info(f"Respuesta enviada a {sender_email}")
            
        except Exception as e:
            self.logger.error(f"Error manejando mensaje de {sender_email}: {e}")
            error_response = "❌ Error interno del bot. El administrador ha sido notificado."
            self.client.send_message({
                'type': 'private',
                'to': sender_email,
                'content': error_response
            })
    
    def run(self):
        """Ejecuta el bot"""
        self.logger.info(f"OraculusBot iniciado para la competencia: {self.config['competition']['name']}")
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
            "site": "https://your-org.zulipchat.com"
        },
        "database": {
            "path": "oraculus.db"
        },
        "teachers": [
            "teacher1@example.com",
            "teacher2@example.com"
        ],
        "master_data": {
            "path": "master_data.csv",
            "seed": 42
        },
        "submissions": {
            "path": "./submissions"
        },
        "gain_matrix": {
            "tp": 1.0,
            "tn": 0.5,
            "fp": -0.1,
            "fn": -0.5
        },
        "gain_thresholds": [
            {
                "min_score": 100,
                "category": "excellent",
                "message": "¡Excelente modelo!",
                "emoji": "🏆"
            },
            {
                "min_score": 50,
                "category": "good",
                "message": "Buen trabajo",
                "emoji": "👍"
            },
            {
                "min_score": 0,
                "category": "basic",
                "message": "Sigue intentando",
                "emoji": "💪"
            }
        ],
        "badges": {
            "first_submission": {
                "name": "Primer Envío",
                "emoji": "🎯"
            },
            "first_model_selection": {
                "name": "Primera Selección",
                "emoji": "⭐"
            },
            "submissions_10": {
                "name": "10 Envíos",
                "emoji": "🔟"
            },
            "submissions_50": {
                "name": "50 Envíos",
                "emoji": "🎖️"
            },
            "submissions_100": {
                "name": "100 Envíos",
                "emoji": "💯"
            },
            "top_5_public": {
                "name": "Top 5 Público",
                "emoji": "🥇"
            },
            "high_threshold_first": {
                "name": "Primer Umbral Alto",
                "emoji": "🚀"
            }
        },
        "competition": {
            "name": "Mi Competencia ML",
            "description": "Competencia de machine learning usando OraculusBot",
            "deadline": "2025-12-31T23:59:59"
        }
    }
    
    with open('config.json', 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    
    # Configurar logging básico para esta función
    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
    logging.info("Archivo config.json creado exitosamente")


def main():
    parser = argparse.ArgumentParser(description='OraculusBot - Bot de Zulip para competencias ML')
    parser.add_argument('--config', '-c', default='config.json', help='Archivo de configuración')
    parser.add_argument('--create-config', action='store_true', help='Crear archivo de configuración de ejemplo')
    
    args = parser.parse_args()
    
    # Configurar logging básico para main
    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
    
    if args.create_config:
        create_config_template()
        return
    
    if not os.path.exists(args.config):
        logging.error(f"Archivo de configuración no encontrado: {args.config}")
        logging.info("Usa --create-config para generar un ejemplo")
        return
    
    try:
        bot = OraculusBot(args.config)
        bot.run()
    except KeyboardInterrupt:
        logging.info("Bot detenido por usuario")
    except Exception as e:
        logging.error(f"Error fatal: {e}")
        raise


if __name__ == "__main__":
    main()