"""저장(git 커밋·푸시)이 어떤 상태에서도 되는지 확인.

예약 실행으로 뜬 작업은 브랜치가 아닌 특정 커밋에 붙은 채(detached HEAD)
시작한다. 이 상태에서 인자 없는 pull/push 가 실패해 5시간 30분 동안 등록
내용이 하나도 저장되지 않은 일이 있었다. 그 재발을 막기 위한 테스트.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import storage  # noqa: E402


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


class PersistTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.remote = os.path.join(root, "remote.git")
        self.work = os.path.join(root, "work")
        git("init", "--bare", "-b", "main", self.remote, cwd=root)
        git("clone", self.remote, self.work, cwd=root)
        for key, value in (("user.email", "t@t"), ("user.name", "t")):
            git("config", key, value, cwd=self.work)

        self.db_path = os.path.join(self.work, "users.json")
        self._write(["첫 숙소"])
        git("add", "users.json", cwd=self.work)
        git("commit", "-m", "first", cwd=self.work)
        git("push", "origin", "main", cwd=self.work)

        self._cwd = os.getcwd()
        os.chdir(self.work)
        self._persist, storage.GIT_PERSIST = storage.GIT_PERSIST, True
        self._branch, storage.GIT_BRANCH = storage.GIT_BRANCH, "main"
        self._file, storage.DB_FILE = storage.DB_FILE, "users.json"

    def tearDown(self):
        os.chdir(self._cwd)
        storage.GIT_PERSIST = self._persist
        storage.GIT_BRANCH = self._branch
        storage.DB_FILE = self._file
        self.tmp.cleanup()

    def _write(self, names):
        db = storage.default_db()
        chat = storage.get_chat(db, "1")
        for name in names:
            chat["watches"].append(
                storage.new_watch(name, "2026-10-10", "2026-10-11"))
        storage.save_db(db, self.db_path)

    def _remote_names(self):
        out = git("show", "main:users.json", cwd=self.remote).stdout
        db = json.loads(out)
        return [w["query"] for c in db["chats"].values() for w in c["watches"]]

    def test_persists_on_a_branch(self):
        self._write(["첫 숙소", "둘째 숙소"])
        self.assertTrue(storage.persist())
        self.assertEqual(self._remote_names(), ["첫 숙소", "둘째 숙소"])

    def test_persists_on_detached_head(self):
        """예약 실행이 붙는 상태 — 여기서 저장이 통째로 실패했었다."""
        head = git("rev-parse", "HEAD", cwd=self.work).stdout.strip()
        git("checkout", "--detach", head, cwd=self.work)
        self._write(["삭제 후 남은 숙소"])
        self.assertTrue(storage.persist())
        self.assertEqual(self._remote_names(), ["삭제 후 남은 숙소"])

    def test_deletion_survives(self):
        self._write(["첫 숙소", "둘째 숙소"])
        storage.persist()
        self._write(["첫 숙소"])  # 둘째 숙소 삭제
        self.assertTrue(storage.persist())
        self.assertEqual(self._remote_names(), ["첫 숙소"])

    def test_no_change_is_not_committed(self):
        self.assertFalse(storage.persist())

    def test_disabled_does_nothing(self):
        storage.GIT_PERSIST = False
        self._write(["첫 숙소", "둘째 숙소"])
        self.assertFalse(storage.persist())
        self.assertEqual(self._remote_names(), ["첫 숙소"])


if __name__ == "__main__":
    unittest.main()
