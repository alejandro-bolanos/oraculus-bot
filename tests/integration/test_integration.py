import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pandas as pd
import pytest

from oraculus_bot import OraculusBot


@pytest.fixture
def integration_setup():
    """Setup completo para tests de integración"""
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_dir = Path(tmpdir)

        # Crear datos maestros realistas
        master_data = pd.DataFrame(
            {
                "id": list(range(1, 101)),  # 100 registros
                "clase_binaria": [1 if i % 3 == 0 else 0 for i in range(1, 101)],  # ~33% positivos
                "dataset": [
                    "public" if i <= 30 else "private" for i in range(1, 101)
                ],  # 30% público
            }
        )

        master_path = temp_dir / "master_data.csv"
        master_data.to_csv(master_path, index=False)

        # Configuración completa
        config = {
            "zulip": {
                "email": "oraculus@test.zulipchat.com",
                "api_key": "test-api-key-123",
                "site": "https://test.zulipchat.com",
            },
            "database": {"path": str(temp_dir / "competition.db")},
            "teachers": ["prof1@uni.edu", "prof2@uni.edu"],
            "master_data": {"path": str(master_path)},
            "logs": {"path": str(temp_dir / "logs")},
            "submissions": {"path": str(temp_dir / "submissions")},
            "gain_matrix": {"tp": 100, "tn": 10, "fp": -50, "fn": -100},
            "gain_thresholds": [
                {
                    "min_score": 1000,
                    "category": "excellent",
                    "message": "¡Modelo excepcional!",
                    "emoji": "🏆",
                },
                {"min_score": 500, "category": "good", "message": "Buen modelo", "emoji": "👍"},
                {"min_score": 0, "category": "basic", "message": "Modelo básico", "emoji": "💪"},
                {
                    "min_score": -1000,
                    "category": "poor",
                    "message": "Necesita mejoras",
                    "emoji": "📚",
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
                "name": "ML Competition 2024",
                "description": "Competencia de Machine Learning con OraculusBot",
                "deadline": "2030-12-31T23:59:59",
            },
        }

        config_path = temp_dir / "config.json"
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        yield {
            "temp_dir": temp_dir,
            "config_path": config_path,
            "master_data": master_data,
            "positive_ids": set(master_data[master_data["clase_binaria"] == 1]["id"]),
        }


class TestFullWorkflow:
    """Tests de flujos completos de trabajo"""

    @patch("oraculus_bot.oraculus_bot.zulip.Client")
    @patch("oraculus_bot.oraculus_bot.requests.get")
    def test_complete_student_workflow(self, mock_requests, mock_zulip_client, integration_setup):
        """Test flujo completo de un estudiante"""
        setup = integration_setup
        mock_client = Mock()
        mock_zulip_client.return_value = mock_client

        # Inicializar bot
        bot = OraculusBot(str(setup["config_path"]))

        # Simular estudiante
        student_user_id = 12345
        student_email = "student@uni.edu"
        student_name = "Ana García"

        # 1. Primer envío del estudiante
        perfect_predictions = setup["positive_ids"]  # Predicciones perfectas
        csv_content = "\n".join([str(id_) for id_ in perfect_predictions])

        mock_response = Mock()
        mock_response.content = csv_content.encode()
        mock_response.raise_for_status.return_value = None
        mock_requests.return_value = mock_response

        submit_message = {
            "type": "private",
            "sender_id": student_user_id,
            "sender_email": student_email,
            "sender_full_name": student_name,
            "content": "submit modelo_perfecto_v1\n[predictions.csv](https://test.zulipchat.com/file123)",
        }

        # Procesar envío
        response = bot.process_submit(submit_message)

        # Verificaciones del primer envío
        assert "¡Modelo excepcional!" in response  # Categoría excellent
        assert "ID Envío:" in response
        assert "Primer Envío" in response  # Badge de primer envío

        # 2. Ver badges ganados
        badges_message = {
            "type": "private",
            "sender_id": student_user_id,
            "sender_email": student_email,
            "content": "badges",
        }

        bot.handle_message(badges_message)

        # Verificar que se envió respuesta con badges
        assert mock_client.send_message.called
        last_call = mock_client.send_message.call_args[0][0]
        assert "Primer Envío" in last_call["content"]

        # 3. Segundo envío (peor)
        mock_client.reset_mock()
        partial_predictions = list(setup["positive_ids"])[: len(setup["positive_ids"]) // 4]
        csv_content2 = "\n".join([str(id_) for id_ in partial_predictions])

        mock_response.content = csv_content2.encode()

        submit_message2 = {
            "type": "private",
            "sender_id": student_user_id,
            "sender_email": student_email,
            "sender_full_name": student_name,
            "content": "submit modelo_parcial_v2\n[predictions2.csv](https://test.zulipchat.com/file456)",
        }

        response2 = bot.process_submit(submit_message2)

        # No debería ser excellent esta vez
        assert "¡Modelo excepcional!" not in response2
        assert "Primer Envío" not in response2  # No otorgar badge duplicado

        # 4. Listar envíos
        list_message = {
            "type": "private",
            "sender_id": student_user_id,
            "sender_email": student_email,
            "content": "list submits",
        }

        bot.handle_message(list_message)

        last_call = mock_client.send_message.call_args[0][0]
        assert "modelo_perfecto_v1" in last_call["content"]
        assert "modelo_parcial_v2" in last_call["content"]

        # 5. Seleccionar mejor modelo
        mock_client.reset_mock()
        select_message = {
            "type": "private",
            "sender_id": student_user_id,
            "sender_email": student_email,
            "content": "select 1",  # Seleccionar el primer envío
        }

        bot.handle_message(select_message)

        last_call = mock_client.send_message.call_args[0][0]
        assert "seleccionado" in last_call["content"].lower()
        assert "Primera Selección" in last_call["content"]  # Badge de primera selección

        # 6. Ver leaderboard público
        mock_client.reset_mock()
        leaderboard_message = {
            "type": "private",
            "sender_id": student_user_id,
            "sender_email": student_email,
            "content": "leaderboard public",
        }

        # Este comando no existe para estudiantes, debería mostrar ayuda
        bot.handle_message(leaderboard_message)

        last_call = mock_client.send_message.call_args[0][0]
        assert "Ayuda" in last_call["content"]

    @patch("oraculus_bot.oraculus_bot.zulip.Client")
    @patch("oraculus_bot.oraculus_bot.requests.get")
    def test_complete_teacher_workflow(self, mock_requests, mock_zulip_client, integration_setup):
        """Test flujo completo de un profesor"""
        setup = integration_setup
        mock_client = Mock()
        mock_zulip_client.return_value = mock_client

        bot = OraculusBot(str(setup["config_path"]))

        teacher_email = "prof1@uni.edu"
        teacher_user_id = 99999

        # 1. Profesor envía modelo de prueba
        test_predictions = list(setup["positive_ids"])[:10]  # Solo algunos
        csv_content = "\n".join([str(id_) for id_ in test_predictions])

        mock_response = Mock()
        mock_response.content = csv_content.encode()
        mock_response.raise_for_status.return_value = None
        mock_requests.return_value = mock_response

        teacher_submit = {
            "type": "private",
            "sender_id": teacher_user_id,
            "sender_email": teacher_email,
            "sender_full_name": "Prof. Smith",
            "content": "submit baseline_model\n[baseline.csv](https://test.zulipchat.com/file789)",
        }

        response = bot.process_submit(teacher_submit, is_teacher=True)

        # Profesor ve resultados completos
        assert "Resultados para baseline_model" in response
        assert "Público:" in response
        assert "Privado:" in response
        assert "Matriz confusión" in response

        # 2. Agregar fake submission al leaderboard
        fake_submit_msg = {
            "type": "private",
            "sender_id": teacher_user_id,
            "sender_email": teacher_email,
            "content": "fake_submit add RandomBaseline 150.5",
        }

        bot.handle_message(fake_submit_msg)

        last_call = mock_client.send_message.call_args[0][0]
        assert "agregado" in last_call["content"].lower()

        # Simular estudiante
        student_user_id = 12345
        student_email = "student@uni.edu"
        student_name = "Ana García"

        perfect_predictions = setup["positive_ids"]  # Predicciones perfectas
        csv_content = "\n".join([str(id_) for id_ in perfect_predictions])

        mock_response = Mock()
        mock_response.content = csv_content.encode()
        mock_response.raise_for_status.return_value = None
        mock_requests.return_value = mock_response

        submit_message = {
            "type": "private",
            "sender_id": student_user_id,
            "sender_email": student_email,
            "sender_full_name": student_name,
            "content": "submit modelo_perfecto_v1\n[predictions.csv](https://test.zulipchat.com/file123)",
        }

        # Procesar envío
        response = bot.process_submit(submit_message)

        # 3. Ver leaderboard completo
        mock_client.reset_mock()
        full_leaderboard_msg = {
            "type": "private",
            "sender_id": teacher_user_id,
            "sender_email": teacher_email,
            "content": "leaderboard full",
        }

        bot.handle_message(full_leaderboard_msg)

        last_call = mock_client.send_message.call_args[0][0]
        assert "Leaderboard Completo" in last_call["content"]

        # 4. Ver leaderboard público
        mock_client.reset_mock()
        public_leaderboard_msg = {
            "type": "private",
            "sender_id": teacher_user_id,
            "sender_email": teacher_email,
            "content": "leaderboard public",
        }

        bot.handle_message(public_leaderboard_msg)

        last_call = mock_client.send_message.call_args[0][0]
        assert "Leaderboard Público" in last_call["content"]
        assert "RandomBaseline" in last_call["content"]

        # 5. Eliminar fake submission
        mock_client.reset_mock()
        remove_fake_msg = {
            "type": "private",
            "sender_id": teacher_user_id,
            "sender_email": teacher_email,
            "content": "fake_submit remove RandomBaseline",
        }

        bot.handle_message(remove_fake_msg)

        last_call = mock_client.send_message.call_args[0][0]
        assert "eliminado" in last_call["content"].lower()


class TestMultiUserScenarios:
    """Tests con múltiples usuarios"""

    @patch("oraculus_bot.oraculus_bot.zulip.Client")
    @patch("oraculus_bot.oraculus_bot.requests.get")
    def test_competition_with_multiple_students(
        self, mock_requests, mock_zulip_client, integration_setup
    ):
        """Test competencia con múltiples estudiantes"""
        setup = integration_setup
        mock_client = Mock()
        mock_zulip_client.return_value = mock_client

        bot = OraculusBot(str(setup["config_path"]))

        # Definir estudiantes con diferentes niveles
        students = [
            {"id": 1001, "email": "alice@uni.edu", "name": "Alice Johnson", "skill": "high"},
            {"id": 1002, "email": "bob@uni.edu", "name": "Bob Wilson", "skill": "medium"},
            {"id": 1003, "email": "charlie@uni.edu", "name": "Charlie Brown", "skill": "low"},
        ]

        positive_ids = setup["positive_ids"]

        # Simular envíos de cada estudiante
        for i, student in enumerate(students):
            # Diferentes estrategias según skill level
            if student["skill"] == "high":
                # Alice hace predicciones casi perfectas
                predictions = list(positive_ids)[:-2]  # Pierde solo 2
            elif student["skill"] == "medium":
                # Bob acierta ~70%
                predictions = list(positive_ids)[: -len(positive_ids) // 3]
            else:
                # Charlie hace predicciones aleatorias (solo algunos positivos)
                predictions = list(positive_ids)[: len(positive_ids) // 2]

            csv_content = "\n".join([str(id_) for id_ in predictions])

            mock_response = Mock()
            mock_response.content = csv_content.encode()
            mock_response.raise_for_status.return_value = None
            mock_requests.return_value = mock_response

            submit_message = {
                "type": "private",
                "sender_id": student["id"],
                "sender_email": student["email"],
                "sender_full_name": student["name"],
                "content": f"submit {student['name'].lower().replace(' ', '_')}_model_v1\n[{student['name'].lower()}.csv](https://test.zulipchat.com/file{i})",
            }

            response = bot.process_submit(submit_message)

            # Verificar que cada estudiante recibe respuesta apropiada
            assert "ID Envío:" in response
            assert "Primer Envío" in response

            # Seleccionar modelo para leaderboard
            select_msg = {
                "type": "private",
                "sender_id": student["id"],
                "sender_email": student["email"],
                "content": f"select {i + 1}",
            }

            bot.handle_message(select_msg)

        # Verificar leaderboard final
        teacher_msg = {
            "type": "private",
            "sender_id": 99999,
            "sender_email": "prof1@uni.edu",
            "content": "leaderboard full",
        }

        bot.handle_message(teacher_msg)

        last_call = mock_client.send_message.call_args[0][0]
        leaderboard_content = last_call["content"]

        # Alice debería estar primera (mejor skill)
        alice_pos = leaderboard_content.find("Alice Johnson")
        bob_pos = leaderboard_content.find("Bob Wilson")
        charlie_pos = leaderboard_content.find("Charlie Brown")

        assert alice_pos < bob_pos < charlie_pos  # Orden por posición en texto


class TestErrorHandlingAndEdgeCases:
    """Tests de manejo de errores y casos límite"""


    @patch("oraculus_bot.oraculus_bot.zulip.Client")
    @patch("oraculus_bot.oraculus_bot.requests.get")
    def test_network_error_handling(self, mock_requests, mock_zulip_client, integration_setup):
        """Test manejo de errores de red"""
        setup = integration_setup
        mock_client = Mock()
        mock_zulip_client.return_value = mock_client

        bot = OraculusBot(str(setup["config_path"]))

        # Simular error de red
        mock_requests.side_effect = Exception("Network error")

        submit_message = {
            "type": "private",
            "sender_id": 123,
            "sender_email": "student@uni.edu",
            "sender_full_name": "Test Student",
            "content": "submit test_model\n[predictions.csv](https://test.zulipchat.com/file123)",
        }

        response = bot.process_submit(submit_message)
        assert "❌ Debes adjuntar un archivo CSV" in response

    @patch("oraculus_bot.oraculus_bot.zulip.Client")
    @patch("oraculus_bot.oraculus_bot.requests.get")
    def test_malformed_csv_handling(self, mock_requests, mock_zulip_client, integration_setup):
        """Test manejo de CSV malformado"""
        setup = integration_setup
        mock_client = Mock()
        mock_zulip_client.return_value = mock_client

        bot = OraculusBot(str(setup["config_path"]))

        # CSV con datos inválidos
        mock_response = Mock()
        mock_response.content = b"invalid,csv,content\nwith,multiple,columns,and,errors"
        mock_response.raise_for_status.return_value = None
        mock_requests.return_value = mock_response

        submit_message = {
            "type": "private",
            "sender_id": 123,
            "sender_email": "student@uni.edu",
            "sender_full_name": "Test Student",
            "content": "submit bad_model\n[bad.csv](https://test.zulipchat.com/file123)",
        }

        response = bot.process_submit(submit_message)
        assert "Error leyendo el archivo CSV" in response


class TestDataIntegrity:
    """Tests de integridad de datos"""

    @patch("oraculus_bot.oraculus_bot.zulip.Client")
    def test_score_calculation_consistency(self, mock_zulip_client, integration_setup):
        """Test consistencia en cálculo de scores"""
        setup = integration_setup
        mock_client = Mock()
        mock_zulip_client.return_value = mock_client

        bot = OraculusBot(str(setup["config_path"]))

        positive_ids = setup["positive_ids"]

        # Calcular scores múltiples veces con los mismos datos
        scores1 = bot.calculate_scores(positive_ids)
        scores2 = bot.calculate_scores(positive_ids)
        scores3 = bot.calculate_scores(positive_ids)

        # Todos los resultados deben ser idénticos
        assert scores1[0]["score"] == scores2[0]["score"] == scores3[0]["score"]
        assert scores1[1]["score"] == scores2[1]["score"] == scores3[1]["score"]

        # Verificar métricas individuales
        for metric in ["tp", "tn", "fp", "fn"]:
            assert scores1[0][metric] == scores2[0][metric] == scores3[0][metric]
            assert scores1[1][metric] == scores2[1][metric] == scores3[1][metric]

    @patch("oraculus_bot.oraculus_bot.zulip.Client")
    @patch("oraculus_bot.oraculus_bot.requests.get")
    def test_duplicate_detection_accuracy(
        self, mock_requests, mock_zulip_client, integration_setup
    ):
        """Test precisión de detección de duplicados"""
        setup = integration_setup
        mock_client = Mock()
        mock_zulip_client.return_value = mock_client

        bot = OraculusBot(str(setup["config_path"]))

        # Crear contenido idéntico para dos usuarios diferentes
        positive_ids = list(setup["positive_ids"])[:10]
        csv_content = "\n".join([str(id_) for id_ in positive_ids])

        mock_response = Mock()
        mock_response.content = csv_content.encode()
        mock_response.raise_for_status.return_value = None
        mock_requests.return_value = mock_response

        # Usuario 1
        submit1 = {
            "type": "private",
            "sender_id": 1001,
            "sender_email": "alice@uni.edu",
            "sender_full_name": "Alice Johnson",
            "content": "submit alice_model\n[alice.csv](https://test.zulipchat.com/file1)",
        }

        # Usuario 2 con mismo contenido
        submit2 = {
            "type": "private",
            "sender_id": 1002,
            "sender_email": "bob@uni.edu",
            "sender_full_name": "Bob Wilson",
            "content": "submit bob_model\n[bob.csv](https://test.zulipchat.com/file2)",
        }

        # Procesar ambos envíos
        bot.process_submit(submit1)
        bot.process_submit(submit2)

        # Verificar detección de duplicados
        duplicates_response = bot.process_duplicates()
        assert "Duplicados" in duplicates_response
        assert "alice@uni.edu" in duplicates_response
        assert "bob@uni.edu" in duplicates_response


class TestConfigurationValidation:
    """Tests de validación de configuración"""

    def test_missing_required_config_fields(self, integration_setup):
        """Test campos requeridos faltantes en configuración"""
        setup = integration_setup

        # Cargar config válida
        with open(setup["config_path"]) as f:
            config = json.load(f)

        # Eliminar campo requerido
        del config["master_data"]

        # Guardar config inválida
        invalid_config_path = setup["temp_dir"] / "invalid_config.json"
        with open(invalid_config_path, "w") as f:
            json.dump(config, f)

        # Debería fallar al inicializar
        with patch("oraculus_bot.oraculus_bot.zulip.Client"), pytest.raises(KeyError):
            OraculusBot(str(invalid_config_path))

    def test_invalid_gain_matrix(self, integration_setup):
        """Test matriz de ganancias inválida"""
        setup = integration_setup

        with open(setup["config_path"]) as f:
            config = json.load(f)

        # Matriz de ganancias incompleta
        config["gain_matrix"] = {"tp": 1, "tn": 1}  # Faltan fp, fn

        invalid_config_path = setup["temp_dir"] / "invalid_gain_config.json"
        with open(invalid_config_path, "w") as f:
            json.dump(config, f)

        with patch("oraculus_bot.oraculus_bot.zulip.Client"):
            bot = OraculusBot(str(invalid_config_path))

            # Debería fallar al calcular scores
            with pytest.raises(KeyError):
                bot.calculate_scores({1, 2, 3})


class TestRobustnessAndRecovery:
    """Tests de robustez y recuperación"""

    @patch("oraculus_bot.oraculus_bot.zulip.Client")
    def test_graceful_degradation_on_errors(self, mock_zulip_client, integration_setup):
        """Test degradación elegante ante errores"""
        setup = integration_setup
        mock_client = Mock()
        mock_zulip_client.return_value = mock_client

        bot = OraculusBot(str(setup["config_path"]))

        # Simular error en handle_message
        with patch.object(bot, "process_submit", side_effect=Exception("Test error")):
            message = {
                "type": "private",
                "sender_email": "student@uni.edu",
                "content": "submit test_model",
            }

            # No debería crashear el bot
            bot.handle_message(message)

            # Debería enviar mensaje de error al usuario
            mock_client.send_message.assert_called()
            error_call = mock_client.send_message.call_args[0][0]
            assert "Error interno" in error_call["content"]

    @patch("oraculus_bot.oraculus_bot.zulip.Client")
    def test_bot_restart_data_persistence(self, mock_zulip_client, integration_setup):
        """Test persistencia de datos tras reinicio del bot"""
        setup = integration_setup
        mock_client = Mock()
        mock_zulip_client.return_value = mock_client

        # Crear primer bot y agregar datos
        bot1 = OraculusBot(str(setup["config_path"]))

        user_info = {"user_id": 123, "email": "test@uni.edu", "full_name": "Test User"}
        public_results = {"score": 15, "tp": 2, "tn": 1, "fp": 0, "fn": 1}
        private_results = {"score": 20, "tp": 3, "tn": 2, "fp": 1, "fn": 0}

        submission_id = bot1.save_submission(
            user_info,
            "persistent_model",
            "/path",
            "checksum123",
            public_results,
            private_results,
            5,
            "good",
        )

        # Agregar badge
        bot1.check_and_award_badges(123, 1, 15.0)

        # "Reiniciar" bot (crear nueva instancia)
        bot2 = OraculusBot(str(setup["config_path"]))

        # Verificar que los datos persisten
        submissions = bot2.process_list_submits(123)
        assert "persistent_model" in submissions

        badges = bot2.process_badges(123)
        assert "Primer Envío" in badges

        # Verificar que el ID de submission sigue siendo válido
        select_response = bot2.process_select(123, f"select {submission_id}")
        assert "seleccionado" in select_response.lower()


if __name__ == "__main__":
    # Ejecutar con más verbosidad para debugging
    pytest.main([__file__, "-v", "-s", "--tb=short"])
