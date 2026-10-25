"""The shared temp-folder cleanup retries a busy delete, and stays loud on a real failure."""
import errno
import tempfile
import unittest

import support


def _flaky(failures, code=errno.ENOTEMPTY):
    calls = []

    def rmtree(path):
        calls.append(path)
        if len(calls) <= failures:
            raise OSError(code, "Directory not empty", path)

    return rmtree, calls


class RemoveTreeTest(unittest.TestCase):
    def test_S_078_1_retries_on_directory_not_empty(self):
        rmtree, calls = _flaky(2)
        support.remove_tree("/x", rmtree=rmtree, wait=0)
        self.assertEqual(len(calls), 3)

    def test_S_078_1_retries_on_busy(self):
        rmtree, calls = _flaky(1, errno.EBUSY)
        support.remove_tree("/x", rmtree=rmtree, wait=0)
        self.assertEqual(len(calls), 2)

    def test_S_078_2_raises_after_the_retries(self):
        rmtree, calls = _flaky(100)
        with self.assertRaises(OSError):
            support.remove_tree("/x", rmtree=rmtree, wait=0)
        self.assertEqual(len(calls), support.REMOVE_ATTEMPTS)

    def test_S_078_2_other_errors_raise_at_once(self):
        rmtree, calls = _flaky(100, errno.EACCES)
        with self.assertRaises(OSError):
            support.remove_tree("/x", rmtree=rmtree, wait=0)
        self.assertEqual(len(calls), 1)

    def test_S_078_1_remove_tmp_removes_the_folder(self):
        tmp = tempfile.TemporaryDirectory()
        support.write(support.pathlib.Path(tmp.name) / "a" / "b.txt", "x")
        support.remove_tmp(tmp)
        self.assertFalse(support.pathlib.Path(tmp.name).exists())


class CleanupPatchTest(unittest.TestCase):
    def test_S_078_1_tmp_cleanup_uses_the_retrying_delete(self):
        self.assertIs(tempfile.TemporaryDirectory.cleanup, support.remove_tmp)
        tmp = tempfile.TemporaryDirectory()
        tmp.cleanup()
        self.assertFalse(support.pathlib.Path(tmp.name).exists())


if __name__ == "__main__":
    unittest.main()
