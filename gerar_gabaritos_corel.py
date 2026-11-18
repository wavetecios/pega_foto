import ast
import json
import os
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


RAIZ = Path(__file__).resolve().parent
PASTA_MOLDURAS = RAIZ / "molduras"
PASTA_SAIDA = RAIZ / "gabaritos_corel"
DPI = 300

VERMELHO = (235, 45, 55, 255)
AZUL_AREA = (65, 155, 255, 58)
AZUL_GUIA = (25, 85, 145, 210)
VERDE_AREA = (95, 190, 115, 48)
FUNDO_TEXTO = (255, 255, 255, 220)
COR_TEXTO = (20, 40, 55, 255)


def ler_configuracao():
  caminho = RAIZ / "config.json"
  with caminho.open("r", encoding="utf-8") as arquivo:
    config = json.load(arquivo)
  if not isinstance(config, dict):
    raise ValueError("config.json precisa conter um objeto JSON.")
  return config


def carregar_moldura(config, chave):
  nome = config.get(chave)
  if not isinstance(nome, str) or not nome.strip():
    raise ValueError(f"config.json não contém uma moldura válida em {chave}.")

  relativa = Path(nome.strip())
  if relativa.parts and relativa.parts[0].lower() == "molduras":
    relativa = Path(*relativa.parts[1:])
  caminho = (PASTA_MOLDURAS / relativa).resolve()
  try:
    caminho.relative_to(PASTA_MOLDURAS.resolve())
  except ValueError as erro:
    raise ValueError(f"Caminho de moldura inválido em {chave}: {nome}") from erro
  if caminho.suffix.lower() != ".png" or not caminho.is_file():
    raise FileNotFoundError(f"Moldura PNG não encontrada: {caminho}")

  with Image.open(caminho) as arquivo:
    return caminho, arquivo.size


def ler_geometria_tira():
  caminho = RAIZ / "app.py"
  linhas = caminho.read_text(encoding="utf-8").splitlines()
  arvore = ast.parse("\n".join(linhas), filename=str(caminho))
  metodo = next(
      (
          no
          for classe in arvore.body
          if isinstance(classe, ast.ClassDef)
          for no in classe.body
          if isinstance(no, ast.FunctionDef)
          and no.name == "montar_tira_3_fotos"
      ),
      None,
  )
  if metodo is None:
    raise ValueError("Não foi possível encontrar montar_tira_3_fotos em app.py.")
  fonte_metodo = "\n".join(linhas[metodo.lineno - 1:metodo.end_lineno])

  def extrair_um(padrao, descricao):
    resultado = re.search(padrao, fonte_metodo)
    if resultado is None:
      raise ValueError(
          f"Não foi possível identificar {descricao} em montar_tira_3_fotos."
      )
    return int(resultado.group(1))

  base_largura = extrair_um(
      r"escala_x\s*=\s*largura_final\s*/\s*(\d+)", "a largura-base"
  )
  base_altura = extrair_um(
      r"escala_y\s*=\s*altura_final\s*/\s*(\d+)", "a altura-base"
  )
  tamanho_base = re.search(
      r"largura_final,\s*altura_final\s*=\s*moldura_atual_pil\.size",
      fonte_metodo,
  )
  if tamanho_base is None:
    raise ValueError("Não foi possível identificar as dimensões da moldura.")

  atribuicao_janelas = next(
      (
          no
          for no in ast.walk(metodo)
          if isinstance(no, ast.Assign)
          and any(
              isinstance(alvo, ast.Name) and alvo.id == "janelas"
              for alvo in no.targets
          )
      ),
      None,
  )
  if atribuicao_janelas is None:
    raise ValueError("Não foi possível identificar as janelas da tira.")
  janelas = ast.literal_eval(atribuicao_janelas.value)
  if (
      len(janelas) != 3
      or any(
          len(janela) != 4
          or any(type(coordenada) is not int for coordenada in janela)
          or janela[0] < 0
          or janela[1] < 0
          or janela[2] <= janela[0]
          or janela[3] <= janela[1]
          or janela[2] > base_largura
          or janela[3] > base_altura
          for janela in janelas
      )
  ):
    raise ValueError("app.py deve definir exatamente 3 janelas válidas.")

  return {
      "base_largura": base_largura,
      "base_altura": base_altura,
      "janelas": janelas,
  }


def mm(px):
  return px * 25.4 / DPI


def texto_medida(largura, altura):
  return (
      f"{largura} x {altura} px"
      f"\n{mm(largura):.1f} x {mm(altura):.1f} mm @ {DPI} DPI"
  )


def obter_fonte(tamanho):
  tamanho = max(10, int(tamanho))
  candidatos = (
      Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "arial.ttf",
      Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
  )
  for caminho in candidatos:
    if caminho.is_file():
      return ImageFont.truetype(str(caminho), tamanho)
  try:
    return ImageFont.truetype("arial.ttf", tamanho)
  except OSError:
    return ImageFont.load_default()


def desenhar_tracejado(draw, caixa, cor, espessura):
  esquerda, topo, direita, base = caixa
  passo = max(12, espessura * 5)
  tracado = max(6, espessura * 3)

  def linha_horizontal(x1, x2, y):
    x = x1
    while x <= x2:
      fim = min(x + tracado, x2)
      draw.line((x, y, fim, y), fill=cor, width=espessura)
      x = fim + passo

  def linha_vertical(y1, y2, x):
    y = y1
    while y <= y2:
      fim = min(y + tracado, y2)
      draw.line((x, y, x, fim), fill=cor, width=espessura)
      y = fim + passo

  linha_horizontal(esquerda, direita, topo)
  linha_horizontal(esquerda, direita, base)
  linha_vertical(topo, base, esquerda)
  linha_vertical(topo, base, direita)


def desenhar_rotulo(draw, centro, texto, fonte, limite=None):
  espacamento = max(3, fonte.size // 6)
  caixa_texto = draw.multiline_textbbox(
      (0, 0), texto, font=fonte, spacing=espacamento, align="center"
  )
  largura_texto = caixa_texto[2] - caixa_texto[0]
  altura_texto = caixa_texto[3] - caixa_texto[1]
  padding = max(8, fonte.size // 3)
  esquerda = round(centro[0] - largura_texto / 2)
  topo = round(centro[1] - altura_texto / 2)
  if limite is not None:
    esquerda = max(limite[0], min(esquerda, limite[2] - largura_texto))
    topo = max(limite[1], min(topo, limite[3] - altura_texto))

  fundo = (
      esquerda - padding,
      topo - padding,
      esquerda + largura_texto + padding,
      topo + altura_texto + padding,
  )
  draw.rounded_rectangle(
      fundo, radius=max(4, padding // 2), fill=FUNDO_TEXTO
  )
  draw.multiline_text(
      (esquerda - caixa_texto[0], topo - caixa_texto[1]),
      texto,
      font=fonte,
      fill=COR_TEXTO,
      spacing=espacamento,
      align="center",
  )


def gerar_gabarito_foto(caminho, dimensoes):
  largura, altura = dimensoes
  imagem = Image.new("RGBA", dimensoes, (0, 0, 0, 0))
  draw = ImageDraw.Draw(imagem, "RGBA")
  espessura = max(3, round(min(dimensoes) / 900))
  margem = max(1, espessura)

  draw.rectangle(
      (0, 0, largura - 1, altura - 1),
      fill=AZUL_AREA,
  )
  desenhar_tracejado(
      draw,
      (margem, margem, largura - 1 - margem, altura - 1 - margem),
      VERMELHO,
      espessura,
  )

  centro_x = largura // 2
  centro_y = altura // 2
  draw.line(
      (centro_x, margem * 4, centro_x, altura - margem * 4),
      fill=AZUL_GUIA,
      width=max(2, espessura // 2),
  )
  draw.line(
      (margem * 4, centro_y, largura - margem * 4, centro_y),
      fill=AZUL_GUIA,
      width=max(2, espessura // 2),
  )
  raio = max(10, round(min(dimensoes) / 100))
  draw.ellipse(
      (centro_x - raio, centro_y - raio, centro_x + raio, centro_y + raio),
      outline=AZUL_GUIA,
      width=max(2, espessura // 2),
  )

  fonte = obter_fonte(min(160, max(24, round(min(dimensoes) * 0.035))))
  rotulo = (
      f"1 FOTO — ÁREA VISÍVEL DA CÂMERA"
      f"\n{texto_medida(largura, altura)}"
      f"\nEIXO X / EIXO Y"
  )
  desenhar_rotulo(
      draw,
      (largura // 2, max(altura * 0.09, fonte.size * 3)),
      rotulo,
      fonte,
      (margem * 5, margem * 5, largura - margem * 5, altura // 3),
  )

  imagem.save(caminho, format="PNG", dpi=(DPI, DPI), compress_level=6)
  imagem.close()


def gerar_gabarito_tira(caminho, dimensoes, geometria):
  largura, altura = dimensoes
  base_largura = geometria["base_largura"]
  base_altura = geometria["base_altura"]
  escala_x = largura / base_largura
  escala_y = altura / base_altura
  janelas = [
      (
          round(x1 * escala_x),
          round(y1 * escala_y),
          round(x2 * escala_x) - round(x1 * escala_x),
          round(y2 * escala_y) - round(y1 * escala_y),
      )
      for x1, y1, x2, y2 in geometria["janelas"]
  ]

  imagem = Image.new("RGBA", dimensoes, VERDE_AREA)
  draw = ImageDraw.Draw(imagem, "RGBA")
  espessura = max(3, round(min(dimensoes) / 900))
  desenhar_tracejado(
      draw,
      (espessura, espessura, largura - 1 - espessura, altura - 1 - espessura),
      VERMELHO,
      espessura,
  )

  for indice, (x, y, janela_largura, janela_altura) in enumerate(janelas, 1):
    direita = x + janela_largura - 1
    base = y + janela_altura - 1
    draw.rectangle(
        (x, y, direita, base),
        fill=AZUL_AREA,
        outline=VERMELHO,
        width=espessura,
    )
    centro_x = x + janela_largura // 2
    centro_y = y + janela_altura // 2
    draw.line(
        (centro_x, y, centro_x, base),
        fill=AZUL_GUIA,
        width=max(2, espessura // 2),
    )
    draw.line(
        (x, centro_y, direita, centro_y),
        fill=AZUL_GUIA,
        width=max(2, espessura // 2),
    )
    fonte = obter_fonte(
        min(110, max(14, round(min(janela_largura, janela_altura) * 0.05)))
    )
    texto = (
        f"FOTO {indice}"
        f"\n{texto_medida(janela_largura, janela_altura)}"
    )
    desenhar_rotulo(
        draw,
        (centro_x, centro_y),
        texto,
        fonte,
        (x + espessura * 2, y + espessura * 2, direita - espessura * 2,
         base - espessura * 2),
    )

  bandas = []
  y_atual = 0
  for _, y, _, janela_altura in sorted(janelas, key=lambda janela: janela[1]):
    if y > y_atual:
      bandas.append((y_atual, y))
    y_atual = max(y_atual, y + janela_altura)
  if y_atual < altura:
    bandas.append((y_atual, altura))
  banda_arte = max(bandas, key=lambda banda: banda[1] - banda[0]) if bandas else (
      0, altura
  )
  fonte_arte = obter_fonte(min(100, max(16, round(min(dimensoes) * 0.025))))
  desenhar_rotulo(
      draw,
      (largura // 2, (banda_arte[0] + banda_arte[1]) // 2),
      "ÁREA LIVRE PARA ARTE / LOGO"
      f"\nPreencher no CorelDRAW: {largura} x {altura} px",
      fonte_arte,
      (0, banda_arte[0], largura, banda_arte[1]),
  )

  imagem.save(caminho, format="PNG", dpi=(DPI, DPI), compress_level=6)
  imagem.close()
  return janelas


def imprimir_resumo(dimensoes_foto, dimensoes_tira, janelas):
  def dimensao(largura, altura):
    return (
        f"{largura} x {altura} px"
        f"  |  {mm(largura) / 10:.2f} x {mm(altura) / 10:.2f} cm"
    )

  print(f"\nGABARITOS COREL DRAW — {DPI} DPI")
  print("-" * 86)
  print(f"{'Modo':<14}{'Dimensões':<40}{'Arquivo'}")
  print("-" * 86)
  print(
      f"{'1 Foto':<14}{dimensao(*dimensoes_foto):<40}"
      "gabarito_1_foto.png"
  )
  print(
      f"{'Tira 3x':<14}{dimensao(*dimensoes_tira):<40}"
      "gabarito_tira_3x.png"
  )
  print("\nJanelas exatas usadas pelo app.py — (X, Y, W, H):")
  print(
      f"{'Janela':<10}{'X':>9}{'Y':>9}{'W':>9}{'H':>9}"
      f"    {'W x H (mm)':>24}"
  )
  print("-" * 78)
  for indice, (x, y, largura, altura) in enumerate(janelas, 1):
    medidas = f"{mm(largura):.1f} x {mm(altura):.1f}"
    print(
        f"FOTO {indice:<5}{x:>9}{y:>9}{largura:>9}{altura:>9}"
        f"    {medidas:>24}"
    )
    print(
        f"  Coordenadas: ({x}, {y}, {largura}, {altura}) px"
        f"  |  posição ({mm(x):.1f}, {mm(y):.1f}) mm"
    )
  print(f"\nSaída: {PASTA_SAIDA}")


def main():
  config = ler_configuracao()
  _, dimensoes_foto = carregar_moldura(config, "moldura_1foto")
  _, dimensoes_tira = carregar_moldura(config, "moldura_tira3")
  geometria = ler_geometria_tira()
  PASTA_SAIDA.mkdir(parents=True, exist_ok=True)

  caminho_foto = PASTA_SAIDA / "gabarito_1_foto.png"
  caminho_tira = PASTA_SAIDA / "gabarito_tira_3x.png"

  gerar_gabarito_foto(caminho_foto, dimensoes_foto)
  janelas = gerar_gabarito_tira(
      caminho_tira, dimensoes_tira, geometria
  )
  imprimir_resumo(dimensoes_foto, dimensoes_tira, janelas)


if __name__ == "__main__":
  main()
