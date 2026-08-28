import asyncio
import threading
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.services import file_parser, llm_client, task_store
from app.services.regex_filter import is_candidate_m1, is_candidate_m10
from app.services.m10_rules import extract_judgment_date, extract_m10_article_refs, resolve_m10_law_context
from app.services.llm_caller import LLMCaller
from app.services.section_assembler import check_m10_skip_condition


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


class M10LawVersionRegressionTests(unittest.TestCase):
    @staticmethod
    def _judgment(result: str, date_text: str | None = "2024年5月1日") -> str:
        suffix = ""
        if date_text:
            suffix = f"\n审判员 张三\n{date_text}"
        return f"人民法院民事判决书\n判决如下：{result}{suffix}"

    def test_judgment_date_is_read_from_signature(self):
        text = self._judgment("被告应于判决生效后十日内支付原告货款10000元。", "二〇二四年五月一日")
        self.assertEqual("2024-05-01", extract_judgment_date(text).isoformat())

    def test_2017_version_uses_article_253(self):
        text = self._judgment(
            "被告应于判决生效后十日内支付原告货款10000元，依据《民事诉讼法》第二百五十三条加倍支付迟延履行期间的债务利息。",
            "2021年12月31日",
        )
        result = check_m10_skip_condition(text)
        self.assertEqual("无问题", result["issue"])
        self.assertEqual(253, resolve_m10_law_context(text).article)

    def test_2021_version_uses_article_260(self):
        text = self._judgment(
            "被告应于判决生效后十日内支付原告货款10000元，依据《民事诉讼法》第260条加倍支付迟延履行期间的债务利息。",
            "2022年6月1日",
        )
        result = check_m10_skip_condition(text)
        self.assertEqual("无问题", result["issue"])
        self.assertEqual(260, resolve_m10_law_context(text).article)

    def test_2023_version_uses_article_264(self):
        text = self._judgment(
            "被告应于判决生效后十日内支付原告货款10000元，依据《民事诉讼法》第264条加倍支付迟延履行期间的债务利息。",
            "2024年5月1日",
        )
        result = check_m10_skip_condition(text)
        self.assertEqual("无问题", result["issue"])
        self.assertEqual(264, resolve_m10_law_context(text).article)

    def test_known_date_with_wrong_article_is_a_problem(self):
        text = self._judgment(
            "被告应于判决生效后十日内支付原告货款10000元，依据《民事诉讼法》第253条加倍支付迟延履行期间的债务利息。",
            "2024年5月1日",
        )
        result = check_m10_skip_condition(text)
        self.assertEqual("存在问题", result["issue"])
        self.assertEqual("中", result["risk"])

    def test_unknown_date_always_requires_manual_review(self):
        for clause in (
            "依据《民事诉讼法》第253条加倍支付迟延履行期间的债务利息。",
            "依据《民事诉讼法》第260条加倍支付迟延履行期间的债务利息。",
            "依据《民事诉讼法》第264条加倍支付迟延履行期间的债务利息。",
            "加倍支付迟延履行期间的债务利息。",
        ):
            with self.subTest(clause=clause):
                result = check_m10_skip_condition(self._judgment(
                    f"被告应于判决生效后十日内支付原告货款10000元，{clause}",
                    None,
                ))
                self.assertEqual("待人工复核", result["issue"])
                self.assertEqual("人工复核", result["risk"])
                self.assertEqual("核对裁判日期及适用法律版本", result["suggestion"])

    def test_unknown_date_does_not_send_m10_to_llm(self):
        text = self._judgment(
            "被告应于判决生效后十日内支付原告货款10000元，并加倍支付迟延履行期间的债务利息。",
            None,
        )
        with patch("app.services.llm_caller.call_llm_with_retry", side_effect=AssertionError("LLM should not run")):
            _, status, data = asyncio.run(LLMCaller("m10").call(text))
        self.assertEqual("skipped", status)
        self.assertEqual("待人工复核", data["issue"])

    def test_multiple_signature_dates_require_manual_review(self):
        text = (
            "人民法院民事判决书\n判决如下：被告支付原告货款10000元。\n"
            "审判员 张三\n2024年5月1日\n书记员 李四\n2024年5月2日"
        )
        self.assertIsNone(extract_judgment_date(text))
        self.assertEqual("待人工复核", check_m10_skip_condition(text)["issue"])

    def test_article_506_alone_is_not_compliant(self):
        text = self._judgment(
            "被告应于判决生效后十日内支付原告货款10000元，按照《民诉法解释》第506条确定起算时间。",
        )
        result = check_m10_skip_condition(text)
        self.assertEqual("存在问题", result["issue"])

    def test_same_number_from_another_law_is_not_m10_article(self):
        self.assertEqual([], extract_m10_article_refs("《民法典》第264条规定其他事项。"))

    def test_ordinary_interest_lpr_and_delayed_payment_penalty_continue_to_llm(self):
        cases = (
            "被告应于判决生效后十日内支付原告货款10000元，逾期按年利率4%支付利息。",
            "被告应于判决生效后十日内支付原告货款10000元，逾期按LPR支付利息。",
            "被告应于判决生效后十日内支付原告货款10000元，逾期支付迟延履行金。",
            "被告应于判决生效后三十日内交付房屋，逾期支付迟延履行金500元。",
        )
        for clause in cases:
            with self.subTest(clause=clause):
                self.assertIsNone(check_m10_skip_condition(self._judgment(clause)))

    def test_behavior_only_does_not_trigger_m10_candidate(self):
        text = self._judgment("被告应于判决生效后三十日内将涉案房屋腾空并返还原告。")
        self.assertFalse(is_candidate_m10(text))

    def test_behavior_and_money_obligations_are_kept_as_m10_candidate(self):
        text = self._judgment(
            "一、被告应于判决生效后三十日内交付房屋；二、被告应于判决生效后十日内支付原告货款10000元。"
        )
        self.assertTrue(is_candidate_m10(text))

    def test_behavior_clause_interest_does_not_hide_money_clause(self):
        text = self._judgment(
            "一、被告应于判决生效后三十日内交付房屋，并加倍支付迟延履行期间的债务利息；"
            "二、被告应于判决生效后十日内支付原告货款10000元。"
        )
        self.assertIsNone(check_m10_skip_condition(text))

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


class LightweightCoreRegressionTests(unittest.TestCase):
    def test_api_keeps_batch_history_and_debug_stream_only(self):
        from app.main import app

        paths = {route.path for route in app.routes}
        self.assertIn("/review/batch", paths)
        self.assertIn("/review/stream/{task_id}", paths)
        self.assertIn("/review/history", paths)
        self.assertNotIn("/review/file", paths)
        self.assertNotIn("/", paths)

    def test_doc_files_still_dispatch_to_legacy_parser(self):
        parsed_text = "判决书内容" * 20
        with patch.object(file_parser, "read_doc", return_value=parsed_text) as read_doc:
            result = file_parser.parse_file(Path("保留支持.doc"))

        self.assertEqual(parsed_text, result)
        read_doc.assert_called_once_with(Path("保留支持.doc"))

    def test_doc_parser_keeps_antiword_as_primary_path(self):
        parsed_text = "人民法院民事判决书" * 10
        completed = SimpleNamespace(returncode=0, stdout=parsed_text.encode("utf-8"))

        with patch.object(file_parser.subprocess, "run", return_value=completed) as run:
            result = file_parser.read_doc(Path("传统格式.doc"))

        self.assertEqual(parsed_text, result)
        self.assertEqual("antiword", run.call_args.args[0][0])


if __name__ == "__main__":
    unittest.main()
