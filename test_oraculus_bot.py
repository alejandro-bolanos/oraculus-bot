import pytest
import pandas as pd
import sqlite3
import tempfile
import json
import os
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
from oraculus_bot import OraculusBot, create_config_template


@pytest.fixture
def temp_dir():
    """Directorio temporal para tests"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_master_data(temp_dir):
    """Datos maestros de ejemplo con nuevo formato"""
    master_data = pd.DataFrame({
        "id": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        "clase_binaria": [1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
        "dataset": ["public", "public", "public", "public", "private", 
                   "private", "private", "private", "private", "private"]
    })
    
    master_path = temp_dir / "master_data.csv"
    master_data.to_csv(master_path, index=False)
    return master_path


@pytest.fixture
def sample_config(temp_dir, sample_master_data):
    """Configuración de ejemplo para tests"""
    config = {
        "zulip": {
            "email": "bot@test.com",
            "api_key": "test-key",
            "site": "https://test.zulipchat.com",
        },
        "database": {"path": str(temp_dir / "test.db")},
        "teachers": ["teacher@test.com"],
        "master_data": {"path": str(sample_master_data)},
        "submissions": {"path": str(temp_dir / "submissions")},
        "gain_matrix": {"tp": 10, "tn": 1, "fp": -5, "fn": -10},
        "gain_thresholds": [
            {"min_score": 20, "category": "excellent", "message": "¡Excelente!", "emoji": "🏆"},
            {"min_score": 10, "category": "good", "message": "Bien", "emoji": "👍"},
            {"min_score": -100, "category": "basic", "message": "Sigue intentando", "emoji": "💪"},
        ],
        "badges": {
            "first_submission": {"name": "Primer Envío", "emoji": "🎯"},
            "first_model_selection": {"name": "Primera Selección", "emoji": "⭐"},
        },
        "competition": {
            "name": "Test Competition",
            "description": "Test",
            "deadline": "2030-12-31T23:59:59",
        },
    }
    
    config_path = temp_dir / "config.json"
    with open(config_path, "w") as f:
        json.dump(config, f)
    
    return config_path


@pytest.fixture
def bot(sample_config):
    """Bot de prueba"""
    with patch("oraculus_bot.zulip.Client") as mock_client:
        mock_client.return_value = Mock()
        bot = OraculusBot(str(sample_config))
        return bot


class TestOraculusBot:
    """Tests para la clase OraculusBot"""

    def test_init(self, bot):
        """Test inicialización del bot"""
        assert bot is not None
        assert bot.config is not None
        assert bot.logger is not None
        assert len(bot.master_df) == 10
        assert len(bot.public_df) == 4
        assert len(bot.private_df) == 6
        assert len(bot.positive_ids) == 5

    def test_load_master_data(self, bot):
        """Test carga de datos maestros"""
        # Verificar estructura de datos
        assert "id" in bot.master_df.columns
        assert "clase_binaria" in bot.master_df.columns
        assert "dataset" in bot.master_df.columns
        
        # Verificar conjuntos
        assert bot.public_ids == {1, 2, 3, 4}
        assert bot.private_ids == {5, 6, 7, 8, 9, 10}
        assert bot.all_ids == {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}
        assert bot.positive_ids == {1, 3, 5, 7, 9}

    def test_calculate_scores(self, bot):
        """Test cálculo de scores"""
        # Predicciones perfectas
        perfect_predictions = {1, 3, 5, 7, 9}  # Todos los positivos
        public_results, private_results = bot.calculate_scores(perfect_predictions)
        
        # Verificar scores público (IDs 1,2,3,4 -> verdaderos: 1,3 positivos)
        # TP=2, TN=2, FP=0, FN=0 -> Score = 2*10 + 2*1 + 0*(-5) + 0*(-10) = 22
        assert public_results["tp"] == 2
        assert public_results["tn"] == 2
        assert public_results["fp"] == 0
        assert public_results["fn"] == 0
        assert public_results["score"] == 22
        
        # Predicciones vacías
        empty_predictions = set()
        public_results, private_results = bot.calculate_scores(empty_predictions)
        
        # Todos negativos: TP=0, TN=2, FP=0, FN=2 -> Score = 0*10 + 2*1 + 0*(-5) + 2*(-10) = -18
        assert public_results["tp"] == 0
        assert public_results["tn"] == 2
        assert public_results["fp"] == 0
        assert public_results["fn"] == 2
        assert public_results["score"] == -18

    def test_threshold_category(self, bot):
        """Test categorización por umbral"""
        assert bot.get_threshold_category(25) == "excellent"
        assert bot.get_threshold_category(15) == "good"
        assert bot.get_threshold_category(5) == "basic"
        assert bot.get_threshold_category(-50) == "basic"

    def test_save_submission(self, bot):
        """Test guardar envío"""
        user_info = {
            "user_id": 123,
            "email": "user@test.com",
            "full_name": "Test User"
        }
        
        public_results = {"score": 15, "tp": 2, "tn": 1, "fp": 0, "fn": 1}
        private_results = {"score": 20, "tp": 3, "tn": 2, "fp": 1, "fn": 0}
        
        submission_id = bot.save_submission(
            user_info, "test_model", "/path/to/file", "checksum123",
            public_results, private_results, 5, "good"
        )
        
        assert submission_id is not None
        assert submission_id > 0
        
        # Verificar en BD
        conn = bot._get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM submissions WHERE id = ?", (submission_id,))
        result = cursor.fetchone()
        conn.close()
        
        assert result is not None
        assert result[1] == 123  # user_id
        assert result[4] == "test_model"  # submission_name

    def test_check_and_award_badges(self, bot):
        """Test sistema de badges"""
        user_id = 123
        
        # Primer envío
        new_badges = bot.check_and_award_badges(user_id, 1, 15.0)
        assert "first_submission" in new_badges
        
        # 10 envíos
        new_badges = bot.check_and_award_badges(user_id, 10, 15.0)
        assert "submissions_10" in new_badges
        
        # Primera selección
        new_badges = bot.check_and_award_badges(user_id, 5, 15.0, is_first_selection=True)
        assert "first_model_selection" in new_badges

    def test_process_badges(self, bot):
        """Test comando badges"""
        user_id = 123
        
        # Sin badges
        response = bot.process_badges(user_id)
        assert "No tienes badges" in response
        
        # Con badges
        bot.check_and_award_badges(user_id, 1, 15.0)
        response = bot.process_badges(user_id)
        assert "Primer Envío" in response

    def test_process_select(self, bot):
        """Test comando select"""
        user_id = 123
        
        # Crear envío primero
        user_info = {"user_id": user_id, "email": "user@test.com", "full_name": "Test User"}
        public_results = {"score": 15, "tp": 2, "tn": 1, "fp": 0, "fn": 1}
        private_results = {"score": 20, "tp": 3, "tn": 2, "fp": 1, "fn": 0}
        
        submission_id = bot.save_submission(
            user_info, "test_model", "/path/to/file", "checksum123",
            public_results, private_results, 5, "good"
        )
        
        # Seleccionar modelo
        response = bot.process_select(user_id, f"select {submission_id}")
        assert "seleccionado" in response.lower()
        
        # Envío inexistente
        response = bot.process_select(user_id, "select 9999")
        assert "no encontrado" in response.lower()
        
        # Formato incorrecto
        response = bot.process_select(user_id, "select")
        assert "Formato incorrecto" in response

    def test_process_list_submits(self, bot):
        """Test comando list submits"""
        user_id = 123
        
        # Sin envíos
        response = bot.process_list_submits(user_id)
        assert "No tienes envíos" in response
        
        # Con envíos
        user_info = {"user_id": user_id, "email": "user@test.com", "full_name": "Test User"}
        public_results = {"score": 15, "tp": 2, "tn": 1, "fp": 0, "fn": 1}
        private_results = {"score": 20, "tp": 3, "tn": 2, "fp": 1, "fn": 0}
        
        bot.save_submission(
            user_info, "test_model", "/path/to/file", "checksum123",
            public_results, private_results, 5, "good"
        )
        
        response = bot.process_list_submits(user_id)
        assert "test_model" in response
        assert "15.0000" in response

    def test_process_fake_submit(self, bot):
        """Test comando fake_submit"""
        # Agregar
        response = bot.process_fake_submit("fake_submit add TestUser 25.5")
        assert "agregado" in response.lower()
        
        # Eliminar
        response = bot.process_fake_submit("fake_submit remove TestUser")
        assert "eliminado" in response.lower()
        
        # Formato incorrecto
        response = bot.process_fake_submit("fake_submit")
        assert "Formato incorrecto" in response

    def test_process_leaderboard_public(self, bot):
        """Test leaderboard público"""
        # Sin envíos
        response = bot.process_leaderboard_public()
        assert "No hay submissions" in response
        
        # Con envíos
        user_info = {"user_id": 123, "email": "user@test.com", "full_name": "Test User"}
        public_results = {"score": 15, "tp": 2, "tn": 1, "fp": 0, "fn": 1}
        private_results = {"score": 20, "tp": 3, "tn": 2, "fp": 1, "fn": 0}
        
        bot.save_submission(
            user_info, "test_model", "/path/to/file", "checksum123",
            public_results, private_results, 5, "good"
        )
        
        response = bot.process_leaderboard_public()
        assert "Test User" in response
        assert "15.0000" in response

    def test_is_teacher(self, bot):
        """Test verificación de profesores"""
        assert bot.is_teacher("teacher@test.com") is True
        assert bot.is_teacher("student@test.com") is False

    def test_get_help_message(self, bot):
        """Test mensajes de ayuda"""
        # Ayuda para estudiantes
        help_msg = bot.get_help_message(False)
        assert "submit" in help_msg
        assert "badges" in help_msg
        assert "1 columna" in help_msg
        
        # Ayuda para profesores
        help_msg = bot.get_help_message(True)
        assert "duplicates" in help_msg
        assert "fake_submit" in help_msg

    @patch("oraculus_bot.requests.get")
    def test_extract_file_from_message(self, mock_get, bot):
        """Test extracción de archivos de mensajes"""
        # Mock response
        mock_response = Mock()
        mock_response.content = b"1,2,3"
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        message = {
            "content": "submit test_model\n[predictions.csv](https://test.zulipchat.com/file123)"
        }
        
        filename, content = bot._extract_file_from_message(message)
        assert filename == "predictions.csv"
        assert content == b"1,2,3"
        
        # Sin archivo
        message = {"content": "submit test_model"}
        filename, content = bot._extract_file_from_message(message)
        assert filename is None
        assert content is None

    @patch("oraculus_bot.requests.get")
    def test_process_submit_success(self, mock_get, bot, temp_dir):
        """Test proceso de submit exitoso"""
        # Mock de descarga de archivo
        mock_response = Mock()
        mock_response.content = b"1\n3\n5"  # IDs positivos predichos
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        message = {
            "sender_id": 123,
            "sender_email": "student@test.com",
            "sender_full_name": "Test Student",
            "content": "submit test_model\n[predictions.csv](https://test.zulipchat.com/file123)"
        }
        
        response = bot.process_submit(message)
        assert "ID Envío:" in response

    def test_process_duplicates(self, bot):
        """Test detección de duplicados"""
        # Crear dos envíos con mismo checksum
        user_info1 = {"user_id": 123, "email": "user1@test.com", "full_name": "User 1"}
        user_info2 = {"user_id": 124, "email": "user2@test.com", "full_name": "User 2"}
        
        public_results = {"score": 15, "tp": 2, "tn": 1, "fp": 0, "fn": 1}
        private_results = {"score": 20, "tp": 3, "tn": 2, "fp": 1, "fn": 0}
        
        # Mismo checksum para ambos
        bot.save_submission(user_info1, "model1", "/path1", "same_checksum", 
                           public_results, private_results, 5, "good")
        bot.save_submission(user_info2, "model2", "/path2", "same_checksum", 
                           public_results, private_results, 5, "good")
        
        response = bot.process_duplicates()
        assert "Duplicados" in response
        assert "same_checksum" in response

    def test_database_initialization(self, bot):
        """Test inicialización de base de datos"""

        conn = sqlite3.connect(bot.config["database"]["path"]) 
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        
        assert "submissions" in tables
        assert "user_badges" in tables
        assert "fake_submissions" in tables
        
        conn.close()


class TestConfigCreation:
    """Tests para creación de configuración"""

    def test_create_config_template(self, temp_dir):
        """Test creación de template de configuración"""
        os.chdir(temp_dir)
        create_config_template()
        
        assert (temp_dir / "config.json").exists()
        
        with open(temp_dir / "config.json") as f:
            config = json.load(f)
        
        assert "zulip" in config
        assert "database" in config
        assert "master_data" in config
        assert "gain_matrix" in config


class TestEdgeCases:
    """Tests para casos límite"""

    def test_empty_predictions(self, bot):
        """Test con predicciones vacías"""
        empty_predictions = set()
        public_results, private_results = bot.calculate_scores(empty_predictions)
        
        # Todos son negativos predichos
        assert public_results["tp"] == 0
        assert public_results["fp"] == 0
        assert public_results["fn"] == 2  # Hay 2 positivos reales en público
        assert public_results["tn"] == 2  # Hay 2 negativos reales en público

    def test_all_predictions_positive(self, bot):
        """Test prediciendo todos como positivos"""
        all_predictions = bot.all_ids
        public_results, private_results = bot.calculate_scores(all_predictions)
        
        # En público: IDs 1,2,3,4 - reales positivos: 1,3
        assert public_results["tp"] == 2  # Predijimos correctamente 1,3
        assert public_results["fp"] == 2  # Predijimos incorrectamente 2,4
        assert public_results["fn"] == 0  # No perdimos ningún positivo
        assert public_results["tn"] == 0  # No acertamos ningún negativo

    def test_invalid_master_data_format(self, temp_dir):
        """Test con formato inválido de datos maestros"""
        # Crear archivo con columnas incorrectas
        bad_data = pd.DataFrame({
            "wrong_id": [1, 2, 3],
            "wrong_label": [0, 1, 0]
        })
        
        bad_path = temp_dir / "bad_master.csv"
        bad_data.to_csv(bad_path, index=False)
        
        config = {
            "zulip": {"email": "test", "api_key": "test", "site": "test"},
            "database": {"path": str(temp_dir / "test.db")},
            "master_data": {"path": str(bad_path)},
            "teachers": [],
            "submissions": {"path": str(temp_dir)},
            "gain_matrix": {"tp": 1, "tn": 1, "fp": -1, "fn": -1},
            "gain_thresholds": [{"min_score": 0, "category": "basic", "message": "OK", "emoji": "👍"}],
            "badges": {},
            "competition": {"name": "Test", "description": "Test", "deadline": "2030-01-01T00:00:00"}
        }
        
        config_path = temp_dir / "bad_config.json"
        with open(config_path, "w") as f:
            json.dump(config, f)
        
        with patch("oraculus_bot.zulip.Client"):
            with pytest.raises(ValueError, match="debe tener columnas"):
                OraculusBot(str(config_path))


class TestMessageHandling:
    """Tests para manejo de mensajes"""

    def test_handle_message_ignore_bot_messages(self, bot):
        """Test ignorar mensajes del propio bot"""
        message = {
            "type": "private",
            "sender_email": bot.config["zulip"]["email"],  # Mensaje del bot
            "content": "test"
        }
        
        # No debería procesar el mensaje (no hay excepción ni respuesta)
        bot.handle_message(message)  # Should not crash

    def test_handle_message_ignore_non_private(self, bot):
        """Test ignorar mensajes que no sean privados"""
        message = {
            "type": "stream",  # No es privado
            "sender_email": "user@test.com",
            "content": "help"
        }
        
        bot.handle_message(message)  # Should not crash


    def test_handle_message_help(self, bot):
        """Test comando help"""
        
        message = {
            "type": "private",
            "sender_email": "student@test.com",
            "content": "help"
        }
        
        bot.handle_message(message)
        
        # Verificar que se envió respuesta
        bot.client.send_message.assert_called_once()
        call_args = bot.client.send_message.call_args[0][0]
        assert call_args["type"] == "private"
        assert call_args["to"] == "student@test.com"
        assert "Ayuda para Estudiantes" in call_args["content"]

    def test_handle_message_unknown_command(self, bot):
        """Test comando desconocido"""
        message = {
            "type": "private",
            "sender_email": "student@test.com",
            "content": "unknown_command"
        }
        bot.handle_message(message)
        
        # Debería responder con ayuda
        bot.client.send_message.assert_called_once()
        call_args = bot.client.send_message.call_args[0][0]
        assert "Ayuda" in call_args["content"]

    @patch.object(OraculusBot, "process_submit", side_effect=Exception("Test error"))
    def test_handle_message_error(self, mock_process, bot):
        """Test manejo de errores"""
        message = {
            "type": "private",
            "sender_email": "student@test.com",
            "content": "submit test"
        }
        bot.handle_message(message)
        
        # Debería enviar mensaje de error
        bot.client.send_message.assert_called_once()
        call_args = bot.client.send_message.call_args[0][0]
        assert "Error interno" in call_args["content"]


class TestSubmissionValidation:
    """Tests para validación de envíos"""

    @patch("oraculus_bot.requests.get")
    def test_submit_csv_with_multiple_columns(self, mock_get, bot):
        """Test CSV con múltiples columnas (inválido)"""
        mock_response = Mock()
        mock_response.content = b"id,pred\n1,0\n2,1"  # 2 columnas
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        message = {
            "sender_id": 123,
            "sender_email": "student@test.com",
            "sender_full_name": "Test Student",
            "content": "submit test_model\n[predictions.csv](https://test.zulipchat.com/file123)"
        }
        
        response = bot.process_submit(message)
        assert "exactamente 1 columna" in response

    @patch("oraculus_bot.requests.get")
    def test_submit_non_csv_file(self, mock_get, bot):
        """Test archivo que no es CSV"""
        mock_response = Mock()
        mock_response.content = b"some content"
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        message = {
            "sender_id": 123,
            "sender_email": "student@test.com",
            "sender_full_name": "Test Student",
            "content": "submit test_model\n[predictions.txt](https://test.zulipchat.com/file123)"
        }
        
        response = bot.process_submit(message)
        assert "Debes adjuntar un archivo CSV" in response

    def test_submit_past_deadline(self, bot):
        """Test envío después de la fecha límite"""
        # Cambiar deadline a fecha pasada
        bot.config["competition"]["deadline"] = "2020-01-01T00:00:00"
        
        message = {
            "sender_id": 123,
            "sender_email": "student@test.com",
            "content": "submit test_model"
        }
        
        response = bot.process_submit(message)
        assert "fecha límite" in response.lower()


class TestLeaderboards:
    """Tests para leaderboards"""

    def test_leaderboard_full_empty(self, bot):
        """Test leaderboard completo vacío"""
        response = bot.process_leaderboard_full()
        assert "No hay submissions" in response

    def test_leaderboard_full_with_data(self, bot):
        """Test leaderboard completo con datos"""
        # Crear envíos de prueba
        users = [
            {"user_id": 1, "email": "user1@test.com", "full_name": "User One"},
            {"user_id": 2, "email": "user2@test.com", "full_name": "User Two"}
        ]
        
        public_results = {"score": 15, "tp": 2, "tn": 1, "fp": 0, "fn": 1}
        private_results1 = {"score": 25, "tp": 3, "tn": 2, "fp": 1, "fn": 0}
        private_results2 = {"score": 20, "tp": 2, "tn": 3, "fp": 0, "fn": 1}
        
        bot.save_submission(users[0], "model1", "/path1", "check1",
                           public_results, private_results1, 5, "excellent")
        bot.save_submission(users[1], "model2", "/path2", "check2", 
                           public_results, private_results2, 4, "good")
        
        response = bot.process_leaderboard_full()
        assert "User One" in response
        assert "User Two" in response
        assert "25.0000" in response  # Score más alto primero


class TestBadgeSystem:
    """Tests específicos para el sistema de badges"""

    def test_badge_first_submission(self, bot):
        """Test badge de primer envío"""
        user_id = 123
        badges = bot.check_and_award_badges(user_id, 1, 10.0)
        assert "first_submission" in badges

    def test_badge_multiple_submissions(self, bot):
        """Test badges por cantidad de envíos"""
        user_id = 123
        
        # Badge 10 envíos
        badges = bot.check_and_award_badges(user_id, 10, 10.0)
        assert "submissions_10" in badges
        
        # Badge 50 envíos
        badges = bot.check_and_award_badges(user_id, 50, 10.0)
        assert "submissions_50" in badges

    def test_badge_no_duplicates(self, bot):
        """Test que no se otorguen badges duplicados"""
        user_id = 123
        
        # Primer badge
        badges1 = bot.check_and_award_badges(user_id, 1, 10.0)
        assert "first_submission" in badges1
        
        # Segundo llamado - no debería otorgar el mismo badge
        badges2 = bot.check_and_award_badges(user_id, 2, 15.0)
        assert "first_submission" not in badges2

    @patch("oraculus_bot.requests.get")
    def test_process_submit_teacher(self, mock_get, bot):
        """Test proceso de submit para profesor"""
        mock_response = Mock()
        mock_response.content = b"1\n3"  # Solo algunos positivos
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        message = {
            "sender_id": 999,
            "sender_email": "teacher@test.com",
            "sender_full_name": "Teacher",
            "content": "submit teacher_model\n[predictions.csv](https://test.zulipchat.com/file123)"
        }
        
        response = bot.process_submit(message, is_teacher=True)
        
        assert "Resultados para teacher_model" in response
        assert "Público:" in response
        assert "Privado:" in response
        assert "Matriz confusión" in response

    def test_process_submit_invalid_format(self, bot):
        """Test submit con formato inválido"""
        message = {
            "sender_id": 123,
            "sender_email": "student@test.com",
            "content": "submit"
        }
        
        response = bot.process_submit(message)
        assert "Formato incorrecto" in response

    @patch("oraculus_bot.requests.get")
    def test_process_submit_invalid_ids(self, mock_get, bot):
        """Test submit con IDs inválidos"""
        mock_response = Mock()
        mock_response.content = b"999\n1000"  # IDs que no existen
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        message = {
            "sender_id": 123,
            "sender_email": "student@test.com",
            "sender_full_name": "Test Student",
            "content": "submit test_model\n[predictions.csv](https://test" }

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

