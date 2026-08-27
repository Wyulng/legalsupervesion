import asyncio
import threading
import unittest
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.services import llm_client, task_store
from app.services.regex_filter import is_candidate_m1, is_candidate_m10


class RegexFilterRegressionTests(unittest.TestCase):
    def test_m1_keeps_valid_notice_when_unrelated_negative_notice_exists(self):
        text = (
            "原告提交了公司注销公告。"
            "本院依法公告送达起诉状副本及开庭传票。"
            "裁判结果未提及公告费。"
        )
        self.assertTrue(is_candidate_m1(text))

    def test_m1_keeps_earlier_service_when_judgment_is_later_announced(self):
        text = (
            "本院依法公告送达起诉状副本及开庭传票。"
            "审理终结后公告送达判决书。"
        )
        self.assertTrue(is_candidate_m1(text))

    def test_m1_excludes_document_with_only_non_court_notice(self):
        self.assertFalse(is_candidate_m1("原告提交公司注销公告，现已完成清算。"))

    def test_m10_keeps_other_money_obligation_beside_emotional_damages(self):
        text = (
            "判决如下：一、被告于判决生效后十日内赔偿原告经济损失10000元；"
            "二、赔偿精神抚慰金1000元。"
        )
        self.assertTrue(is_candidate_m10(text))

    def test_m10_excludes_emotional_damages_only(self):
        self.assertFalse(is_candidate_m10("判决如下：被告赔偿原告精神抚慰金1000元。"))

    def test_m10_keeps_delayed_obligation_beside_immediate_payment(self):
        text = (
            "判决如下：一、被告当庭给付原告500元；"
            "二、被告于判决生效后十日内偿还借款10000元。"
        )
        self.assertTrue(is_candidate_m10(text))


class LLMClientRegressionTests(unittest.TestCase):
    def test_non_rate_limit_value_error_uses_all_attempts(self):
        calls = []

        def fail_with_invalid_json(*args, **kwargs):
            calls.append(1)
            raise ValueError("JSON parse failed")

        async def no_sleep(_delay):
            return None

        with (
            patch.object(llm_client, "_do_call_sync", fail_with_invalid_json),
            patch.object(llm_client.asyncio, "sleep", no_sleep),
        ):
            result = asyncio.run(
                llm_client.call_llm_with_retry(
                    "prompt",
                    max_retries=2,
                    function_schema=llm_client.FUNCTION_SCHEMA_M1,
                )
            )

        self.assertEqual(3, len(calls))
        self.assertTrue(result["_parse_fallback"])

    def test_timed_out_slot_acquisition_does_not_consume_future_release(self):
        semaphore = threading.BoundedSemaphore(1)
        semaphore.acquire()

        with patch.object(llm_client, "_llm_semaphore", semaphore):
            self.assertFalse(asyncio.run(llm_client._acquire_llm_slot(timeout=0.01)))
            semaphore.release()
            self.assertTrue(asyncio.run(llm_client._acquire_llm_slot(timeout=0.01)))
            llm_client._release_llm_slot()


class TaskStoreRegressionTests(unittest.TestCase):
    def test_completed_snapshot_always_contains_unique_csv_filename(self):
        task = task_store.create_task(total=0)
        snapshots = []

        def capture_save(current_task):
            snapshots.append(asdict(current_task))

        with TemporaryDirectory() as temp_dir:
            with (
                patch("app.logging_config.setup_logging"),
                patch("app.main.process_batch", return_value=[]),
                patch("app.main.save_results_to_csv"),
                patch.object(task_store, "RESULT_DIR", Path(temp_dir)),
                patch.object(task_store, "_save", side_effect=capture_save),
                patch.object(task_store, "_migrate_to_history"),
            ):
                task_store.process_task_async(task.task_id, [])

        completed = [item for item in snapshots if item["status"] == "completed"]
        self.assertEqual(1, len(completed))
        self.assertEqual(f"batch_{task.task_id}.csv", completed[0]["csv_filename"])
        self.assertEqual(100, completed[0]["progress"])

        with task_store._tasks_lock:
            task_store._tasks.pop(task.task_id, None)


if __name__ == "__main__":
    unittest.main()
