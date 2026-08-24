import os
import shutil
import unittest

from gerar_proposta import _resolve_img_path, BASE_DIR
from models import Equipment


class EquipmentIllustrationPathTest(unittest.TestCase):
    def test_normalizes_prefix_and_separators_on_set(self):
        eq = Equipment()
        eq.illustration_path = "static\\images\\folder/equip.png"

        self.assertEqual(eq.illustration_path, "folder/equip.png")
        self.assertEqual(eq._illustration_path, "folder/equip.png")

    def test_normalizes_existing_database_value_on_get(self):
        eq = Equipment()
        eq._illustration_path = "static/images/eq7.png"

        self.assertEqual(eq.illustration_path, "eq7.png")


class ResolveImgPathTest(unittest.TestCase):
    def setUp(self):
        self.static_dir = os.path.join(BASE_DIR, "static")
        self.images_dir = os.path.join(self.static_dir, "images")

        self.created_static = not os.path.isdir(self.static_dir)
        self.created_images = not os.path.isdir(self.images_dir)

        if self.created_static:
            os.makedirs(self.static_dir, exist_ok=True)
        if self.created_images:
            os.makedirs(self.images_dir, exist_ok=True)

        self.sample_file = os.path.join(self.images_dir, "sample.png")
        with open(self.sample_file, "wb") as fp:
            fp.write(b"test")

    def tearDown(self):
        if os.path.exists(self.sample_file):
            os.remove(self.sample_file)
        if self.created_images and os.path.isdir(self.images_dir):
            shutil.rmtree(self.images_dir)
        if self.created_static and os.path.isdir(self.static_dir):
            shutil.rmtree(self.static_dir)

    def test_resolve_accepts_windows_style_static_prefix(self):
        resolved = _resolve_img_path("static\\images\\sample.png")

        self.assertEqual(os.path.normpath(resolved), os.path.normpath(self.sample_file))


if __name__ == "__main__":
    unittest.main()
