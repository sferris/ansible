# -*- coding: utf-8 -*-

from __future__ import absolute_import, division, print_function

import hashlib
import os
import shutil
import tarfile
import tempfile
import unittest
import zipfile

from plugins.module_utils.package_installer import (
    PackageInstallationError,
    install_package,
)


class PackageInstallerTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="package-installer-test-")
        self.installation = os.path.join(self.root, "installed")
        self.inventory = os.path.join(self.root, "inventory")
        os.mkdir(self.installation)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _tar(self, name="product", member="payload.txt", content=b"payload"):
        source_root = os.path.join(self.root, "tar-source")
        package_root = os.path.join(source_root, name)
        os.makedirs(package_root)
        with open(os.path.join(package_root, member), "wb") as stream:
            stream.write(content)
        archive = os.path.join(self.root, "%s.tar.gz" % name)
        with tarfile.open(archive, "w:gz") as output:
            output.add(package_root, arcname=name)
        return archive

    def _zip(self, name="zip-product"):
        archive = os.path.join(self.root, "%s.zip" % name)
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("%s/payload.txt" % name, b"zip payload")
        return archive

    def _md5(self, path):
        digest = hashlib.md5()
        with open(path, "rb") as stream:
            digest.update(stream.read())
        return digest.hexdigest()

    def test_installs_local_tar_and_creates_md5_inventory_link(self):
        archive = self._tar()

        result = install_package(
            self.installation, archive, inventory_directory=self.inventory
        )

        destination = os.path.join(self.installation, "product")
        self.assertTrue(result["changed"])
        self.assertFalse(result["failed"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["md5sum"], self._md5(archive))
        self.assertEqual(result["installed_directory"], destination)
        self.assertTrue(result["temporary_directory"])
        self.assertFalse(os.path.exists(result["temporary_directory"]))
        self.assertTrue(os.path.isfile(os.path.join(destination, "payload.txt")))
        link = os.path.join(self.inventory, ".%s.md5" % result["md5sum"])
        self.assertEqual(os.path.realpath(link), destination)
        self.assertEqual(os.listdir(self.installation), ["product"])

    def test_installs_zip_from_file_url(self):
        archive = self._zip()

        result = install_package(
            self.installation, "file://" + archive,
            inventory_directory=self.inventory,
        )

        self.assertTrue(result["changed"])
        self.assertTrue(os.path.isfile(os.path.join(
            result["installed_directory"], "payload.txt"
        )))

    def test_supplied_md5_inventory_link_avoids_opening_source(self):
        target = os.path.join(self.installation, "already-there")
        os.mkdir(target)
        os.mkdir(self.inventory)
        checksum = "a" * 32
        os.symlink(target, os.path.join(self.inventory, ".%s.md5" % checksum))

        result = install_package(
            self.installation, os.path.join(self.root, "missing.tar.gz"),
            md5sum=checksum, inventory_directory=self.inventory,
        )

        self.assertFalse(result["changed"])
        self.assertEqual(result["installed_directory"], target)
        self.assertEqual(result["md5sum"], checksum)

    def test_force_bypasses_existing_checksum_inventory_link(self):
        archive = self._tar(content=b"new")
        checksum = self._md5(archive)
        destination = os.path.join(self.installation, "product")
        os.mkdir(destination)
        with open(os.path.join(destination, "old.txt"), "w") as stream:
            stream.write("old")
        os.mkdir(self.inventory)
        os.symlink(destination, os.path.join(self.inventory, ".%s.md5" % checksum))

        result = install_package(
            self.installation, archive, md5sum=checksum, force=True,
            inventory_directory=self.inventory,
        )

        self.assertTrue(result["changed"])
        self.assertTrue(os.path.isfile(os.path.join(destination, "payload.txt")))
        self.assertTrue(os.path.isfile(os.path.join(destination + ".trash", "old.txt")))

    def test_invalid_md5_is_rejected_before_installation(self):
        with self.assertRaises(PackageInstallationError) as context:
            install_package(
                self.installation, "missing.tar.gz", md5sum="not-an-md5",
                inventory_directory=self.inventory,
            )

        self.assertIn("32 hexadecimal", str(context.exception))
        self.assertEqual(os.listdir(self.installation), [])

    def test_checksum_mismatch_raises_with_checksum_and_removes_tempdir(self):
        archive = self._tar()

        with self.assertRaises(PackageInstallationError) as context:
            install_package(
                self.installation, archive, md5sum="0" * 32,
                inventory_directory=self.inventory,
            )

        error = context.exception
        self.assertEqual(error.md5sum, self._md5(archive))
        self.assertIsNotNone(error.temporary_directory)
        self.assertFalse(os.path.exists(error.temporary_directory))
        self.assertIn("checksum mismatch", str(error).lower())

    def test_skip_relocation_preserves_tempdir_and_leaves_installation_empty(self):
        archive = self._tar()

        result = install_package(
            self.installation, archive, skip_relocation=True,
            inventory_directory=self.inventory,
        )

        self.assertTrue(result["changed"])
        self.assertEqual(result["installed_directory"], "")
        self.assertTrue(os.path.isdir(result["temporary_directory"]))
        self.assertTrue(os.path.isfile(os.path.join(
            result["temporary_directory"], "extract", "product", "payload.txt"
        )))
        self.assertEqual(os.listdir(self.installation), [
            os.path.basename(result["temporary_directory"])
        ])

    def test_existing_extracted_destination_is_idempotent(self):
        archive = self._tar()
        destination = os.path.join(self.installation, "product")
        os.mkdir(destination)
        marker = os.path.join(destination, "existing.txt")
        with open(marker, "w") as stream:
            stream.write("keep")

        result = install_package(
            self.installation, archive, inventory_directory=self.inventory
        )

        self.assertFalse(result["changed"])
        self.assertEqual(result["installed_directory"], destination)
        self.assertTrue(os.path.isfile(marker))
        self.assertEqual(os.listdir(self.installation), ["product"])

    def test_force_replaces_destination_and_refreshes_stale_trash(self):
        archive = self._tar(content=b"new")
        destination = os.path.join(self.installation, "product")
        trash = destination + ".trash"
        os.mkdir(destination)
        os.mkdir(trash)
        with open(os.path.join(destination, "old.txt"), "w") as stream:
            stream.write("old")
        with open(os.path.join(trash, "stale.txt"), "w") as stream:
            stream.write("stale")

        result = install_package(
            self.installation, archive, force=True,
            inventory_directory=self.inventory,
        )

        self.assertTrue(result["changed"])
        self.assertTrue(os.path.isfile(os.path.join(destination, "payload.txt")))
        self.assertTrue(os.path.isfile(os.path.join(trash, "old.txt")))
        self.assertFalse(os.path.exists(os.path.join(trash, "stale.txt")))

    def test_rejects_archive_path_traversal_before_extraction(self):
        archive = os.path.join(self.root, "unsafe.zip")
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("../escaped.txt", b"bad")

        with self.assertRaises(PackageInstallationError) as context:
            install_package(
                self.installation, archive, inventory_directory=self.inventory
            )

        self.assertIn("unsafe path", str(context.exception))
        self.assertFalse(os.path.exists(os.path.join(self.root, "escaped.txt")))
        self.assertEqual(os.listdir(self.installation), [])

    def test_rejects_multiple_top_level_directories_and_cleans_up(self):
        archive = os.path.join(self.root, "multiple.zip")
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("one/file", b"one")
            output.writestr("two/file", b"two")

        with self.assertRaises(PackageInstallationError) as context:
            install_package(
                self.installation, archive, inventory_directory=self.inventory
            )

        self.assertIn("exactly one", str(context.exception))
        self.assertFalse(os.path.exists(context.exception.temporary_directory))
        self.assertEqual(os.listdir(self.installation), [])

    def test_rejects_unsupported_archive_with_actionable_error(self):
        source = os.path.join(self.root, "package.bin")
        with open(source, "wb") as stream:
            stream.write(b"not an archive")

        with self.assertRaises(PackageInstallationError) as context:
            install_package(
                self.installation, source, inventory_directory=self.inventory
            )

        self.assertIn("expected .tgz, .tar.gz, or .zip", str(context.exception))
        self.assertFalse(os.path.exists(context.exception.temporary_directory))


if __name__ == "__main__":
    unittest.main()
