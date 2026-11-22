from io import BytesIO
from tempfile import TemporaryDirectory

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from .models import Foto


@override_settings(TOTEM_API_KEY="test-totem-api-key")
class UploadFotoTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media_dir = TemporaryDirectory()
        cls.media_settings = override_settings(MEDIA_ROOT=cls.media_dir.name)
        cls.media_settings.enable()

    @classmethod
    def tearDownClass(cls):
        cls.media_settings.disable()
        cls.media_dir.cleanup()
        super().tearDownClass()

    def make_image(self):
        content = BytesIO()
        Image.new("RGB", (2, 2), color="blue").save(content, format="PNG")
        return SimpleUploadedFile(
            "foto.png",
            content.getvalue(),
            content_type="image/png",
        )

    def test_upload_rejects_missing_api_key(self):
        response = self.client.post(
            "/api/upload/",
            {"imagem": self.make_image()},
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"erro": "Não autorizado"})
        self.assertEqual(Foto.objects.count(), 0)

    def test_upload_rejects_incorrect_api_key(self):
        response = self.client.post(
            "/api/upload/",
            {
                "imagem": self.make_image(),
                "codigo_evento": "festa-2026",
            },
            HTTP_X_API_KEY="wrong-key",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"erro": "Não autorizado"})
        self.assertEqual(Foto.objects.count(), 0)

    def test_upload_rejects_non_ascii_api_key(self):
        response = self.client.post(
            "/api/upload/",
            {"imagem": self.make_image()},
            HTTP_X_API_KEY="chave-inválida",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(Foto.objects.count(), 0)

    def test_upload_rejects_missing_image(self):
        response = self.client.post(
            "/api/upload/",
            {"codigo_evento": "festa-2026"},
            HTTP_X_API_KEY="test-totem-api-key",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Foto.objects.count(), 0)

    def test_upload_saves_photo_with_correct_api_key(self):
        response = self.client.post(
            "/api/upload/",
            {
                "imagem": self.make_image(),
                "codigo_evento": "festa-2026",
            },
            HTTP_X_API_KEY="test-totem-api-key",
        )

        self.assertEqual(response.status_code, 201)
        foto = Foto.objects.get()
        self.assertEqual(foto.codigo_evento, "festa-2026")
        self.assertTrue(foto.imagem.name.startswith("fotos_evento/"))
        self.assertEqual(response.json()["codigo_evento"], "festa-2026")

        gallery_response = self.client.get("/")
        self.assertContains(gallery_response, "/media/fotos_evento/foto.png")
        self.assertContains(gallery_response, "festa-2026")
        self.assertContains(gallery_response, "Baixar Foto em Alta Resolução")
        self.assertNotContains(gallery_response, "Ainda não há fotos")

        event_gallery_response = self.client.get("/?evento=festa-2026")
        self.assertContains(event_gallery_response, "/media/fotos_evento/foto.png")

    def test_upload_rejects_non_image(self):
        response = self.client.post(
            "/api/upload/",
            {
                "imagem": SimpleUploadedFile(
                    "arquivo.txt",
                    b"nao e uma imagem",
                    content_type="text/plain",
                )
            },
            HTTP_X_API_KEY="test-totem-api-key",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Foto.objects.count(), 0)

    @override_settings(MAX_UPLOAD_SIZE=8)
    def test_upload_rejects_oversized_file(self):
        response = self.client.post(
            "/api/upload/",
            {"imagem": self.make_image()},
            HTTP_X_API_KEY="test-totem-api-key",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Foto.objects.count(), 0)
