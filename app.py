import cv2
import json
import os
import queue
import shutil
import threading
import time
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageOps, ImageTk

Image.MAX_IMAGE_PIXELS = None

# --- CONFIGURAÇÕES ---
PASTA_BASE = r"C:\Totem_Fotografico"
PASTA_PRONTA = os.path.join(PASTA_BASE, "fotos_prontas")
PASTA_MOLDURAS = os.path.join(PASTA_BASE, "molduras")
CAMINHO_CONFIG = os.path.join(PASTA_BASE, "config.json")
CAMINHO_MOLDURA = os.path.join(PASTA_BASE, "molduras", "moldura.png")
CAMINHO_MOLDURA_TIRA = os.path.join(
    PASTA_BASE, "molduras", "moldura_tira.png"
)
# Garante que as pastas existem
os.makedirs(PASTA_PRONTA, exist_ok=True)
os.makedirs(PASTA_MOLDURAS, exist_ok=True)


def listar_molduras_disponiveis():
  return sorted(
      (
          nome
          for nome in os.listdir(PASTA_MOLDURAS)
          if nome.lower().endswith(".png")
          and os.path.isfile(os.path.join(PASTA_MOLDURAS, nome))
      ),
      key=lambda nome: nome.casefold(),
  )


def carregar_config():
  molduras = listar_molduras_disponiveis()
  molduras_por_chave = {
      os.path.normcase(os.path.normpath(caminho)): caminho
      for caminho in molduras
  }
  primeira_moldura = molduras[0] if molduras else None

  def moldura_padrao(caminho_legado):
    relativa = os.path.relpath(caminho_legado, PASTA_MOLDURAS)
    chave = os.path.normcase(os.path.normpath(relativa))
    return molduras_por_chave.get(chave, primeira_moldura or relativa)

  config_lida = {}
  config_existente = os.path.exists(CAMINHO_CONFIG)
  if config_existente:
    try:
      with open(CAMINHO_CONFIG, "r", encoding="utf-8") as arquivo:
        dados = json.load(arquivo)
      if isinstance(dados, dict):
        config_lida = dados
      else:
        print("Aviso: config.json deve conter um objeto JSON.")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as erro:
      print(f"Aviso: não foi possível ler config.json ({erro}); usando padrões.")

  def escolher_moldura(chave, padrao):
    if chave not in config_lida:
      return padrao

    valor = config_lida[chave]
    if not isinstance(valor, str):
      return primeira_moldura or padrao
    valor = valor.strip()
    if os.path.isabs(valor):
      try:
        valor = os.path.relpath(valor, PASTA_MOLDURAS)
      except ValueError:
        return primeira_moldura or padrao
    valor = os.path.normpath(valor)
    if valor.lower().startswith("molduras" + os.sep):
      valor = valor[len("molduras" + os.sep):]
    chave_valor = os.path.normcase(os.path.normpath(valor))
    return molduras_por_chave.get(chave_valor, primeira_moldura or padrao)

  config = {
      "moldura_1foto": escolher_moldura(
          "moldura_1foto", moldura_padrao(CAMINHO_MOLDURA)
      ),
      "moldura_tira3": escolher_moldura(
          "moldura_tira3", moldura_padrao(CAMINHO_MOLDURA_TIRA)
      ),
      "modo_atual": config_lida.get("modo_atual", "1_foto"),
      "tempo_contagem": config_lida.get("tempo_contagem", 3),
      "tempo_resultado": config_lida.get("tempo_resultado", 5),
      "indice_camera": config_lida.get("indice_camera", 0),
  }
  if config["modo_atual"] not in ("1_foto", "tira_3"):
    config["modo_atual"] = "1_foto"
  chave_moldura_ativa = (
      "moldura_tira3"
      if config["modo_atual"] == "tira_3"
      else "moldura_1foto"
  )
  config["moldura"] = escolher_moldura(
      "moldura", config[chave_moldura_ativa]
  )
  tempo = config["tempo_contagem"]
  if isinstance(tempo, bool) or not isinstance(tempo, int) or tempo < 1:
    config["tempo_contagem"] = 3
  tempo_resultado = config["tempo_resultado"]
  if (
      isinstance(tempo_resultado, bool)
      or not isinstance(tempo_resultado, int)
      or tempo_resultado < 1
  ):
    config["tempo_resultado"] = 5
  indice_camera = config["indice_camera"]
  if (
      isinstance(indice_camera, bool)
      or not isinstance(indice_camera, int)
      or indice_camera not in (0, 1, 2)
  ):
    config["indice_camera"] = 0

  if (
      not config_existente
      or config_lida.get("moldura") != config["moldura"]
      or config_lida.get("indice_camera") != config["indice_camera"]
      or config_lida.get("tempo_resultado") != config["tempo_resultado"]
  ):
    salvar_config(config)
  return config


def salvar_config(cfg):
  with open(CAMINHO_CONFIG, "w", encoding="utf-8") as arquivo:
    json.dump(cfg, arquivo, ensure_ascii=False, indent=2)


class TotemApp:

  def __init__(self, root):
    self.root = root
    self.root.title("Totem Fotográfico")
    self.root.configure(
        bg="#121212", borderwidth=0, highlightthickness=0
    )

    # Tela cheia (aperte ESC para sair durante os testes)
    self.root.attributes("-fullscreen", True)
    self.root.bind(
        "<Escape>", lambda e: self.root.attributes("-fullscreen", False)
    )
    self.root.protocol("WM_DELETE_WINDOW", self.fechar_aplicativo)
    self.root.bind("<space>", lambda e: self.iniciar_sequencia())
    self.root.bind("<m>", lambda e: self.alternar_modo())
    self.root.bind("<c>", lambda e: self.abrir_menu_operador())
    self.root.bind("<C>", lambda e: self.abrir_menu_operador())
    self.root.bind("<Double-Button-1>", self.verificar_clique_menu)

    self.config = carregar_config()
    self.ocupado = False
    self.em_captura = False
    self.modo_tira = self.config["modo_atual"] == "tira_3"
    self.tempo_contagem = self.config["tempo_contagem"]
    self.tempo_resultado = self.config["tempo_resultado"]
    self.indice_camera = self.config["indice_camera"]
    self.cap = None
    self._frame_lock = threading.Lock()
    self._frame_bruto_atual = None
    self._camera_stop_event = None
    self._camera_thread = None
    self._camera_generation = 0
    self.ultimo_frame_limpo = None
    self.camera_erro = None
    if not self.abrir_camera(self.indice_camera):
      self.camera_erro = (
          f"Não foi possível abrir a câmera {self.indice_camera}. "
          "Use C para selecionar outra câmera."
      )
    self.fotos_sessao = []
    self.resultados_captura = queue.Queue()
    self.moldura_atual_pil = None
    self.moldura_atual_path = None
    self._moldura_tk_cache = None
    self._moldura_tamanho_cache = None
    self.erro_moldura = None
    try:
      self.recarregar_moldura_ativa()
    except (OSError, ValueError) as erro:
      self.erro_moldura = str(erro)
    self.liveview_ativo = False
    self.liveview_loop_agendado = False
    self.liveview_photo = None
    self.preview_photo = None
    self.item_preview = None
    self.item_sombra = None
    self.item_texto = None
    self.item_status = None
    self.item_flash = None
    self.texto_central = "📸"
    self.tamanho_texto_central = 120
    self.cor_texto_central = "#00E676"

    self.canvas = tk.Canvas(
        root, bg="#121212", highlightthickness=0, bd=0
    )
    self.canvas.pack(fill="both", expand=True)
    self.canvas.bind("<Button-1>", lambda evento: self.iniciar_sequencia())
    self.canvas.bind("<Configure>", self.redimensionar_canvas)
    self.item_liveview = self.canvas.create_image(
        0, 0, anchor="nw", tags=("camada_video",)
    )
    self.item_moldura = self.canvas.create_image(
        0, 0, anchor="nw", tags=("camada_moldura",)
    )

    self.lbl_erro = tk.Label(
        root,
        text="",
        font=("Arial", 14, "bold"),
        fg="#FFFFFF",
        bg="#8E2424",
        wraplength=740,
        padx=14,
        pady=8,
    )
    self.lbl_erro.place_forget()

    self.redimensionar_canvas()

    self.iniciar_liveview()
    self.root.after(50, self.verificar_resultado_captura)
    if self.camera_erro:
      self.root.after(0, self.exibir_erro, self.camera_erro)
    elif self.erro_moldura:
      self.root.after(0, self.exibir_erro, self.erro_moldura)

  def alternar_modo(self):
    if self.ocupado:
      return

    modo_tira = not self.modo_tira
    config_nova = self.config.copy()
    config_nova["modo_atual"] = "tira_3" if modo_tira else "1_foto"
    try:
      salvar_config(config_nova)
    except OSError as erro:
      messagebox.showerror(
          "Erro ao salvar configuração",
          f"Não foi possível salvar config.json:\n{erro}",
          parent=self.root,
      )
      return

    self.config = config_nova
    self.modo_tira = modo_tira
    try:
      self.recarregar_moldura_ativa()
    except (OSError, ValueError) as erro:
      self.exibir_erro(str(erro))
      return
    self.atualizar_liveview_imediato()

  def abrir_camera(self, indice):
    if (
        self.cap is not None
        and self.indice_camera == indice
        and self.cap.isOpened()
    ):
      return True

    nova_camera = cv2.VideoCapture(indice, cv2.CAP_DSHOW)
    if not nova_camera.isOpened():
      nova_camera.release()
      return False

    nova_camera.set(
        cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG")
    )
    nova_camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    nova_camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    evento_anterior = self._camera_stop_event
    camera_anterior = self.cap
    with self._frame_lock:
      self._camera_generation += 1
      geracao = self._camera_generation
      self._frame_bruto_atual = None
      self.cap = nova_camera
      self.indice_camera = indice
      self._camera_stop_event = threading.Event()
      evento_novo = self._camera_stop_event

    if evento_anterior is not None:
      evento_anterior.set()
    if camera_anterior is not None:
      camera_anterior.release()

    self._camera_thread = threading.Thread(
        target=self._ler_frames_camera,
        args=(nova_camera, evento_novo, geracao),
        daemon=True,
    )
    self._camera_thread.start()
    self.ultimo_frame_limpo = None
    return True

  def _ler_frames_camera(self, camera, stop_event, geracao):
    while not stop_event.is_set():
      ret, frame = camera.read()
      if not ret or frame is None or not frame.size:
        stop_event.wait(0.01)
        continue

      with self._frame_lock:
        if (
            not stop_event.is_set()
            and geracao == self._camera_generation
        ):
          self._frame_bruto_atual = frame

  def fechar_aplicativo(self):
    self.liveview_ativo = False
    if self._camera_stop_event is not None:
      self._camera_stop_event.set()
    with self._frame_lock:
      self._camera_generation += 1
      self._frame_bruto_atual = None
      camera = self.cap
      self.cap = None
    if camera is not None:
      camera.release()
    self.root.destroy()

  def recarregar_moldura_ativa(self):
    self.moldura_atual_pil = None
    self.moldura_atual_path = None
    self._moldura_tk_cache = None
    self._moldura_tamanho_cache = None
    if getattr(self, "item_moldura", None) is not None:
      self.canvas.itemconfigure(self.item_moldura, image="", state="hidden")

    chave_moldura = "moldura_tira3" if self.modo_tira else "moldura_1foto"
    nome_moldura = self.config.get(chave_moldura) or self.config.get(
        "moldura"
    )
    if not nome_moldura:
      raise ValueError(f"A configuração não define a moldura {chave_moldura}.")
    caminho = os.path.join(PASTA_MOLDURAS, nome_moldura)
    if not os.path.isfile(caminho):
      raise FileNotFoundError(
          f"A moldura selecionada não foi encontrada: {caminho}"
      )

    with Image.open(caminho) as arquivo:
      self.moldura_atual_pil = self.normalizar_moldura(arquivo)
    self.moldura_atual_path = caminho
    self.erro_moldura = None
    print(f"Moldura ativa: {caminho}")

  def normalizar_moldura(self, imagem):
    imagem = imagem.convert("RGBA")
    largura, altura = imagem.size
    if largura > 2560:
      nova_largura = 2400
      nova_altura = max(1, round(altura * nova_largura / largura))
      imagem = imagem.resize(
          (nova_largura, nova_altura), Image.Resampling.LANCZOS
      )
    return imagem

  def atualizar_moldura_canvas(self):
    largura = self.canvas.winfo_width()
    altura = self.canvas.winfo_height()
    if largura <= 1 or altura <= 1:
      return

    tamanho = (largura, altura)
    if self.moldura_atual_pil is None:
      self._moldura_tk_cache = None
      self._moldura_tamanho_cache = None
      self.canvas.itemconfigure(self.item_moldura, image="", state="hidden")
      return

    if (
        self._moldura_tk_cache is None
        or self._moldura_tamanho_cache != tamanho
    ):
      moldura_redimensionada = self.moldura_atual_pil.resize(
          tamanho, Image.Resampling.LANCZOS
      )
      self._moldura_tk_cache = ImageTk.PhotoImage(moldura_redimensionada)
      self._moldura_tamanho_cache = tamanho
      self.canvas.itemconfigure(
          self.item_moldura, image=self._moldura_tk_cache
      )

    self.canvas.coords(self.item_moldura, 0, 0)
    self.canvas.itemconfigure(self.item_moldura, state="normal")

  def carregar_moldura_para_composicao(self, moldura, modo_tira):
    if moldura is None:
      config = carregar_config()
      chave = "moldura_tira3" if modo_tira else "moldura_1foto"
      caminho = os.path.join(PASTA_MOLDURAS, config[chave])
      with Image.open(caminho) as arquivo:
        moldura = self.normalizar_moldura(arquivo)
    else:
      moldura = self.normalizar_moldura(moldura)
    return moldura

  def redimensionar_canvas(self, evento=None):
    largura = max(self.canvas.winfo_width(), 1)
    altura = max(self.canvas.winfo_height(), 1)
    centro_x = largura / 2
    centro_y = altura / 2
    if not self.ocupado and not self.em_captura:
      self.mostrar_texto_inicial()
    if getattr(self, "item_sombra", None) is not None:
      self.canvas.coords(self.item_sombra, centro_x, centro_y)
      self.canvas.coords(self.item_texto, centro_x, centro_y)
      self.canvas.coords(self.item_status, centro_x, max(35, altura * 0.08))
      self.canvas.coords(self.item_flash, 0, 0, largura, altura)
    if evento is not None:
      self.atualizar_liveview_imediato()

  def mostrar_texto_inicial(self):
    self.canvas.delete("texto_inicial")
    largura = max(self.canvas.winfo_width(), 1)
    altura = max(self.canvas.winfo_height(), 1)
    fonte = max(15, min(30, largura // 20))
    self.canvas.create_text(
        largura // 2,
        altura // 2,
        text="TOQUE NA TELA PARA TIRAR UMA FOTO",
        fill="#FFFFFF",
        font=("Arial", fonte, "bold"),
        anchor="center",
        tags="texto_inicial",
    )

  def criar_overlays_temporarios(self):
    self.item_preview = self.canvas.create_image(0, 0, anchor="center")
    self.item_sombra = self.canvas.create_text(
        0, 0, text="", fill="#000000", font=("Arial", 28, "bold"),
        anchor="center", state="hidden",
    )
    self.item_texto = self.canvas.create_text(
        0, 0, text="", fill="#FFFFFF", font=("Arial", 28, "bold"),
        anchor="center", state="hidden",
    )
    self.item_status = self.canvas.create_text(
        0, 0, text="", fill="#FFFFFF", font=("Arial", 24, "bold"),
        anchor="center",
    )
    self.item_flash = self.canvas.create_rectangle(
        0, 0, 1, 1, fill="#FFFFFF", outline="", state="hidden"
    )
    self.redimensionar_canvas()

  def limpar_overlays_temporarios(self):
    for atributo in (
        "item_preview",
        "item_sombra",
        "item_texto",
        "item_status",
        "item_flash",
    ):
      item = getattr(self, atributo, None)
      if item is not None:
        self.canvas.delete(item)
        setattr(self, atributo, None)

  def verificar_clique_menu(self, evento):
    x = self.root.winfo_pointerx() - self.root.winfo_rootx()
    y = self.root.winfo_pointery() - self.root.winfo_rooty()
    if 0 <= x < 120 and 0 <= y < 120:
      self.abrir_menu_operador()

  def abrir_menu_operador(self):
    if self.em_captura:
      return

    menu_existente = getattr(self, "janela_menu_operador", None)
    if menu_existente is not None and menu_existente.winfo_exists():
      menu_existente.lift()
      menu_existente.focus_force()
      return

    janela = tk.Toplevel(self.root)
    self.janela_menu_operador = janela
    janela.title("Menu do Operador")
    janela.configure(bg="#1E1E1E")
    janela.transient(self.root)
    janela.resizable(False, False)
    janela.grab_set()

    def fechar_menu():
      janela.grab_release()
      janela.destroy()
      self.janela_menu_operador = None

    janela.protocol("WM_DELETE_WINDOW", fechar_menu)

    conteudo = tk.Frame(janela, bg="#1E1E1E", padx=18, pady=16)
    conteudo.pack(fill=tk.BOTH, expand=True)
    tk.Label(
        conteudo,
        text="CONFIGURAÇÕES DO TOTEM",
        font=("Arial", 18, "bold"),
        fg="#FFFFFF",
        bg="#1E1E1E",
    ).pack(pady=(0, 14))

    molduras_frame = tk.Frame(conteudo, bg="#1E1E1E")
    molduras_frame.pack(fill=tk.BOTH, expand=True)
    molduras = listar_molduras_disponiveis()
    self.var_moldura_1foto = tk.StringVar(
        master=janela, value=self.config["moldura_1foto"]
    )
    self.var_moldura_tira3 = tk.StringVar(
        master=janela, value=self.config["moldura_tira3"]
    )
    combo_1foto = self.criar_seletor_moldura(
        molduras_frame,
        "Moldura — 1 Foto",
        0,
        self.var_moldura_1foto,
        molduras,
    )
    combo_tira = self.criar_seletor_moldura(
        molduras_frame,
        "Moldura — Tira 3x",
        1,
        self.var_moldura_tira3,
        molduras,
    )

    def atualizar_listas(moldura_importada=None):
      nonlocal molduras
      selecionada_1 = combo_1foto.get()
      selecionada_tira = combo_tira.get()
      molduras = listar_molduras_disponiveis()
      for combo, selecionada in (
          (combo_1foto, selecionada_1),
          (combo_tira, selecionada_tira),
      ):
        combo.configure(values=molduras)
        if selecionada in molduras:
          combo.set(selecionada)
        elif moldura_importada in molduras:
          combo.set(moldura_importada)
        elif molduras:
          combo.set(molduras[0])
        else:
          combo.set("")

    def importar_moldura():
      origem = filedialog.askopenfilename(
          parent=janela,
          title="Importar moldura PNG",
          filetypes=[("Imagens PNG", "*.png")],
      )
      if not origem:
        return
      if os.path.splitext(origem)[1].lower() != ".png":
        messagebox.showerror(
            "Arquivo inválido",
            "Selecione um arquivo PNG.",
            parent=janela,
        )
        return

      nome = os.path.basename(origem)
      destino = os.path.join(PASTA_MOLDURAS, nome)
      if os.path.normcase(os.path.abspath(origem)) != os.path.normcase(
          os.path.abspath(destino)
      ):
        base, extensao = os.path.splitext(nome)
        sufixo = 2
        while os.path.exists(destino):
          destino = os.path.join(
              PASTA_MOLDURAS, f"{base}_{sufixo}{extensao}"
          )
          sufixo += 1
        try:
          shutil.copy2(origem, destino)
        except OSError as erro:
          messagebox.showerror(
              "Erro ao importar moldura",
              f"Não foi possível copiar o arquivo:\n{erro}",
              parent=janela,
          )
          return

      atualizar_listas(os.path.relpath(destino, PASTA_MOLDURAS))

    tk.Button(
        conteudo,
        text="Importar Nova Moldura (.png)",
        command=importar_moldura,
    ).pack(pady=(10, 8))

    preferencias = tk.Frame(conteudo, bg="#1E1E1E")
    preferencias.pack(fill=tk.X, pady=6)
    self.var_modo_menu = tk.StringVar(
        master=janela,
        value="tira_3" if self.modo_tira else "1_foto",
    )
    tk.Label(
        preferencias,
        text="Modo ativo:",
        fg="#FFFFFF",
        bg="#1E1E1E",
    ).grid(row=0, column=0, sticky="w")
    tk.Radiobutton(
        preferencias,
        text="1 Foto",
        variable=self.var_modo_menu,
        value="1_foto",
        fg="#FFFFFF",
        bg="#1E1E1E",
        selectcolor="#2C2C2C",
        activebackground="#1E1E1E",
    ).grid(row=0, column=1, padx=8)
    tk.Radiobutton(
        preferencias,
        text="Tira 3x",
        variable=self.var_modo_menu,
        value="tira_3",
        fg="#FFFFFF",
        bg="#1E1E1E",
        selectcolor="#2C2C2C",
        activebackground="#1E1E1E",
    ).grid(row=0, column=2, padx=8)

    tk.Label(
        preferencias,
        text="Números na contagem:",
        fg="#FFFFFF",
        bg="#1E1E1E",
    ).grid(row=1, column=0, sticky="w", pady=(8, 0))
    self.var_tempo_menu = tk.StringVar(
        master=janela, value=str(self.tempo_contagem)
    )
    tk.Entry(preferencias, textvariable=self.var_tempo_menu, width=6).grid(
        row=1, column=1, sticky="w", pady=(8, 0)
    )

    tk.Label(
        preferencias,
        text="Câmera:",
        fg="#FFFFFF",
        bg="#1E1E1E",
    ).grid(row=2, column=0, sticky="w", pady=(8, 0))
    self.var_camera_menu = tk.IntVar(master=janela, value=self.indice_camera)
    tk.OptionMenu(preferencias, self.var_camera_menu, 0, 1, 2).grid(
        row=2, column=1, sticky="w", pady=(8, 0)
    )

    total_fotos = self.contar_fotos_prontas()
    tk.Label(
        conteudo,
        text=f"Fotos geradas: {total_fotos}",
        fg="#CCCCCC",
        bg="#1E1E1E",
    ).pack(pady=(4, 10))

    botoes = tk.Frame(conteudo, bg="#1E1E1E")
    botoes.pack(fill=tk.X)

    def salvar_aplicar():
      selecionada_1 = combo_1foto.get().strip()
      selecionada_tira = combo_tira.get().strip()
      molduras = listar_molduras_disponiveis()
      if (
          selecionada_1 not in molduras
          or selecionada_tira not in molduras
      ):
        messagebox.showerror(
            "Moldura não selecionada",
            "Escolha uma moldura PNG válida para cada modo.",
            parent=janela,
        )
        return
      modo_atual = self.var_modo_menu.get()
      arquivo_escolhido = (
          selecionada_tira if modo_atual == "tira_3" else selecionada_1
      )
      if modo_atual == "tira_3":
        selecionada_tira = arquivo_escolhido
      else:
        selecionada_1 = arquivo_escolhido
      try:
        tempo = int(self.var_tempo_menu.get())
        if tempo < 1:
          raise ValueError("A contagem precisa ter pelo menos 1 número.")
      except ValueError as erro:
        messagebox.showerror(
            "Contagem inválida",
            f"Informe um número inteiro positivo.\n{erro}",
            parent=janela,
        )
        return

      config_nova = {
          "moldura_1foto": selecionada_1,
          "moldura_tira3": selecionada_tira,
          "moldura": arquivo_escolhido,
          "modo_atual": modo_atual,
          "tempo_contagem": tempo,
          "tempo_resultado": self.tempo_resultado,
          "indice_camera": self.var_camera_menu.get(),
      }
      indice_camera_antiga = self.indice_camera
      if not self.abrir_camera(config_nova["indice_camera"]):
        messagebox.showerror(
            "Câmera indisponível",
            f"Não foi possível abrir a câmera {config_nova['indice_camera']}.",
            parent=janela,
        )
        return
      try:
        salvar_config(config_nova)
      except OSError as erro:
        if self.indice_camera != indice_camera_antiga:
          self.abrir_camera(indice_camera_antiga)
        messagebox.showerror(
            "Erro ao salvar configuração",
            f"Não foi possível salvar config.json:\n{erro}",
            parent=janela,
        )
        return

      self.config = config_nova
      self.modo_tira = modo_atual == "tira_3"
      self.tempo_contagem = tempo
      self.camera_erro = None
      self.lbl_erro.place_forget()
      print("SALVANDO NO CONFIG:", arquivo_escolhido)
      try:
        self.recarregar_moldura_ativa()
      except (OSError, ValueError) as erro:
        messagebox.showerror(
            "Erro ao carregar moldura",
            f"Não foi possível carregar a moldura selecionada:\n{erro}",
            parent=janela,
        )
        return
      self.atualizar_moldura_canvas()
      self.canvas.tag_raise("camada_moldura")
      self.atualizar_liveview_imediato()
      fechar_menu()

    tk.Button(
        botoes,
        text="Salvar e Aplicar",
        command=salvar_aplicar,
        bg="#00C853",
        fg="#FFFFFF",
        padx=14,
    ).pack(side=tk.RIGHT, padx=(8, 0))
    tk.Button(
        botoes,
        text="Cancelar",
        command=fechar_menu,
        padx=14,
    ).pack(side=tk.RIGHT)

  def criar_seletor_moldura(
      self, parent, titulo, coluna, variable, molduras
  ):
    painel = tk.Frame(parent, bg="#1E1E1E")
    painel.grid(row=0, column=coluna, padx=6, sticky="nsew")
    parent.grid_columnconfigure(coluna, weight=1)
    tk.Label(
        painel,
        text=titulo,
        fg="#FFFFFF",
        bg="#1E1E1E",
    ).pack(anchor="w", pady=(0, 4))

    seletor = ttk.Combobox(
        painel,
        textvariable=variable,
        values=molduras,
        state="readonly",
        width=34,
    )
    seletor.pack(fill=tk.X, expand=True)
    if variable.get() not in molduras and molduras:
      seletor.current(0)
    return seletor

  def contar_fotos_prontas(self):
    extensoes = (".jpg", ".jpeg", ".png")
    return sum(
        1
        for nome in os.listdir(PASTA_PRONTA)
        if nome.lower().endswith(extensoes)
        and os.path.isfile(os.path.join(PASTA_PRONTA, nome))
    )

  def iniciar_liveview(self):
    self.liveview_ativo = True

    if not self.liveview_loop_agendado:
      self.liveview_loop_agendado = True
      self.atualizar_liveview()

  def atualizar_liveview(self):
    if not self.liveview_ativo:
      self.liveview_loop_agendado = False
      return

    with self._frame_lock:
      frame = (
          self._frame_bruto_atual.copy()
          if self._frame_bruto_atual is not None
          else None
      )
    if frame is not None:
      frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
      imagem = ImageOps.mirror(Image.fromarray(frame_rgb))
      self.ultimo_frame_limpo = imagem.copy()
      self.renderizar_liveview(imagem)

    self.root.after(30, self.atualizar_liveview)

  def renderizar_liveview(self, imagem):
    largura = self.canvas.winfo_width()
    altura = self.canvas.winfo_height()
    if largura <= 1 or altura <= 1:
      return
    tamanho = (largura, altura)
    quadro = self.preencher_frame_com_corte(
        imagem,
        tamanho,
        Image.Resampling.BILINEAR,
    )
    self.exibir_liveview(quadro)
    self.atualizar_moldura_canvas()

  def preencher_frame_com_corte(
      self, imagem, tamanho, metodo=Image.Resampling.LANCZOS
  ):
    return ImageOps.fit(
        imagem.convert("RGB"),
        tamanho,
        metodo,
        centering=(0.5, 0.5),
    )

  def atualizar_liveview_imediato(self):
    if self.liveview_ativo and self.ultimo_frame_limpo is not None:
      self.renderizar_liveview(self.ultimo_frame_limpo)

  def exibir_liveview(self, imagem):
    if not self.liveview_ativo:
      return

    self.liveview_photo = ImageTk.PhotoImage(imagem)
    self.canvas.itemconfigure(self.item_liveview, image=self.liveview_photo)
    self.canvas.coords(self.item_liveview, 0, 0)
    self.canvas.itemconfigure(self.item_moldura, state="normal")
    if self.item_preview is not None:
      self.canvas.itemconfigure(self.item_preview, image="")

  def iniciar_sequencia(self):
    if self.ocupado or self.em_captura:
      return
    self.em_captura = True
    self.ocupado = True
    self.lbl_erro.place_forget()
    self.fotos_sessao = []
    self.canvas.delete("texto_inicial")
    self.criar_overlays_temporarios()
    self.canvas.itemconfigure(self.item_status, text="")

    self.root.after(150, self.iniciar_contagem_foto)

  def iniciar_contagem_foto(self):
    if self.modo_tira:
      self.canvas.itemconfigure(
          self.item_status,
          text=f"PREPARE-SE! FOTO {len(self.fotos_sessao) + 1} DE 3",
      )
    else:
      self.canvas.itemconfigure(self.item_status, text="")
    self.executar_passo_contagem(0)

  def executar_passo_contagem(self, indice):
    if indice < self.tempo_contagem:
      texto = str(self.tempo_contagem - indice)
      self.atualizar_texto_central(texto, 110, "#FFEA00")
      self.root.after(1000, lambda: self.executar_passo_contagem(indice + 1))
      return

    self.atualizar_texto_central("SORRIA!", 36, "#FFFFFF")
    self.root.after(1000, self._executar_disparo)

  def _executar_disparo(self):
    self.atualizar_texto_central(
        "", self.tamanho_texto_central, self.cor_texto_central
    )
    try:
      if self.moldura_atual_pil is None:
        self.config = carregar_config()
        self.modo_tira = self.config["modo_atual"] == "tira_3"
        self.recarregar_moldura_ativa()
      if self.cap is None or not self.cap.isOpened():
        raise RuntimeError(
            f"A câmera {self.indice_camera} não está disponível."
        )
      if self.ultimo_frame_limpo is None:
        raise RuntimeError("A câmera ainda não forneceu um frame válido.")
      frame_capturado = self.ultimo_frame_limpo.copy()
    except (RuntimeError, cv2.error, OSError, ValueError) as erro:
      self.exibir_erro(str(erro))
      self.root.after(4000, self.resetar_tela)
      return

    self.efeito_flash()
    self.fotos_sessao.append(frame_capturado)
    if self.modo_tira and len(self.fotos_sessao) < 3:
      self.root.after(1200, self.preparar_proxima_foto)
      return

    largura = max(self.canvas.winfo_width(), 1)
    altura = max(self.canvas.winfo_height(), 1)
    moldura_capturada = self.moldura_atual_pil
    threading.Thread(
        target=self.processar_captura,
        args=(
            tuple(self.fotos_sessao),
            self.modo_tira,
            (largura, altura),
            moldura_capturada,
        ),
        daemon=True,
    ).start()

  def processar_captura(
      self, fotos_capturadas, modo_tira, tamanho_preview, moldura_capturada
  ):
    try:
      moldura_capturada = self.carregar_moldura_para_composicao(
          moldura_capturada, modo_tira
      )
      if modo_tira:
        caminho_final = self.montar_tira_3_fotos(
            fotos_capturadas, moldura_capturada
        )
      else:
        caminho_final = self.aplicar_moldura(
            fotos_capturadas[0], moldura_capturada
        )

      with Image.open(caminho_final) as imagem:
        preview = ImageOps.contain(
            imagem.convert("RGBA"),
            tamanho_preview,
            Image.Resampling.LANCZOS,
        ).copy()
      self.resultados_captura.put(("sucesso", preview))
    except Exception as erro:
      traceback.print_exc()
      self.resultados_captura.put(("erro", str(erro)))

  def verificar_resultado_captura(self):
    try:
      tipo, resultado = self.resultados_captura.get_nowait()
    except queue.Empty:
      pass
    else:
      if tipo == "sucesso":
        self.exibir_foto_pronta(resultado)
        self.root.after(
            self.tempo_resultado * 1000, self.resetar_tela
        )
      else:
        self.exibir_erro(resultado)
        self.root.after(4000, self.resetar_tela)

    self.root.after(50, self.verificar_resultado_captura)

  def preparar_proxima_foto(self):
    self.iniciar_contagem_foto()

  def atualizar_texto_central(self, texto, tamanho, cor):
    self.texto_central = texto
    self.tamanho_texto_central = tamanho
    self.cor_texto_central = cor
    self.canvas.itemconfigure(
        self.item_sombra,
        text=texto,
        font=("Arial", tamanho, "bold"),
    )
    self.canvas.itemconfigure(
        self.item_texto,
        text=texto,
        fill=cor,
        font=("Arial", tamanho, "bold"),
    )
    estado = "normal" if texto else "hidden"
    self.canvas.itemconfigure(self.item_sombra, state=estado)
    self.canvas.itemconfigure(self.item_texto, state=estado)

  def exibir_erro(self, mensagem):
    self.lbl_erro.config(text=f"ERRO: {mensagem}")
    self.lbl_erro.place(
        relx=0.5,
        rely=1.0,
        relwidth=0.96,
        anchor="s",
    )
    self.lbl_erro.lift()

  def efeito_flash(self):
    largura = max(self.canvas.winfo_width(), 1)
    altura = max(self.canvas.winfo_height(), 1)
    self.canvas.coords(self.item_flash, 0, 0, largura, altura)
    self.canvas.itemconfigure(self.item_flash, state="normal")
    self.canvas.tag_raise(self.item_flash)
    self.root.after(
        150,
        lambda: self.canvas.itemconfigure(self.item_flash, state="hidden")
        if self.item_flash is not None
        else None,
    )

  def aplicar_moldura(self, foto_bruta, moldura_atual_pil):
    if moldura_atual_pil is None:
      raise RuntimeError("Não há moldura carregada para a foto.")

    largura_final, altura_final = moldura_atual_pil.size
    moldura_rgba = moldura_atual_pil.resize(
        (largura_final, altura_final), Image.Resampling.LANCZOS
    )
    base = self.preencher_frame_com_corte(
        foto_bruta,
        (largura_final, altura_final),
    )
    base_rgba = base.convert("RGBA")
    foto_final = Image.alpha_composite(base_rgba, moldura_rgba).convert("RGB")

    caminho_saida = os.path.join(
        PASTA_PRONTA, f"foto_{int(time.time())}.jpg"
    )
    foto_final.save(caminho_saida, "JPEG", quality=95)
    return caminho_saida

  def montar_tira_3_fotos(self, fotos, moldura_atual_pil):
    if len(fotos) != 3:
      raise ValueError("A tira precisa de exatamente 3 fotos.")

    if moldura_atual_pil is None:
      raise RuntimeError("Não há moldura carregada para a tira.")

    largura_final, altura_final = moldura_atual_pil.size
    escala_x = largura_final / 600
    escala_y = altura_final / 1800
    moldura_rgba = moldura_atual_pil.resize(
        (largura_final, altura_final), Image.Resampling.LANCZOS
    )
    tira = Image.new(
        "RGBA", (largura_final, altura_final), (255, 255, 255, 255)
    )
    for foto_bruta, posicao_y in zip(fotos, (40, 545, 1050)):
      tamanho_foto = (
          max(1, round(540 * escala_x)),
          max(1, round(480 * escala_y)),
      )
      posicao = (
          round(30 * escala_x),
          round(posicao_y * escala_y),
      )
      foto = self.preencher_frame_com_corte(
          foto_bruta, tamanho_foto
      ).convert("RGBA")
      tira.paste(foto, posicao)

    foto_final = Image.alpha_composite(tira, moldura_rgba).convert("RGB")

    caminho_saida = os.path.join(
        PASTA_PRONTA, f"tira_{int(time.time())}.jpg"
    )
    foto_final.save(caminho_saida, "JPEG", quality=95)
    return caminho_saida

  def exibir_foto_pronta(self, foto):
    self.liveview_ativo = False
    self.preview_photo = ImageTk.PhotoImage(foto)
    self.canvas.itemconfigure(self.item_liveview, image="")
    self.canvas.itemconfigure(self.item_moldura, state="hidden")
    self.canvas.itemconfigure(
        self.item_preview, image=self.preview_photo
    )
    self.canvas.coords(
        self.item_preview,
        self.canvas.winfo_width() / 2,
        self.canvas.winfo_height() / 2,
    )
    self.canvas.itemconfigure(
        self.item_status, text="FICOU ÓTIMA! RETIRE SUA FOTO NO SITE"
    )
    self.liveview_photo = None

  def resetar_tela(self):
    self.lbl_erro.place_forget()
    self.limpar_overlays_temporarios()
    self.preview_photo = None
    self.texto_central = ""
    self.tamanho_texto_central = 120
    self.cor_texto_central = "#00E676"
    self.liveview_photo = None
    self.em_captura = False
    self.ocupado = False
    self.mostrar_texto_inicial()
    self.iniciar_liveview()


if __name__ == "__main__":
  root = tk.Tk()
  app = TotemApp(root)
  root.mainloop()