#!/usr/bin/env python3
"""
Tests unitarios para OraculusBot
Ejecutar con: uv run pytest test_oraculus_bot.py -v
"""

import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

# Importar la clase a testear
from oraculus_bot import OraculusBot


class TestOraculusBot:

    @pytest.fixture
    def temp_dir(self):
        """Fixture para directorio temporal"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def config_data(self, temp_dir):
        """Fixture para datos de configuración"""
        return {
            "zulip": {
                "email": "bot@test.com",
                "api_key": "test-key",
                "site": "https://test.zulipchat.com",
            },
            "database": {"path": os.path.join(temp_dir, "test.db")},
            "teachers": ["teacher@test.com"],
            "master_data": {"path": os.path.join(temp_dir, "master.csv"), "seed": 42},
            "submissions": {"path": os.path.join(temp_dir, "submissions")},
            "gain_matrix": {"tp": 1.0, "tn": 0.5, "fp": -0.1, "fn": -0.5},
            "gain_thresholds": [
                {
                    "min_score": 10,
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
            "badges": {"first_submission": {"name": "Primer Envío", "emoji": "🎯"}},
            "competition": {
                "name": "Test Competition",
                "description": "Test competition",
                "deadline": (datetime.now() + timedelta(days=30)).isoformat(),
            },
        }

    @pytest.fixture
    def config_file(self, config_data, temp_dir):
        """Fixture para archivo de configuración"""
        config_path = os.path.join(temp_dir, "config.json")
        with open(config_path, "w") as f:
            json.dump(config_data, f)
        return config_path

    @pytest.fixture
    def master_data(self, config_data):
        """Fixture para datos maestros"""
        master_path = config_data["master_data"]["path"]
        df = pd.DataFrame(
            {
                "id": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                "true_label": [0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
            }
        )
        df.to_csv(master_path, index=False, header=False)
        return master_path

    @pytest.fixture
    def bot(self, config_file, master_data):
        """Fixture para instancia del bot"""
        with patch("oraculus_bot.zulip.Client"):
            bot = OraculusBot(config_file)
            return bot


class TestScoreCalculation(TestOraculusBot):
    """Tests de cálculo de scores"""

    def test_calculate_scores_perfect_prediction(self, bot):
        """Test cálculo con predicción perfecta"""
        # Crear predicciones perfectas
        predictions_df = pd.DataFrame(
            {
                "id": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                "prediction": [0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
            }
        )

        public_results, private_results = bot.calculate_scores(predictions_df)

        # Con predicción perfecta, solo deberían haber TP y TN
        assert public_results["fp"] == 0
        assert public_results["fn"] == 0
        assert private_results["fp"] == 0
        assert private_results["fn"] == 0

        # Score debería ser positivo
        assert public_results["score"] > 0
        assert private_results["score"] > 0

    def test_calculate_scores_all_wrong(self, bot):
        """Test cálculo con todas las predicciones incorrectas"""
        predictions_df = pd.DataFrame(
            {
                "id": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                "prediction": [1, 0, 1, 0, 1, 0, 1, 0, 1, 0],  # Opuesto a la verdad
            }
        )

        public_results, private_results = bot.calculate_scores(predictions_df)

        # Con predicciones opuestas, solo deberían haber FP y FN
        assert public_results["tp"] == 0
        assert public_results["tn"] == 0
        assert private_results["tp"] == 0
        assert private_results["tn"] == 0

    def test_threshold_category(self, bot):
        """Test categorización por umbrales"""
        # Score alto
        category = bot.get_threshold_category(15)
        assert category == "good"

        # Score bajo
        category = bot.get_threshold_category(5)
        assert category == "basic"


class TestBadgeSystem(TestOraculusBot):
    """Tests del sistema de badges"""

    def test_first_submission_badge(self, bot):
        """Test badge de primer envío"""
        user_id = 123
        new_badges = bot.check_and_award_badges(user_id, 1, 10.0)
        assert "first_submission" in new_badges

    def test_no_duplicate_badges(self, bot):
        """Test que no se otorguen badges duplicados"""
        user_id = 123

        # Primer envío
        badges1 = bot.check_and_award_badges(user_id, 1, 10.0)
        assert "first_submission" in badges1

        # Segundo envío
        badges2 = bot.check_and_award_badges(user_id, 2, 12.0)
        assert "first_submission" not in badges2

    def test_multiple_submission_badges(self, bot):
        """Test badges por cantidad de envíos"""
        user_id = 123

        # 10 envíos
        badges = bot.check_and_award_badges(user_id, 10, 10.0)
        assert "submissions_10" in badges

        # 50 envíos
        badges = bot.check_and_award_badges(user_id, 50, 10.0)
        assert "submissions_50" in badges


class TestCommandHandling(TestOraculusBot):
    """Tests de manejo de comandos"""

    def test_help_command_student(self, bot):
        """Test comando help para estudiante"""
        response = bot.get_help_message(is_teacher=False)
        assert "Ayuda para Estudiantes" in response
        assert "submit <nombre>" in response
        assert "badges" in response

    def test_help_command_teacher(self, bot):
        """Test comando help para profesor"""
        response = bot.get_help_message(is_teacher=True)
        assert "Ayuda para Profesores" in response
        assert "duplicates" in response
        assert "leaderboard full" in response

    def test_is_teacher_identification(self, bot):
        """Test identificación de profesores"""
        assert bot.is_teacher("teacher@test.com")
        assert not bot.is_teacher("student@test.com")

    @patch("oraculus_bot.OraculusBot")
    def test_handle_own_message_ignored(self, mock_client, bot):
        """Test que el bot ignore sus propios mensajes"""
        message = {
            "type": "private",
            "sender_email": bot.config["zulip"]["email"],  # Mensaje del propio bot
            "content": "help",
        }

        # No debería procesar el mensaje
        bot.handle_message(message)
        mock_client.send_message.assert_not_called()


class TestSubmissionValidation(TestOraculusBot):
    """Tests de validación de envíos"""

    def test_validate_csv_format(self, bot):
        """Test validación formato CSV"""
        # CSV correcto
        correct_df = pd.DataFrame(
            {
                "id": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                "prediction": [0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
            }
        )

        # Debería pasar validación
        submitted_ids = set(correct_df.iloc[:, 0])
        expected_ids = set(bot.master_df["id"])
        assert submitted_ids == expected_ids

        predictions = correct_df.iloc[:, 1]
        assert all(pred in [0, 1] for pred in predictions)

    def test_validate_missing_ids(self, bot):
        """Test validación IDs faltantes"""
        # CSV con IDs faltantes
        incomplete_df = pd.DataFrame(
            {"id": [1, 2, 3], "prediction": [0, 1, 0]}  # Faltan IDs
        )

        submitted_ids = set(incomplete_df.iloc[:, 0])
        expected_ids = set(bot.master_df["id"])
        assert submitted_ids != expected_ids

    def test_validate_non_binary_predictions(self, bot):
        """Test validación predicciones no binarias"""
        # CSV con predicciones no binarias
        invalid_df = pd.DataFrame(
            {
                "id": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                "prediction": [0, 1, 2, 1, 0, 1, 0, 1, 0, 1],  # Contiene '2'
            }
        )

        predictions = invalid_df.iloc[:, 1]
        assert not all(pred in [0, 1] for pred in predictions)


class TestLeaderboard(TestOraculusBot):
    """Tests del sistema de leaderboard"""

    def test_fake_submission_add(self, bot):
        """Test agregar fake submission"""
        response = bot.process_fake_submit("fake_submit add TestUser 15.5")
        assert "agregado" in response

        # Verificar en base de datos
        conn = sqlite3.connect(bot.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM fake_submissions WHERE name = 'TestUser'")
        result = cursor.fetchone()
        conn.close()

        assert result is not None
        assert result[2] == 15.5  # public_score

    def test_fake_submission_remove(self, bot):
        """Test remover fake submission"""
        # Primero agregar
        bot.process_fake_submit("fake_submit add TestUser2 20.0")

        # Luego remover
        response = bot.process_fake_submit("fake_submit remove TestUser2")
        assert "eliminado" in response

        # Verificar que se eliminó
        conn = sqlite3.connect(bot.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM fake_submissions WHERE name = 'TestUser2'")
        result = cursor.fetchone()
        conn.close()

        assert result is None


class TestEdgeCases(TestOraculusBot):
    """Tests de casos límite"""

    def test_empty_master_data(self, temp_dir):
        """Test con datos maestros vacíos"""
        # Crear archivo maestro vacío
        empty_master_path = os.path.join(temp_dir, "empty_master.csv")
        pd.DataFrame().to_csv(empty_master_path, index=False, header=False)

        config_data = {
            "zulip": {"email": "bot@test.com", "api_key": "key", "site": "site"},
            "database": {"path": os.path.join(temp_dir, "test.db")},
            "teachers": [],
            "master_data": {"path": empty_master_path, "seed": 42},
            "submissions": {"path": temp_dir},
            "gain_matrix": {"tp": 1, "tn": 1, "fp": -1, "fn": -1},
            "gain_thresholds": [
                {"min_score": 0, "category": "basic", "message": "Basic"}
            ],
            "badges": {},
            "competition": {
                "name": "Test",
                "description": "Test",
                "deadline": "2025-12-31T23:59:59",
            },
        }

        config_path = os.path.join(temp_dir, "config.json")
        with open(config_path, "w") as f:
            json.dump(config_data, f)

        # Debería fallar al cargar datos vacíos
        with patch("oraculus_bot.zulip.Client"):
            with pytest.raises(Exception):
                OraculusBot(config_path)

    def test_expired_deadline(self, bot):
        """Test envío después de fecha límite"""
        # Cambiar deadline a ayer
        old_deadline = bot.config["competition"]["deadline"]
        yesterday = (datetime.now() - timedelta(days=1)).isoformat()
        bot.config["competition"]["deadline"] = yesterday

        message = {
            "sender_id": 123,
            "sender_email": "student@test.com",
            "sender_full_name": "Test Student",
            "content": "submit test_model",
            "attachments": [{"name": "test.csv", "url": "test_url"}],
        }

        response = bot.process_submit(message, is_teacher=False)
        assert "fecha límite" in response

        # Restaurar deadline
        bot.config["competition"]["deadline"] = old_deadline


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
