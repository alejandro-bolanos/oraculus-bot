#!/usr/bin/env python3
"""
Tests de integración para OraculusBot
Ejecutar con: uv run pytest test_integration.py -v
"""

import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from oraculus_bot import OraculusBot


class TestFullWorkflow:
    """Tests del flujo completo de trabajo"""

    @pytest.fixture
    def complete_setup(self):
        """Setup completo para tests de integración"""
        temp_dir = tempfile.mkdtemp()

        # Crear datos maestros
        master_path = os.path.join(temp_dir, "master.csv")
        master_df = pd.DataFrame(
            {
                "id": list(range(1, 21)),  # 20 registros
                "true_label": [i % 2 for i in range(20)],  # Alternar 0,1
            }
        )
        master_df.to_csv(master_path, index=False, header=False)

        # Configuración completa
        config = {
            "zulip": {
                "email": "oraculus-bot@test.com",
                "api_key": "test-key",
                "site": "https://test.zulipchat.com",
            },
            "database": {"path": os.path.join(temp_dir, "test.db")},
            "teachers": ["teacher@test.com"],
            "master_data": {"path": master_path, "seed": 42},
            "submissions": {"path": os.path.join(temp_dir, "submissions")},
            "gain_matrix": {"tp": 2.0, "tn": 1.0, "fp": -1.0, "fn": -2.0},
            "gain_thresholds": [
                {
                    "min_score": 15,
                    "category": "excellent",
                    "message": "¡Excelente modelo!",
                    "emoji": "🏆",
                },
                {
                    "min_score": 5,
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
                "top_5_public": {"name": "Top 5 Público", "emoji": "🥇"},
            },
            "competition": {
                "name": "Test ML Competition",
                "description": "Competencia de prueba",
                "deadline": (datetime.now() + timedelta(days=7)).isoformat(),
            },
        }

        config_path = os.path.join(temp_dir, "config.json")
        with open(config_path, "w") as f:
            json.dump(config, f)

        yield {
            "temp_dir": temp_dir,
            "config_path": config_path,
            "master_path": master_path,
            "config": config,
        }

        shutil.rmtree(temp_dir)

    def test_complete_student_workflow(self, complete_setup):
        """Test flujo completo de estudiante"""
        setup = complete_setup

        with patch("oraculus_bot.zulip.Client") as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client

            # Crear CSV de predicciones
            predictions_csv = "1,0\n2,1\n3,0\n4,1\n5,0\n6,1\n7,0\n8,1\n9,0\n10,1\n11,0\n12,1\n13,0\n14,1\n15,0\n16,1\n17,0\n18,1\n19,0\n20,1\n"
            mock_client.get_file_content.return_value = predictions_csv.encode()

            # Inicializar bot
            bot = OraculusBot(setup["config_path"])

            # Simular mensaje de estudiante con envío
            student_message = {
                "type": "private",
                "sender_id": 12345,
                "sender_email": "student@test.com",
                "sender_full_name": "Test Student",
                "content": "submit mi_primer_modelo",
                "attachments": [{"name": "predictions.csv", "url": "test_url"}],
            }

            # Procesar envío
            response = bot.process_submit(student_message, is_teacher=False)

            # Verificar respuesta
            assert "ID Envío:" in response
            assert "Primer Envío" in response

            # Verificar que se guardó en BD
            conn = sqlite3.connect(bot.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM submissions WHERE user_id = ?", (12345,))
            submission = cursor.fetchone()
            assert submission is not None
            assert submission[4] == "mi_primer_modelo"  # submission_name

            # Verificar badge
            cursor.execute("SELECT * FROM user_badges WHERE user_id = ?", (12345,))
            badges = cursor.fetchall()
            assert len(badges) >= 1
            assert badges[0][2] == "first_submission"
            conn.close()

            # Test comando list submits
            list_response = bot.process_list_submits(12345)
            assert "mi_primer_modelo" in list_response

            # Test comando select
            submission_id = submission[0]
            select_response = bot.process_select(12345, f"select {submission_id}")
            assert "seleccionado" in select_response

            # Test comando badges
            badges_response = bot.process_badges(12345)
            assert "Primer Envío" in badges_response

    def test_teacher_workflow(self, complete_setup):
        """Test flujo completo de profesor"""
        setup = complete_setup

        with patch("oraculus_bot.zulip.Client") as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client

            predictions_csv = "1,1\n2,0\n3,1\n4,0\n5,1\n6,0\n7,1\n8,0\n9,1\n10,0\n11,1\n12,0\n13,1\n14,0\n15,1\n16,0\n17,1\n18,0\n19,1\n20,0\n"
            mock_client.get_file_content.return_value = predictions_csv.encode()

            bot = OraculusBot(setup["config_path"])

            # Test envío de profesor
            teacher_message = {
                "type": "private",
                "sender_id": 99999,
                "sender_email": "teacher@test.com",
                "sender_full_name": "Test Teacher",
                "content": "submit modelo_profesor",
                "attachments": [{"name": "teacher_predictions.csv", "url": "test_url"}],
            }

            response = bot.process_submit(teacher_message, is_teacher=True)

            student_message = {
                "type": "private",
                "sender_id": 99991,
                "sender_email": "student@test.com",
                "sender_full_name": "Test Student",
                "content": "submit modelo_student",
                "attachments": [{"name": "teacher_predictions.csv", "url": "test_url"}],
            }
            # Profesor debería ver scores completos
            assert "Público:" in response
            assert "Privado:" in response
            assert "Categoría:" in response

            response = bot.process_submit(student_message, is_teacher=False)

            # Test fake submissions
            fake_add_response = bot.process_fake_submit("fake_submit add FakeUser 25.5")
            assert "agregado" in fake_add_response

            # Test leaderboards
            public_board = bot.process_leaderboard_public()
            assert "FakeUser" in public_board

            full_board = bot.process_leaderboard_full()
            assert "Leaderboard Completo" in full_board

            # Test duplicates (debería estar vacío inicialmente)
            duplicates = bot.process_duplicates()
            assert "No se encontraron" in duplicates

    def test_multiple_students_competition(self, complete_setup):
        """Test competencia con múltiples estudiantes"""
        setup = complete_setup

        with patch("oraculus_bot.zulip.Client") as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client

            bot = OraculusBot(setup["config_path"])

            # Crear varios estudiantes con diferentes performances
            students = [
                {"id": 1001, "email": "student1@test.com", "name": "Student 1"},
                {"id": 1002, "email": "student2@test.com", "name": "Student 2"},
                {"id": 1003, "email": "student3@test.com", "name": "Student 3"},
            ]

            # Predicciones con diferentes calidades
            predictions = [
                # Student 1: Predicción perfecta
                "1,1\n2,0\n3,1\n4,0\n5,1\n6,0\n7,1\n8,0\n9,1\n10,0\n11,1\n12,0\n13,1\n14,0\n15,1\n16,0\n17,1\n18,0\n19,1\n20,0\n",
                # Student 2: Predicción mediocre
                "1,0\n2,0\n3,0\n4,0\n5,0\n6,1\n7,1\n8,1\n9,1\n10,1\n11,0\n12,0\n13,0\n14,0\n15,0\n16,1\n17,1\n18,1\n19,1\n20,1\n",
                # Student 3: Predicción aleatoria
                "1,1\n2,1\n3,0\n4,0\n5,1\n6,1\n7,0\n8,0\n9,1\n10,1\n11,0\n12,0\n13,1\n14,1\n15,0\n16,0\n17,1\n18,1\n19,0\n20,0\n",
            ]

            submission_ids = []

            for i, (student, pred) in enumerate(zip(students, predictions)):
                mock_client.get_file_content.return_value = pred.encode()

                message = {
                    "type": "private",
                    "sender_id": student["id"],
                    "sender_email": student["email"],
                    "sender_full_name": student["name"],
                    "content": f"submit modelo_v1_student_{i + 1}",
                    "attachments": [
                        {"name": f"pred_{i + 1}.csv", "url": f"test_url_{i + 1}"}
                    ],
                }

                response = bot.process_submit(message, is_teacher=False)

                # Extraer ID del envío
                lines = response.split("\n")
                for line in lines:
                    if "ID Envío:" in line:
                        submission_id = int(line.split(":**")[1].strip())
                        submission_ids.append(submission_id)
                        break

                # Seleccionar modelo
                select_response = bot.process_select(
                    student["id"], f"select {submission_ids[-1]}"
                )
                assert "seleccionado" in select_response

            # Verificar leaderboard completo
            full_board = bot.process_leaderboard_full()
            assert "Student 1" in full_board
            assert "Student 2" in full_board
            assert "Student 3" in full_board

            # Test múltiples envíos del mismo estudiante
            mock_client.get_file_content.return_value = predictions[0].encode()

            # Student 1 hace más envíos
            for j in range(2, 11):  # 9 envíos más (total 10)
                message = {
                    "type": "private",
                    "sender_id": students[0]["id"],
                    "sender_email": students[0]["email"],
                    "sender_full_name": students[0]["name"],
                    "content": f"submit modelo_v{j}_student_1",
                    "attachments": [
                        {"name": f"pred_1_v{j}.csv", "url": f"test_url_1_v{j}"}
                    ],
                }

                response = bot.process_submit(message, is_teacher=False)

                # En el envío #10 debería obtener badge
                if j == 10:
                    assert "10 Envíos" in response

            # Verificar badge de 10 envíos
            badges_response = bot.process_badges(students[0]["id"])
            assert "10 Envíos" in badges_response

    def test_deadline_enforcement(self, complete_setup):
        """Test aplicación de fecha límite"""
        setup = complete_setup

        with patch("oraculus_bot.zulip.Client") as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client

            # Cambiar deadline a ayer
            config = setup["config"]
            config["competition"]["deadline"] = (
                datetime.now() - timedelta(days=1)
            ).isoformat()

            with open(setup["config_path"], "w") as f:
                json.dump(config, f)

            bot = OraculusBot(setup["config_path"])

            predictions_csv = "1,0\n2,1\n3,0\n4,1\n5,0\n6,1\n7,0\n8,1\n9,0\n10,1\n11,0\n12,1\n13,0\n14,1\n15,0\n16,1\n17,0\n18,1\n19,0\n20,1\n"
            mock_client.get_file_content.return_value = predictions_csv.encode()

            # Estudiante intenta enviar después del deadline
            student_message = {
                "type": "private",
                "sender_id": 12345,
                "sender_email": "late_student@test.com",
                "sender_full_name": "Late Student",
                "content": "submit modelo_tardio",
                "attachments": [{"name": "late_predictions.csv", "url": "test_url"}],
            }

            response = bot.process_submit(student_message, is_teacher=False)
            assert "fecha límite" in response.lower()

            # Profesor puede enviar después del deadline
            teacher_message = {
                "type": "private",
                "sender_id": 99999,
                "sender_email": "teacher@test.com",
                "sender_full_name": "Test Teacher",
                "content": "submit modelo_profesor_post_deadline",
                "attachments": [{"name": "teacher_late.csv", "url": "test_url"}],
            }

            response = bot.process_submit(teacher_message, is_teacher=True)
            assert "Público:" in response  # Debería funcionar para profesores

    def test_error_handling_integration(self, complete_setup):
        """Test manejo de errores en flujo completo"""
        setup = complete_setup

        with patch("oraculus_bot.zulip.Client") as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client

            bot = OraculusBot(setup["config_path"])

            # Test CSV con formato incorrecto (3 columnas)
            bad_csv = "1,0,extra\n2,1,extra\n3,0,extra\n"
            mock_client.get_file_content.return_value = bad_csv.encode()

            message = {
                "type": "private",
                "sender_id": 12345,
                "sender_email": "student@test.com",
                "sender_full_name": "Test Student",
                "content": "submit bad_format",
                "attachments": [{"name": "bad.csv", "url": "test_url"}],
            }

            response = bot.process_submit(message, is_teacher=False)
            assert "2 columnas" in response

            # Test CSV con IDs incorrectos
            wrong_ids_csv = "100,0\n101,1\n102,0\n"  # IDs que no existen
            mock_client.get_file_content.return_value = wrong_ids_csv.encode()

            message["content"] = "submit wrong_ids"
            response = bot.process_submit(message, is_teacher=False)
            assert "IDs incorrectos" in response

            # Test CSV con valores no binarios
            non_binary_csv = "1,0\n2,1\n3,2\n4,1\n5,0\n6,1\n7,0\n8,1\n9,0\n10,1\n11,0\n12,1\n13,0\n14,1\n15,0\n16,1\n17,0\n18,1\n19,0\n20,1\n"
            mock_client.get_file_content.return_value = non_binary_csv.encode()

            message["content"] = "submit non_binary"
            response = bot.process_submit(message, is_teacher=False)
            assert "binarios" in response

    def test_message_routing_integration(self, complete_setup):
        """Test enrutamiento completo de mensajes"""
        setup = complete_setup

        with patch("oraculus_bot.zulip.Client") as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            mock_client.send_message.return_value = {"result": "success"}

            bot = OraculusBot(setup["config_path"])

            # Test mensaje de ayuda de estudiante
            student_help_msg = {
                "type": "private",
                "sender_email": "student@test.com",
                "content": "help",
            }

            bot.handle_message(student_help_msg)

            # Verificar que se envió respuesta
            assert mock_client.send_message.called
            call_args = mock_client.send_message.call_args[0][0]
            assert call_args["to"] == "student@test.com"
            assert "Ayuda para Estudiantes" in call_args["content"]

            # Reset mock
            mock_client.send_message.reset_mock()

            # Test mensaje de ayuda de profesor
            teacher_help_msg = {
                "type": "private",
                "sender_email": "teacher@test.com",
                "content": "help",
            }

            bot.handle_message(teacher_help_msg)

            call_args = mock_client.send_message.call_args[0][0]
            assert call_args["to"] == "teacher@test.com"
            assert "Ayuda para Profesores" in call_args["content"]

            # Test que el bot ignore sus propios mensajes
            mock_client.send_message.reset_mock()

            bot_own_msg = {
                "type": "private",
                "sender_email": "oraculus-bot@test.com",  # Email del bot
                "content": "help",
            }

            bot.handle_message(bot_own_msg)

            # No debería haber enviado respuesta
            assert not mock_client.send_message.called

            # Test mensaje de canal público (debería ignorarse)
            public_msg = {
                "type": "stream",
                "sender_email": "student@test.com",
                "content": "help",
            }

            bot.handle_message(public_msg)

            # No debería haber enviado respuesta
            assert not mock_client.send_message.called


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
