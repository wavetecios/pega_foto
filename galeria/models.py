from django.db import models


class Foto(models.Model):
    imagem = models.ImageField(upload_to="fotos_evento/")
    criado_em = models.DateTimeField(auto_now_add=True)
    codigo_evento = models.CharField(max_length=50, default="evento_padrao")

    class Meta:
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.codigo_evento} - {self.criado_em:%Y-%m-%d %H:%M}"
