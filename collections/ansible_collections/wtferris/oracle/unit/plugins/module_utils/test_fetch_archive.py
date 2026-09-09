# -*- coding: utf-8 -*-

from __future__ import absolute_import, division, print_function

import hashlib
import os
import shutil
import tarfile
import tempfile
import unittest
import zipfile

from plugins.module_utils.fetch_archive import FetchArchiveError, fetch_archive


class FetchArchiveTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="fetch-archive-test-")
        self.temporary_root = os.path.join(self.root, "temporary")
        os.mkdir(self.temporary_root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _tar(self, names=("product",)):
        source_root = os.path.join(self.root, "tar-source")
        os.mkdir(source_root)
        archive = os.path.join(self.root, "product.tar.gz")
        for name in names:
            directory = os.path.join(source_root, name)
            os.mkdir(directory)
            with open(os.path.join(directory, "payload.txt"), "wb") as stream:
                stream.write(name.encode("ascii"))
        with tarfile.open(archive, "w:gz") as output:
            for name in names:
                output.add(os.path.join(source_root, name), arcname=name)
        return archive

    def _zip(self):
        archive = os.path.join(self.root, "product.zip")
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("zip-product/payload.txt", b"zip payload")
        return archive

    def _md5(self, path):
        digest = hashlib.md5()
        with open(path, "rb") as stream:
            digest.update(stream.read())
        return digest.hexdigest()

    def test_unpacks_tar_and_preserves_temporary_directory(self):
        archive = self._tar()

        result = fetch_archive(archive, temporary_directory_root=self.temporary_root)
        self.addCleanup(shutil.rmtree, result["temporary_directory"], True)

        self.assertTrue(result["changed"])
        self.assertFalse(result["failed"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["md5sum"], self._md5(archive))
        self.assertEqual(result["contents"], ["product"])
        self.assertEqual(
            result["unpack_directory"],
            os.path.join(result["temporary_directory"], "extract"),
        )
        self.assertTrue(os.path.isfile(os.path.join(
            result["unpack_directory"], "product", "payload.txt"
        )))
        self.assertTrue(os.path.isfile(os.path.join(
            result["temporary_directory"], "archive.tar.gz"
        )))

    def test_returns_multiple_top_level_entries(self):
        archive = self._tar(names=("one", "two"))

        result = fetch_archive(archive, temporary_directory_root=self.temporary_root)
        self.addCleanup(shutil.rmtree, result["temporary_directory"], True)

        self.assertEqual(result["contents"], ["one", "two"])

    def test_unpacks_zip_from_file_url(self):
        archive = self._zip()

        result = fetch_archive(
            "file://" + archive,
            temporary_directory_root=self.temporary_root,
        )
        self.addCleanup(shutil.rmtree, result["temporary_directory"], True)

        self.assertEqual(result["contents"], ["zip-product"])
        self.assertTrue(os.path.isfile(os.path.join(
            result["unpack_directory"], "zip-product", "payload.txt"
        )))

    def test_accepts_matching_md5(self):
        archive = self._tar()

        result = fetch_archive(
            archive,
            temporary_directory_root=self.temporary_root,
            md5sum=self._md5(archive).upper(),
        )
        self.addCleanup(shutil.rmtree, result["temporary_directory"], True)

        self.assertEqual(result["md5sum"], self._md5(archive))

    def test_checksum_mismatch_reports_checksum_and_cleans_up(self):
        archive = self._tar()

        with self.assertRaises(FetchArchiveError) as context:
            fetch_archive(
                archive,
                temporary_directory_root=self.temporary_root,
                md5sum="0" * 32,
            )

        error = context.exception
        self.assertEqual(error.md5sum, self._md5(archive))
        temporary_directory = error.temporary_directory or ""
        self.assertTrue(temporary_directory)
        self.assertFalse(os.path.exists(temporary_directory))
        self.assertIn("checksum mismatch", str(error).lower())

    def test_invalid_md5_is_rejected_before_creating_temporary_directory(self):
        with self.assertRaises(FetchArchiveError) as context:
            fetch_archive(
                "missing.tar.gz",
                temporary_directory_root=self.temporary_root,
                md5sum="invalid",
            )

        self.assertIn("32 hexadecimal", str(context.exception))
        self.assertEqual(os.listdir(self.temporary_root), [])

    def test_rejects_path_traversal_and_cleans_up(self):
        archive = os.path.join(self.root, "unsafe.zip")
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("../escaped.txt", b"bad")

        with self.assertRaises(FetchArchiveError) as context:
            fetch_archive(archive, temporary_directory_root=self.temporary_root)

        self.assertIn("unsafe path", str(context.exception))
        temporary_directory = context.exception.temporary_directory or ""
        self.assertTrue(temporary_directory)
        self.assertFalse(os.path.exists(temporary_directory))
        self.assertFalse(os.path.exists(os.path.join(self.root, "escaped.txt")))

    def test_rejects_unsupported_archive_and_cleans_up(self):
        source = os.path.join(self.root, "package.bin")
        with open(source, "wb") as stream:
            stream.write(b"not an archive")

        with self.assertRaises(FetchArchiveError) as context:
            fetch_archive(source, temporary_directory_root=self.temporary_root)

        self.assertIn("expected .tgz, .tar.gz, or .zip", str(context.exception))
        temporary_directory = context.exception.temporary_directory or ""
        self.assertTrue(temporary_directory)
        self.assertFalse(os.path.exists(temporary_directory))


if __name__ == "__main__":
    unittest.main()
