import difflib
import io
import re
import shutil
import unicodedata
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from flask import Flask, render_template, request, send_file
from PyPDF2 import PdfMerger, PdfReader, PdfWriter
from werkzeug.utils import secure_filename

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None
try:
    from rapidfuzz import fuzz
except Exception:
    fuzz = None


BASE_DIR = Path(__file__).resolve().parent
WORK_DIR = BASE_DIR / "uploads"
MIN_SIMILARIDADE_PADRAO = 0.85
PALAVRAS_LIGACAO = {"DA", "DE", "DO", "DAS", "DOS", "E"}
EQUIVALENCIAS = {
    "SOUSA": "SOUZA",
    "SOUZA": "SOUSA",
    "LUIS": "LUIZ",
    "LUIZ": "LUIS",
    "FILIPE": "FELIPE",
    "FELIPE": "FILIPE",
    "FILIPI": "FILIPE",
    "MANOEL": "MANUEL",
    "MANUEL": "MANOEL",
}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024


@dataclass
class Documento:
    nome_normalizado: str
    arquivo: str
    caminho: Path


def remover_acentos(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto)
    return texto.encode("ASCII", "ignore").decode("ASCII")


def limpar_nome(nome_arquivo: str) -> str:
    nome = Path(nome_arquivo).stem.lower()
    nome = remover_acentos(nome)
    nome = re.sub(r"^\d+\s*[-_.]?\s*", "", nome)
    nome = re.sub(r"[_\-.,;()[\]{}]+", " ", nome)
    nome = re.sub(r"\b(holerite|hollerite|folha|pagamento|comprovante|recibo|salario)\b", " ", nome)
    nome = re.sub(r"\s+", " ", nome)
    return nome.strip().upper()


def normalizar_texto(texto: str) -> str:
    return remover_acentos(re.sub(r"\s+", " ", texto or "").strip()).upper()


def tokens_nome(texto: str) -> list[str]:
    tokens = normalizar_texto(texto).split()
    tokens = [t for t in tokens if t not in PALAVRAS_LIGACAO]
    return [EQUIVALENCIAS.get(t, t) for t in tokens]


def similaridade_texto(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if fuzz:
        return float(fuzz.ratio(a, b)) / 100.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def token_parece_igual(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(b) >= 2 and a.startswith(b):
        return True
    if len(a) >= 3 and b.startswith(a):
        return True
    return similaridade_texto(a, b) >= 0.80


def eh_abreviacao_final(nome_oficial: str, nome_banco: str) -> bool:
    to = tokens_nome(nome_oficial)
    tb = tokens_nome(nome_banco)
    if not to or not tb or len(tb) > len(to):
        return False
    i = 0
    for b in tb:
        while i < len(to) and not token_parece_igual(to[i], b):
            i += 1
        if i >= len(to):
            return False
        i += 1
    return True


def score_nome(nome_oficial: str, nome_banco: str) -> float:
    to = tokens_nome(nome_oficial)
    tb = tokens_nome(nome_banco)
    if not to or not tb:
        return 0.0
    if to == tb:
        return 100.0

    sim_compacto = similaridade_texto("".join(to), "".join(tb))
    sim_frase = similaridade_texto(" ".join(to), " ".join(tb))
    primeiro_ok = 1.0 if token_parece_igual(to[0], tb[0]) else 0.0
    ultimo_ok = 1.0 if token_parece_igual(to[-1], tb[-1]) else 0.0

    pos = 0
    encontrados = 0
    for b in tb:
        while pos < len(to):
            if token_parece_igual(to[pos], b):
                encontrados += 1
                pos += 1
                break
            pos += 1
    cob_b = encontrados / len(tb)
    cob_o = encontrados / len(to)

    score = 100 * (0.38 * cob_b + 0.27 * cob_o + 0.17 * sim_frase + 0.12 * sim_compacto + 0.04 * primeiro_ok + 0.02 * ultimo_ok)

    if eh_abreviacao_final(nome_oficial, nome_banco):
        score = max(score, 79.0)
    if len(tb) <= 2 and len(to) >= 4:
        score = min(score, 77.5)
    return round(max(0.0, min(score, 100.0)), 2)


def extrair_nome_creditado_pagina(texto: str) -> str:
    txt = (texto or "").replace("\r", "\n")
    padroes = [
        r"DADOS\s+DA\s+CONTA\s+CREDITADA\s*:?.*?NOME\s*:\s*(.+?)(?:\n\s*(?:AG|AG[ÊE]NCIA|AGENCIA|CONTA|VALOR|CPF|CNPJ)\b|$)",
        r"NOME\s*:\s*(.+?)(?:\n\s*(?:AG|AG[ÊE]NCIA|AGENCIA|CONTA|VALOR|CPF|CNPJ)\b|$)",
    ]
    for p in padroes:
        m = re.search(p, txt, flags=re.I | re.S)
        if not m:
            continue
        nome = re.sub(r"\s+", " ", m.group(1)).strip()
        nome = re.sub(r"\b(AG|AGENCIA|AGÊNCIA|CONTA|VALOR|CPF|CNPJ)\b.*$", "", nome, flags=re.I).strip(" -|:")
        if nome:
            return nome
    return ""


def tipo_por_caminho(caminho_relativo: str) -> str | None:
    texto = remover_acentos(caminho_relativo).lower()
    if "holerite" in texto or "hollerite" in texto or "folha" in texto:
        return "holerite"
    if "comprovante" in texto or "recibo" in texto:
        return "comprovante"
    return None


def caminho_seguro_upload(nome_original: str) -> Path:
    partes = [secure_filename(p) for p in re.split(r"[\\/]+", nome_original) if p.strip()]
    partes = [p for p in partes if p and p not in {".", ".."}]
    if not partes:
        partes = [f"arquivo-{uuid.uuid4().hex}.pdf"]
    return Path(*partes)


def caminho_unico(caminho: Path) -> Path:
    if not caminho.exists():
        return caminho

    contador = 2
    while True:
        candidato = caminho.with_name(f"{caminho.stem}_{contador}{caminho.suffix}")
        if not candidato.exists():
            return candidato
        contador += 1


def salvar_uploads(arquivos, pasta_destino: Path) -> list[Path]:
    salvos = []
    pasta_destino.mkdir(parents=True, exist_ok=True)

    for arquivo in arquivos:
        if not arquivo or not arquivo.filename:
            continue
        if not arquivo.filename.lower().endswith(".pdf"):
            continue

        caminho_relativo = caminho_seguro_upload(arquivo.filename)
        destino = caminho_unico(pasta_destino / caminho_relativo)
        destino.parent.mkdir(parents=True, exist_ok=True)
        arquivo.save(destino)
        salvos.append(destino)

    return salvos


def salvar_grupo_upload(request_files, nomes_campos: list[str], pasta_destino: Path) -> list[Path]:
    salvos = []
    for campo in nomes_campos:
        salvos.extend(salvar_uploads(request_files.getlist(campo), pasta_destino))
    return salvos


def zipar_pasta(pasta_saida: Path, destino_zip: Path) -> None:
    with zipfile.ZipFile(destino_zip, "w", zipfile.ZIP_DEFLATED) as zipf:
        for arquivo in sorted(pasta_saida.glob("*.pdf")):
            zipf.write(arquivo, arquivo.name)


def listar_documentos(pasta_upload: Path) -> tuple[list[Documento], list[Documento], list[str]]:
    holerites = []
    comprovantes = []
    ignorados = []

    for caminho in pasta_upload.rglob("*.pdf"):
        relativo = caminho.relative_to(pasta_upload).as_posix()
        tipo = tipo_por_caminho(relativo)
        documento = Documento(limpar_nome(caminho.name), caminho.name, caminho)

        if not documento.nome_normalizado:
            ignorados.append(relativo)
        elif tipo == "holerite":
            holerites.append(documento)
        elif tipo == "comprovante":
            comprovantes.append(documento)
        else:
            ignorados.append(relativo)

    return holerites, comprovantes, ignorados


def unificar_documentos(pasta_upload: Path, cutoff: float = MIN_SIMILARIDADE_PADRAO) -> dict:
    pasta_saida = pasta_upload.parent / "DOCUMENTOS_UNIFICADOS"
    pasta_saida.mkdir(parents=True, exist_ok=True)

    holerites, comprovantes, ignorados = listar_documentos(pasta_upload)
    comprovantes_disponiveis = list(comprovantes)

    pares = []
    sem_comprovante = []
    erros = []

    for holerite in holerites:
        melhor_indice = None
        melhor_similaridade = 0.0

        for indice, comprovante_candidato in enumerate(comprovantes_disponiveis):
            similaridade_candidato = difflib.SequenceMatcher(
                None,
                holerite.nome_normalizado,
                comprovante_candidato.nome_normalizado,
            ).ratio()

            if similaridade_candidato >= cutoff and similaridade_candidato > melhor_similaridade:
                melhor_indice = indice
                melhor_similaridade = similaridade_candidato

        if melhor_indice is None:
            sem_comprovante.append(holerite.arquivo)
            continue

        comprovante = comprovantes_disponiveis[melhor_indice]
        nome_saida = secure_filename(f"{holerite.nome_normalizado}.pdf") or f"{uuid.uuid4().hex}.pdf"
        caminho_saida = caminho_unico(pasta_saida / nome_saida)

        try:
            merger = PdfMerger()
            merger.append(str(holerite.caminho))
            merger.append(str(comprovante.caminho))
            with caminho_saida.open("wb") as output_file:
                merger.write(output_file)
            merger.close()

            pares.append(
                {
                    "nome": holerite.nome_normalizado,
                    "holerite": holerite.arquivo,
                    "comprovante": comprovante.arquivo,
                    "similaridade": round(melhor_similaridade * 100, 1),
                    "aproximado": holerite.nome_normalizado != comprovante.nome_normalizado,
                }
            )
            comprovantes_disponiveis.pop(melhor_indice)
        except Exception as exc:
            erros.append(f"{holerite.arquivo}: {exc}")

    sem_holerite = [documento.arquivo for documento in comprovantes_disponiveis]
    zip_path = pasta_upload.parent / "documentos_unificados.zip"
    zipar_pasta(pasta_saida, zip_path)

    return {
        "pares": pares,
        "sem_comprovante": sem_comprovante,
        "sem_holerite": sem_holerite,
        "ignorados": ignorados,
        "erros": erros,
        "total_holerites": len(holerites),
        "total_comprovantes": len(comprovantes),
        "tem_zip": bool(pares) and zip_path.exists() and zip_path.stat().st_size > 0,
    }


def extrair_paginas_por_nomes(arquivos_pdf: list[Path], nomes: list[str], pasta_saida: Path) -> dict:
    pasta_saida.mkdir(parents=True, exist_ok=True)
    nomes_originais = [n.strip() for n in nomes if n.strip()]
    encontrados = set()
    extraidos = []
    erros = []
    paginas = []

    for pdf_path in arquivos_pdf:
        try:
            with pdf_path.open("rb") as file:
                reader = PdfReader(file)
                for idx, page in enumerate(reader.pages, start=1):
                    texto = page.extract_text() or ""
                    nome_extraido = extrair_nome_creditado_pagina(texto)
                    paginas.append((pdf_path, idx, nome_extraido, texto))
        except Exception as exc:
            erros.append(f"{pdf_path.name}: {exc}")

    # Etapa 1: calcula scores de todos x todos (maxima extracao).
    candidatos = []
    tops = {}
    for i, nome in enumerate(nomes_originais):
        local = []
        for pdf_path, idx, nome_pag, _ in paginas:
            if not nome_pag:
                continue
            sc = score_nome(nome, nome_pag)
            if sc > 0:
                local.append((sc, pdf_path, idx, nome_pag))
                if sc >= 68:
                    candidatos.append((sc, i, pdf_path, idx, nome_pag))
        local.sort(key=lambda x: x[0], reverse=True)
        tops[i] = local[:5]

    # Etapa 2: resolve duplicidade por maior score.
    candidatos.sort(key=lambda x: (-x[0], x[1], x[3]))
    usados = set()
    match = {}
    for sc, i, pdf_path, idx, nome_pag in candidatos:
        chave = (str(pdf_path), idx)
        if i in match or chave in usados:
            continue
        match[i] = (sc, pdf_path, idx, nome_pag)
        usados.add(chave)

    # Etapa 3: rescue para faltantes.
    for i, nome in enumerate(nomes_originais):
        if i in match:
            continue
        top = tops.get(i, [])
        if not top:
            continue
        sc, pdf_path, idx, nome_pag = top[0]
        if sc >= 68 or eh_abreviacao_final(nome, nome_pag):
            match[i] = (max(sc, 68.0), pdf_path, idx, nome_pag)

    for i, nome in enumerate(nomes_originais):
        if i not in match:
            continue
        sc, pdf_path, idx, nome_pag = match[i]
        if sc < 68:
            continue
        with pdf_path.open("rb") as f:
            reader = PdfReader(f)
            writer = PdfWriter()
            writer.add_page(reader.pages[idx - 1])
        nome_saida = secure_filename(nome) or uuid.uuid4().hex
        destino = caminho_unico(pasta_saida / f"{nome_saida}.pdf")
        with destino.open("wb") as out_file:
            writer.write(out_file)
        extraidos.append(destino.name)
        encontrados.add(nome)

    faltantes = [nome for nome in nomes_originais if nome not in encontrados]
    return {
        "total_nomes": len(nomes_originais),
        "encontrados": sorted(encontrados),
        "faltantes": faltantes,
        "extraidos": extraidos,
        "erros": erros,
    }


def extrair_colaboradores(texto: str) -> list[dict]:
    linhas = texto.splitlines()
    encontrados = []

    def proxima_linha_com_texto(indice_inicial: int, limite: int = 6) -> str:
        for deslocamento in range(1, limite + 1):
            idx = indice_inicial + deslocamento
            if idx >= len(linhas):
                break
            valor = re.sub(r"\s+", " ", linhas[idx]).strip()
            if valor:
                return valor
        return ""

    for i, linha_bruta in enumerate(linhas):
        linha = re.sub(r"\s+", " ", linha_bruta).strip()
        if normalizar_texto(linha) != "EMPR.:":
            continue

        linha_anterior = re.sub(r"\s+", " ", linhas[i - 1] if i > 0 else "").strip()
        match_anterior = re.match(r"^(\d+)\s+(.+)$", linha_anterior)
        if not match_anterior:
            continue

        matricula, nome = match_anterior.group(1).strip(), match_anterior.group(2).strip()
        funcao, cbo, situacao = "", "", ""

        for j in range(i, min(i + 60, len(linhas))):
            linha_j = re.sub(r"\s+", " ", linhas[j]).strip()
            norm = normalizar_texto(linha_j)
            if not linha_j:
                continue

            if not situacao and norm == "SITUACAO:":
                situacao = proxima_linha_com_texto(j, 4)
            if not situacao and ("TRABALHANDO" in norm or "DEMITIDO" in norm):
                situacao = linha_j

            if norm == "CARGO:":
                linha_cargo = proxima_linha_com_texto(j, 4)
                match_cargo = re.match(r"^(\d+)\s+(.+)$", linha_cargo)
                if match_cargo:
                    funcao = match_cargo.group(2).strip()

            if norm.startswith("C.B.O:"):
                na_linha = re.search(r"C\.B\.O\:\s*(\d{6})", linha_j, flags=re.IGNORECASE)
                if na_linha:
                    cbo = na_linha.group(1)
                else:
                    for k in range(1, 7):
                        candidato = re.sub(r"\s+", " ", linhas[j + k] if j + k < len(linhas) else "").strip()
                        achou = re.search(r"\b(\d{6})\b", candidato)
                        if achou:
                            cbo = achou.group(1)
                            break

            if "Empr.:" in linha_j and j > i + 1:
                break
            if cbo and situacao:
                break

        if not cbo:
            continue

        demitido = "DEMIT" in normalizar_texto(situacao)
        encontrados.append(
            {
                "matricula": matricula,
                "nome": nome,
                "funcao": funcao,
                "cbo": cbo,
                "situacao": situacao,
                "demitido": demitido,
            }
        )

    unicos = {}
    for item in encontrados:
        chave = "|".join(normalizar_texto(item[k]) for k in ["matricula", "nome", "funcao", "cbo"])
        unicos[chave] = item

    return sorted(unicos.values(), key=lambda x: normalizar_texto(x["nome"]))


def extrair_texto_pdf_com_fallback(pdf_bytes: bytes) -> tuple[str, str]:
    texto = ""

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        texto = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        texto = ""

    texto_limpo = re.sub(r"\s+", " ", texto).strip()
    if texto_limpo:
        return texto, "pypdf2"

    if fitz is None:
        raise RuntimeError("PyMuPDF nao encontrado. Instale com: pip install pymupdf")

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        partes = [pagina.get_text("text") for pagina in doc]
        doc.close()
    except Exception as exc:
        raise RuntimeError(f"Falha no fallback com PyMuPDF: {exc}") from exc

    texto_fallback = "\n".join(partes)
    texto_fallback_limpo = re.sub(r"\s+", " ", texto_fallback).strip()
    if not texto_fallback_limpo:
        raise RuntimeError("Nao foi possivel extrair texto do PDF com PyPDF2 nem PyMuPDF.")

    return texto_fallback, "pymupdf"


@app.get("/")
def index():
    return render_template("index.html", active_tab=request.args.get("tab", "unificar"), similaridade=MIN_SIMILARIDADE_PADRAO)


@app.post("/unificar")
def unificar():
    cutoff = float(request.form.get("similaridade", MIN_SIMILARIDADE_PADRAO))
    cutoff = max(0.5, min(cutoff, 1.0))

    job_id = uuid.uuid4().hex
    pasta_job = WORK_DIR / job_id
    pasta_upload = pasta_job / "entrada"

    if pasta_job.exists():
        shutil.rmtree(pasta_job)

    salvos_holerites = salvar_grupo_upload(
        request.files,
        ["holerites_pasta", "holerites_pdf"],
        pasta_upload / "holerites",
    )
    salvos_comprovantes = salvar_grupo_upload(
        request.files,
        ["comprovantes_pasta", "comprovantes_pdf"],
        pasta_upload / "comprovantes",
    )
    salvos = salvos_holerites + salvos_comprovantes

    if not salvos:
        return render_template("index.html", active_tab="unificar", erro="Envie ao menos um PDF.", similaridade=cutoff)

    resultado = unificar_documentos(pasta_upload, cutoff)
    return render_template("index.html", active_tab="unificar", resultado=resultado, job_id=job_id, similaridade=cutoff)


@app.post("/extrair-nomes")
def extrair_nomes():
    job_id = uuid.uuid4().hex
    pasta_job = WORK_DIR / job_id
    pasta_upload = pasta_job / "entrada"
    pasta_saida = pasta_job / "extraidos"

    arquivos = salvar_uploads(request.files.getlist("comprovantes_pdf"), pasta_upload)
    nomes = [linha.strip() for linha in request.form.get("nomes", "").splitlines() if linha.strip()]

    if not arquivos:
        return render_template("index.html", active_tab="extrair", erro_extrair="Envie ao menos um PDF de comprovante.", nomes_input=request.form.get("nomes", ""))
    if not nomes:
        return render_template("index.html", active_tab="extrair", erro_extrair="Informe ao menos um nome.")

    resultado_extrair = extrair_paginas_por_nomes(arquivos, nomes, pasta_saida)
    zip_path = pasta_job / "paginas_extraidas.zip"
    zipar_pasta(pasta_saida, zip_path)
    return render_template(
        "index.html",
        active_tab="extrair",
        resultado_extrair=resultado_extrair,
        job_id_extrair=job_id,
        tem_zip_extrair=zip_path.exists() and zip_path.stat().st_size > 0,
        nomes_input=request.form.get("nomes", ""),
    )


@app.post("/separar-folha")
def separar_folha():
    arquivo = request.files.get("folha_pdf")
    modo = request.form.get("mode", "nomes-cbo")

    if not arquivo or not arquivo.filename.lower().endswith(".pdf"):
        return render_template("index.html", active_tab="folha", erro_folha="Selecione um PDF da folha.", mode_folha=modo)

    try:
        pdf_bytes = arquivo.read()
        texto, origem_extracao = extrair_texto_pdf_com_fallback(pdf_bytes)
    except RuntimeError as exc:
        return render_template("index.html", active_tab="folha", erro_folha=str(exc), mode_folha=modo)
    except Exception:
        return render_template("index.html", active_tab="folha", erro_folha="Falha ao ler o PDF.", mode_folha=modo)

    todos = extrair_colaboradores(texto)

    # Mantem o comportamento original e evita falso negativo:
    # se PyPDF2 extrair texto "quebrado", tenta parsear novamente com PyMuPDF.
    if not todos and origem_extracao == "pypdf2" and fitz is not None:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            texto_fitz = "\n".join(pagina.get_text("text") for pagina in doc)
            doc.close()
            todos = extrair_colaboradores(texto_fitz)
            if todos:
                origem_extracao = "pymupdf"
        except Exception:
            pass

    if not todos:
        return render_template(
            "index.html",
            active_tab="folha",
            erro_folha="Nenhum colaborador localizado no PDF.",
            mode_folha=modo,
            origem_extracao=origem_extracao,
        )

    ativos = [i for i in todos if not i["demitido"]]
    demitidos = [i for i in todos if i["demitido"]]

    if modo == "separar-demitidos":
        resultado_folha = {
            "mode": modo,
            "total": len(todos),
            "ativos": len(ativos),
            "demitidos": len(demitidos),
            "listaAtivos": ativos,
            "listaDemitidos": demitidos,
        }
    else:
        resultado_folha = {"mode": "nomes-cbo", "total": len(todos), "colaboradores": todos}

    return render_template(
        "index.html",
        active_tab="folha",
        resultado_folha=resultado_folha,
        mode_folha=modo,
        origem_extracao=origem_extracao,
    )


@app.get("/download/<job_id>/<tipo>")
def download(job_id: str, tipo: str):
    pasta = WORK_DIR / secure_filename(job_id)
    mapa = {
        "unificados": pasta / "documentos_unificados.zip",
        "extraidos": pasta / "paginas_extraidas.zip",
    }
    caminho = mapa.get(tipo)
    if not caminho or not caminho.exists():
        return "Arquivo nao encontrado.", 404
    return send_file(caminho, as_attachment=True, download_name=caminho.name)


if __name__ == "__main__":
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    app.run(host="127.0.0.1", port=5000, debug=True)
