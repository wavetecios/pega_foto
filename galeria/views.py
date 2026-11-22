import hmac

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from PIL import Image, UnidentifiedImageError

from .forms import UploadFotoForm
from .models import Foto


@csrf_exempt
@require_POST
def upload_foto(request):
    api_key = request.headers.get("X-API-KEY", "")
    if not hmac.compare_digest(
        api_key.encode("utf-8"),
        settings.TOTEM_API_KEY.encode("utf-8"),
    ):
        return JsonResponse({"erro": "Não autorizado"}, status=401)

    imagem = request.FILES.get("imagem")
    if imagem is None:
        return JsonResponse({"erro": "Arquivo de imagem obrigatório"}, status=400)
    if imagem.size > settings.MAX_UPLOAD_SIZE:
        return JsonResponse({"erro": "Imagem excede o limite de 10 MB"}, status=400)

    try:
        imagem.seek(0)
        with Image.open(imagem) as arquivo_imagem:
            arquivo_imagem.verify()
        imagem.seek(0)
    except (
        Image.DecompressionBombError,
        OSError,
        SyntaxError,
        UnidentifiedImageError,
        ValueError,
    ):
        return JsonResponse({"erro": "Arquivo de imagem inválido"}, status=400)

    form = UploadFotoForm(request.POST, request.FILES)
    if not form.is_valid():
        return JsonResponse({"erros": form.errors.get_json_data()}, status=400)

    foto = Foto.objects.create(
        imagem=form.cleaned_data["imagem"],
        codigo_evento=form.cleaned_data["codigo_evento"],
    )
    return JsonResponse(
        {
            "id": foto.pk,
            "codigo_evento": foto.codigo_evento,
            "imagem": request.build_absolute_uri(foto.imagem.url),
        },
        status=201,
    )


def index(request):
    codigo_evento = request.GET.get("evento", "").strip()
    fotos = Foto.objects.all()
    if codigo_evento:
        fotos = fotos.filter(codigo_evento=codigo_evento)
    fotos = fotos.order_by("-criado_em", "-id")
    return render(
        request,
        "galeria/index.html",
        {
            "fotos": fotos,
            "codigo_evento": codigo_evento or "Todos os eventos",
        },
    )
