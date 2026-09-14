"""비공개 Gist 저장 방식 확인.

공개 저장소에 쓰는 사람의 채팅 ID·감시 목록이 남지 않도록,
등록 내용을 Gist 에 두는 경로를 검증한다.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

import storage  # noqa: E402


class GistStorageTest(unittest.TestCase):
    def setUp(self):
        self._saved = (storage.GIST_ID, storage.GIST_TOKEN, storage.gist_read,
                       storage.gist_write, dict(storage._last_saved))
        storage.GIST_ID, storage.GIST_TOKEN = "abc123", "token"
        storage._last_saved.clear()
        self.written = []
        storage.gist_write = lambda content: self.written.append(content) or True

    def tearDown(self):
        (storage.GIST_ID, storage.GIST_TOKEN, storage.gist_read,
         storage.gist_write, saved) = self._saved
        storage._last_saved.clear()
        storage._last_saved.update(saved)

    def _db_with(self, name):
        db = storage.default_db()
        storage.get_chat(db, "1")["watches"].append(
            storage.new_watch(name, "2026-10-10", "2026-10-11"))
        return db

    def test_enabled_only_with_both_settings(self):
        self.assertTrue(storage.gist_enabled())
        storage.GIST_TOKEN = ""
        self.assertFalse(storage.gist_enabled())

    def test_loads_from_gist(self):
        storage.gist_read = lambda: json.dumps(self._db_with("비토애 산청"))
        db = storage.load_db()
        self.assertEqual(db["chats"]["1"]["watches"][0]["query"], "비토애 산청")

    def test_read_failure_stops_instead_of_starting_empty(self):
        """여기서 빈 상태로 시작하면 다음 저장 때 전부 지워진다."""
        def boom():
            raise requests.RequestException("네트워크 오류")

        storage.gist_read = boom
        with self.assertRaises(storage.StorageError):
            storage.load_db()

    def test_empty_gist_is_seeded_from_file(self):
        import tempfile

        storage.gist_read = lambda: ""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "users.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._db_with("소노벨 변산"), f)
            db = storage.load_db(path)
        self.assertEqual(db["chats"]["1"]["watches"][0]["query"], "소노벨 변산")

    def test_empty_gist_and_no_file_starts_fresh(self):
        storage.gist_read = lambda: ""
        self.assertEqual(storage.load_db("없는파일.json")["chats"], {})

    def test_saves_to_gist(self):
        self.assertTrue(storage.save_db(self._db_with("비토애 산청")))
        self.assertIn("비토애 산청", self.written[0])

    def test_same_content_is_not_written_twice(self):
        db = self._db_with("비토애 산청")
        storage.save_db(db)
        storage.save_db(db)
        self.assertEqual(len(self.written), 1)

    def test_save_failure_is_reported(self):
        def boom(content):
            raise requests.RequestException("거절됨")

        storage.gist_write = boom
        self.assertFalse(storage.save_db(self._db_with("비토애 산청")))

    def test_repository_commit_is_skipped(self):
        """Gist 를 쓰면 공개 저장소에는 아무것도 커밋하지 않는다."""
        self.assertFalse(storage.persist())


if __name__ == "__main__":
    unittest.main()
