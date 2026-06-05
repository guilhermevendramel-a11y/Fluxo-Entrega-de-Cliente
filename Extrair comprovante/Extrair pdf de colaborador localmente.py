# -*- coding: utf-8 -*-
"""
Dependencias (instalar antes de rodar):
    pip install pymupdf pypdf rapidfuzz pandas openpyxl

Estrutura esperada (sera criada automaticamente se nao existir):
projeto_comprovantes/
├── entrada/
│   ├── comprovantes/
│   └── relacao/
├── saida/
│   ├── extraidos/
│   ├── relatorios/
│   └── database/
└── logs/
"""

from __future__ import annotations

import csv
import logging
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fitz
import pandas as pd
from pypdf import PdfReader

try:
    from rapidfuzz import fuzz
except Exception:
    fuzz = None
    from difflib import SequenceMatcher


# ============================================================
# CONFIGURACOES
# ============================================================

VERSAO_SCRIPT = "MAX_EXTRACAO_LOCAL_V6"
PERMITIR_DUPLICIDADE = False
MODO_MAXIMA_EXTRACAO = True
MIN_SCORE_AUTOMATICO = 75.0
MIN_SCORE_ALTA_CONFIANCA = 90.0
MIN_SCORE_RESCUE = 70.0
MARGEM_MINIMA_RESCUE = 6.0
SCORE_OK = 88.0
SCORE_ABREVIACAO = 78.0
SCORE_CONFERIR = 68.0

PALAVRAS_LIGACAO = {"DA", "DE", "DO", "DAS", "DOS", "E"}

EQUIVALENCIAS = {
    "LUIS": "LUIZ",
    "LUIZ": "LUIS",
    "FELIPE": "FILIPE",
    "FILIPE": "FELIPE",
    "FILIPI": "FILIPE",
    "SOUSA": "SOUZA",
    "SOUZA": "SOUSA",
}

STOP_PATTERNS = [
    r"^AG\b",
    r"^AGEN[CC]IA\b",
    r"^AGENCIA\b",
    r"^AGENCIA\b",
    r"^CONTA\b",
    r"^CONTA\s+CORRENTE\b",
    r"^VALOR\b",
    r"^CPF\b",
    r"^CNPJ\b",
]


@dataclass
class Comprovante:
    arquivo: str
    caminho_pdf: str
    pagina: int
    nome_comprovante: str
    nome_normalizado: str
    valor: str
    data_pagamento: str
    banco: str
    texto_primeiras_linhas: str
    metodo_extracao_nome: str
    nome_vazio_sim_nao: str
    origem_nome: str


# ============================================================
# LOG
# ============================================================

def configurar_logger(caminho_log: Path) -> logging.Logger:
    logger = logging.getLogger("extracao_comprovantes")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S")

    fh = logging.FileHandler(caminho_log, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    return logger


# ============================================================
# NORMALIZACAO E COMPARACAO
# ============================================================

def normalizar(texto: str) -> str:
    texto = texto or ""
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = texto.upper()
    texto = re.sub(r"[^A-Z0-9 ]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def normalizar_token(token: str) -> str:
    token = normalizar(token)
    return EQUIVALENCIAS.get(token, token)


def tokens_nome(texto: str, remover_ligacao: bool = True) -> List[str]:
    tokens = normalizar(texto).split()
    if remover_ligacao:
        tokens = [t for t in tokens if t not in PALAVRAS_LIGACAO]
    return [normalizar_token(t) for t in tokens]


def texto_compacto(texto: str) -> str:
    return "".join(tokens_nome(texto, remover_ligacao=True))


def similaridade(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if fuzz:
        return float(fuzz.ratio(a, b)) / 100.0
    return SequenceMatcher(None, a, b).ratio()


def token_parece_igual(token_oficial: str, token_banco: str) -> bool:
    a = normalizar_token(token_oficial)
    b = normalizar_token(token_banco)

    if a == b:
        return True

    if len(b) == 1 and a.startswith(b):
        return True

    if len(b) >= 2 and a.startswith(b):
        return True
    if len(a) >= 3 and b.startswith(a):
        return True

    return similaridade(a, b) >= 0.80


def contar_tokens_em_ordem(tokens_oficial: List[str], tokens_banco: List[str]) -> int:
    pos = 0
    encontrados = 0
    for token_banco in tokens_banco:
        while pos < len(tokens_oficial):
            if token_parece_igual(tokens_oficial[pos], token_banco):
                encontrados += 1
                pos += 1
                break
            pos += 1
    return encontrados


def eh_abreviacao_final(nome_oficial: str, nome_banco: str) -> bool:
    no = normalizar(nome_oficial)
    nb = normalizar(nome_banco)
    if not no or not nb:
        return False
    if no.startswith(nb) and len(no) > len(nb):
        return True
    to = tokens_nome(nome_oficial)
    tb = tokens_nome(nome_banco)
    if len(tb) <= len(to) and tb and to:
        if all(token_parece_igual(to[i], tb[i]) for i in range(min(len(tb), len(to)))) and len(tb) < len(to):
            return True
    return False


def score_nome(nome_oficial: str, nome_banco: str) -> float:
    no = normalizar(nome_oficial)
    nb = normalizar(nome_banco)
    if not no or not nb:
        return 0.0

    if no == nb:
        return 100.0

    to = tokens_nome(nome_oficial)
    tb = tokens_nome(nome_banco)
    if not to or not tb:
        return 0.0

    compacto_oficial = texto_compacto(nome_oficial)
    compacto_banco = texto_compacto(nome_banco)
    sim_compacto = similaridade(compacto_oficial, compacto_banco)

    primeiro_ok = 1.0 if token_parece_igual(to[0], tb[0]) else 0.0
    primeiro_inicial_ok = 1.0 if to[0][:1] == tb[0][:1] else 0.0

    if no.startswith(nb) or nb.startswith(no):
        return 99.0

    if sim_compacto >= 0.965:
        return 97.0

    encontrados = contar_tokens_em_ordem(to, tb)
    cobertura_banco = encontrados / len(tb)
    cobertura_oficial = encontrados / len(to)
    sim_frase = similaridade(no, nb)
    ultimo_ok = 1.0 if token_parece_igual(to[-1], tb[-1]) else 0.0

    score = 100 * (
        0.38 * cobertura_banco
        + 0.27 * cobertura_oficial
        + 0.17 * sim_frase
        + 0.12 * sim_compacto
        + 0.04 * primeiro_ok
        + 0.02 * ultimo_ok
    )

    if primeiro_ok and ultimo_ok:
        score += 0.5

    if len(tb) <= 2 and len(to) >= 4 and cobertura_oficial < 0.70:
        score -= 28

    if primeiro_ok == 0:
        if primeiro_inicial_ok and sim_compacto >= 0.90:
            score -= 8
        elif sim_compacto >= 0.94 and cobertura_oficial >= 0.75:
            score -= 12
        else:
            score -= 35

    return round(max(0.0, min(score, 100.0)), 2)


# ============================================================
# LEITURA DE RELACAO
# ============================================================

def carregar_relacao(caminho: Path) -> List[str]:
    ext = caminho.suffix.lower()

    if ext == ".txt":
        return [linha.strip() for linha in caminho.read_text(encoding="utf-8", errors="ignore").splitlines() if linha.strip()]

    if ext == ".csv":
        df = pd.read_csv(caminho, dtype=str, sep=None, engine="python")
    elif ext in {".xlsx", ".xls"}:
        df = pd.read_excel(caminho, dtype=str)
    else:
        return []

    df = df.fillna("")
    colunas = list(df.columns)
    coluna_nome = None

    for c in colunas:
        if "nome" in normalizar(str(c)).lower():
            coluna_nome = c
            break

    if coluna_nome is None and colunas:
        coluna_nome = colunas[0]

    if coluna_nome is None:
        return []

    nomes = []
    for v in df[coluna_nome].astype(str).tolist():
        v = v.strip()
        if v and v.lower() != "nan":
            nomes.append(v)
    return nomes


def encontrar_relacao(entrada_relacao: Path) -> Optional[Path]:
    arquivos = []
    for ext in ("*.txt", "*.csv", "*.xlsx", "*.xls"):
        arquivos.extend(entrada_relacao.glob(ext))
    if not arquivos:
        return None
    return sorted(arquivos, key=lambda p: p.stat().st_mtime, reverse=True)[0]


# ============================================================
# EXTRACAO DO NOME (3 CAMADAS)
# ============================================================

def primeira_linha(texto: str) -> str:
    for linha in (texto or "").splitlines():
        linha = linha.strip()
        if linha:
            return linha
    return ""


def primeira_n_linhas(texto: str, n: int = 20) -> str:
    linhas = [l.strip() for l in (texto or "").splitlines() if l.strip()]
    return " | ".join(linhas[:n])


def _eh_linha_stop(linha: str) -> bool:
    ln = normalizar(linha)
    for p in STOP_PATTERNS:
        if re.match(p, ln):
            return True
    return False


def limpar_nome_extraido(nome: str) -> str:
    nome = nome or ""
    nome = re.sub(r"\s+", " ", nome).strip()

    padroes_corte = [
        r"\bAG\b.*$",
        r"\bAG[ÊE]NCIA\b.*$",
        r"\bAGENCIA\b.*$",
        r"\bCONTA\s+CORRENTE\b.*$",
        r"\bCONTA\b.*$",
        r"\bVALOR\b.*$",
        r"\bCPF\b.*$",
        r"\bCNPJ\b.*$",
    ]

    limpo = nome
    for p in padroes_corte:
        limpo = re.sub(p, "", limpo, flags=re.I).strip()

    limpo = re.sub(r"\s+", " ", limpo).strip(" -|:")
    return limpo


def extrair_nome_creditado_regex_flexivel(texto: str) -> str:
    if not texto:
        return ""

    txt = texto.replace("\r", "\n")

    bloco_match = re.search(r"DADOS\s+DA\s+CONTA\s+CREDITADA\s*:?(.+)", txt, flags=re.I | re.S)
    if bloco_match:
        bloco = bloco_match.group(1)
    else:
        bloco = txt

    m = re.search(r"NOME\s*:\s*(.+?)(?:\n\s*(?:AG\b|AG[ÊE]NCIA\b|AGENCIA\b|CONTA\b|CONTA\s+CORRENTE\b|VALOR\b|CPF\b|CNPJ\b)|$)", bloco, flags=re.I | re.S)
    if not m:
        return ""

    nome = re.sub(r"\s+", " ", m.group(1)).strip()
    return limpar_nome_extraido(nome)


def extrair_nome_creditado_linhas(texto: str) -> str:
    linhas = [l.rstrip() for l in (texto or "").replace("\r", "\n").split("\n")]

    for i, linha in enumerate(linhas):
        ln = linha.strip()
        if not ln:
            continue

        if re.match(r"^NOME\s*:\s*", ln, flags=re.I):
            resto = re.sub(r"^NOME\s*:\s*", "", ln, flags=re.I).strip()
            if resto:
                return limpar_nome_extraido(resto)

            partes = []
            for j in range(i + 1, min(i + 8, len(linhas))):
                lj = linhas[j].strip()
                if not lj:
                    continue
                if _eh_linha_stop(lj):
                    break
                partes.append(lj)
            if partes:
                return limpar_nome_extraido(" ".join(partes))

    return ""


def extrair_nome_creditado_blocos(page: fitz.Page) -> str:
    try:
        d = page.get_text("dict")
    except Exception:
        return ""

    linhas = []
    for b in d.get("blocks", []):
        if b.get("type", 0) != 0:
            continue
        for ln in b.get("lines", []):
            spans = ln.get("spans", [])
            txt = " ".join((s.get("text", "") or "").strip() for s in spans if (s.get("text", "") or "").strip())
            if txt:
                y = ln.get("bbox", [0, 0, 0, 0])[1] if ln.get("bbox") else 0
                linhas.append((y, txt))

    if not linhas:
        return ""

    linhas.sort(key=lambda x: x[0])
    somente_texto = [t for _, t in linhas]

    for i, t in enumerate(somente_texto):
        if re.search(r"\bNOME\b\s*:", t, flags=re.I):
            resto = re.sub(r"^.*?\bNOME\b\s*:\s*", "", t, flags=re.I).strip()
            if resto:
                return limpar_nome_extraido(resto)

            partes = []
            for j in range(i + 1, min(i + 8, len(somente_texto))):
                lj = somente_texto[j].strip()
                if not lj:
                    continue
                if _eh_linha_stop(lj):
                    break
                partes.append(lj)
            if partes:
                return limpar_nome_extraido(" ".join(partes))

    return ""


def extrair_nome_creditado(texto: str, page: fitz.Page) -> Tuple[str, str, str]:
    # CAMADA 1 - regex flexivel
    nome = extrair_nome_creditado_regex_flexivel(texto)
    if nome:
        return nome, "regex_flexivel", "extraido_por_regex"

    # CAMADA 2 - leitura por linhas
    nome = extrair_nome_creditado_linhas(texto)
    if nome:
        return nome, "leitura_linhas", "extraido_por_linhas"

    # CAMADA 3 - fallback por blocos
    nome = extrair_nome_creditado_blocos(page)
    if nome:
        return nome, "fallback_blocos_dict", "extraido_por_blocos"

    return "", "nao_encontrado", "campo_nome_nao_localizado"


def extrair_valor(texto: str) -> str:
    m = re.search(r"Valor\s*[:\-]?\s*R\$\s*([\d\.]+,\d{2})", texto or "", flags=re.I)
    return m.group(1) if m else ""


def extrair_data_pagamento(texto: str) -> str:
    m = re.search(r"(?:Transfer[êe]ncia|Pagamento|Opera[cç][aã]o).*?em\s*(\d{2}/\d{2}/\d{4})", texto or "", flags=re.I | re.S)
    return m.group(1) if m else ""


def carregar_database_apoio(caminhos_csv: List[Path], logger: logging.Logger) -> Dict[Tuple[str, int], dict]:
    apoio: Dict[Tuple[str, int], dict] = {}
    for caminho in caminhos_csv:
        if not caminho.exists():
            continue
        try:
            df = pd.read_csv(caminho, sep=";", dtype=str, encoding="utf-8-sig")
            cols = {c.lower(): c for c in df.columns}
            if "arquivo" not in cols or "pagina" not in cols:
                logger.warning("Database apoio ignorado (sem colunas arquivo/pagina): %s", caminho)
                continue
            col_nome = cols.get("nome_comprovante") or cols.get("nome_no_comprovante")
            if not col_nome:
                logger.warning("Database apoio ignorado (sem coluna de nome): %s", caminho)
                continue

            for _, row in df.iterrows():
                arquivo = str(row[cols["arquivo"]]).strip()
                pagina_raw = str(row[cols["pagina"]]).strip()
                nome = str(row[col_nome]).strip()
                if not arquivo or not pagina_raw:
                    continue
                try:
                    pagina = int(float(pagina_raw))
                except Exception:
                    continue
                if not nome:
                    continue
                apoio[(arquivo, pagina)] = {
                    "nome": nome,
                    "valor": str(row[cols["valor"]]).strip() if "valor" in cols else "",
                    "data_pagamento": str(row[cols["data_transferencia"]]).strip() if "data_transferencia" in cols else str(row[cols["data_pagamento"]]).strip() if "data_pagamento" in cols else "",
                }
            logger.info("Database de apoio carregado: %s | registros uteis: %s", caminho, len(apoio))
        except Exception as e:
            logger.error("Erro ao carregar database de apoio %s: %s", caminho, e)
    return apoio


# ============================================================
# EXTRACAO DOS COMPROVANTES
# ============================================================

def listar_pdfs(pasta: Path) -> List[Path]:
    return sorted([p for p in pasta.glob("*.pdf") if p.is_file()])


def montar_database_comprovantes(
    pasta_pdfs: Path,
    logger: logging.Logger,
    logs_paginas_sem_nome_dir: Path,
    database_apoio: Dict[Tuple[str, int], dict],
) -> Tuple[List[Comprovante], Dict[str, fitz.Document], List[dict], int, int, int]:
    registros: List[Comprovante] = []
    documentos: Dict[str, fitz.Document] = {}
    paginas_sem_nome: List[dict] = []

    total_paginas = 0
    total_nomes_extraidos = 0
    total_nomes_pypdf = 0
    total_nomes_apoio = 0

    pdfs = listar_pdfs(pasta_pdfs)
    logger.info("Arquivos PDF encontrados: %s", ", ".join(p.name for p in pdfs) if pdfs else "nenhum")

    contador_sem_nome = 0

    for pdf_path in pdfs:
        try:
            doc = fitz.open(str(pdf_path))
            documentos[str(pdf_path)] = doc
            logger.info("Lendo PDF: %s | paginas: %s", pdf_path.name, len(doc))
            reader_pypdf = PdfReader(str(pdf_path))
        except Exception as e:
            logger.error("Erro ao abrir PDF %s: %s", pdf_path.name, e)
            continue

        for i in range(1, len(doc) + 1):
            page = doc[i - 1]
            total_paginas += 1

            try:
                texto = page.get_text("text") or ""
                nome, metodo_nome, motivo_nome = extrair_nome_creditado(texto, page)
                nome = limpar_nome_extraido(nome)
                origem_nome = "fitz"

                if not nome:
                    try:
                        texto_pypdf = reader_pypdf.pages[i - 1].extract_text() or ""
                        nome_py, metodo_py, motivo_py = extrair_nome_creditado(texto_pypdf, page)
                        nome_py = limpar_nome_extraido(nome_py)
                        if nome_py:
                            nome = nome_py
                            metodo_nome = f"{metodo_py}_pypdf"
                            motivo_nome = "extraido_por_pypdf"
                            origem_nome = "pypdf"
                            total_nomes_pypdf += 1
                    except Exception:
                        pass

                if not nome:
                    chave_apoio = (pdf_path.name, i)
                    if chave_apoio in database_apoio:
                        apoio = database_apoio[chave_apoio]
                        nome = limpar_nome_extraido(apoio["nome"])
                        if nome:
                            metodo_nome = "database_apoio"
                            motivo_nome = "preenchido_por_database_apoio"
                            origem_nome = "database_apoio"
                            total_nomes_apoio += 1

                primeiras_linhas = primeira_n_linhas(texto, n=20)
                nome_vazio = "SIM" if not nome else "NAO"

                if nome:
                    total_nomes_extraidos += 1
                else:
                    contador_sem_nome += 1
                    nome_log = f"pagina_{contador_sem_nome:04d}_{normalizar(pdf_path.stem)[:40]}_p{i:04d}.txt"
                    destino_log = logs_paginas_sem_nome_dir / nome_log
                    destino_log.write_text(texto or "", encoding="utf-8")

                    paginas_sem_nome.append(
                        {
                            "arquivo": pdf_path.name,
                            "pagina": i,
                            "primeiras_20_linhas_texto": primeiras_linhas,
                            "motivo": motivo_nome,
                        }
                    )

                logger.info(
                    "Pagina %s de %s | nome extraido: %s | metodo: %s",
                    i,
                    pdf_path.name,
                    nome if nome else "(vazio)",
                    metodo_nome,
                )

                registros.append(
                    Comprovante(
                        arquivo=pdf_path.name,
                        caminho_pdf=str(pdf_path),
                        pagina=i,
                        nome_comprovante=nome,
                        nome_normalizado=normalizar(nome),
                        valor=extrair_valor(texto),
                        data_pagamento=extrair_data_pagamento(texto),
                        banco=primeira_linha(texto),
                        texto_primeiras_linhas=primeiras_linhas,
                        metodo_extracao_nome=metodo_nome,
                        nome_vazio_sim_nao=nome_vazio,
                        origem_nome=origem_nome,
                    )
                )
            except Exception as e:
                logger.error("Erro na pagina %s de %s: %s", i, pdf_path.name, e)

    total_paginas_sem_nome = total_paginas - total_nomes_extraidos
    logger.info("Nomes via fallback pypdf: %s | nomes via database apoio: %s", total_nomes_pypdf, total_nomes_apoio)
    return registros, documentos, paginas_sem_nome, total_paginas, total_nomes_extraidos, total_paginas_sem_nome


# ============================================================
# RELATORIOS E EXTRACAO
# ============================================================

def nome_arquivo_seguro(nome: str) -> str:
    nome = normalizar(nome).title()
    nome = re.sub(r"[^A-Za-z0-9 _.-]+", "", nome)
    nome = re.sub(r"\s+", " ", nome).strip()
    return (nome[:120] or "Sem_Nome").rstrip(" .")


def salvar_csv(caminho: Path, linhas: List[dict], colunas: List[str]) -> None:
    with caminho.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=colunas, delimiter=";")
        w.writeheader()
        for l in linhas:
            w.writerow(l)


def indexar_por_primeiro_nome(registros: List[Comprovante]) -> Dict[str, List[Comprovante]]:
    indice = defaultdict(list)
    for r in registros:
        t = tokens_nome(r.nome_comprovante)
        if t:
            indice[t[0]].append(r)
    return indice


def candidatos_por_primeiro_nome(nome: str, registros: List[Comprovante], indice: Dict[str, List[Comprovante]]) -> List[Comprovante]:
    t = tokens_nome(nome)
    if not t:
        return registros
    primeiro = t[0]
    chaves = {primeiro, EQUIVALENCIAS.get(primeiro, primeiro)}
    candidatos = []
    for c in chaves:
        candidatos.extend(indice.get(c, []))
    if not candidatos:
        return registros
    unicos = {(r.arquivo, r.pagina): r for r in candidatos}
    return list(unicos.values())


def extrair_pagina_pdf(registro: Comprovante, documentos_abertos: Dict[str, fitz.Document], destino: Path) -> None:
    doc_origem = documentos_abertos[registro.caminho_pdf]
    novo = fitz.open()
    novo.insert_pdf(doc_origem, from_page=registro.pagina - 1, to_page=registro.pagina - 1)
    novo.save(str(destino))
    novo.close()


def criar_estrutura(base_dir: Path) -> Dict[str, Path]:
    caminhos = {
        "entrada": base_dir / "entrada",
        "entrada_comprovantes": base_dir / "entrada" / "comprovantes",
        "entrada_relacao": base_dir / "entrada" / "relacao",
        "entrada_database": base_dir / "entrada" / "database",
        "saida": base_dir / "saida",
        "saida_extraidos": base_dir / "saida" / "extraidos",
        "saida_relatorios": base_dir / "saida" / "relatorios",
        "saida_database": base_dir / "saida" / "database",
        "logs": base_dir / "logs",
        "logs_paginas_sem_nome": base_dir / "logs" / "paginas_sem_nome",
    }
    for p in caminhos.values():
        p.mkdir(parents=True, exist_ok=True)
    return caminhos


def processar(base_dir: Path) -> None:
    dirs = criar_estrutura(base_dir)
    logger = configurar_logger(dirs["logs"] / "log_execucao.txt")

    print(f"VERSAO_SCRIPT: {VERSAO_SCRIPT}")
    logger.info("Inicio da execucao")
    logger.info("VERSAO_SCRIPT: %s", VERSAO_SCRIPT)
    logger.info("Base do projeto: %s", base_dir)

    pdfs = listar_pdfs(dirs["entrada_comprovantes"])
    if not pdfs:
        print("Nenhum PDF encontrado em entrada/comprovantes/")
        logger.warning("Nenhum PDF encontrado em entrada/comprovantes/")
        return

    arquivo_relacao = encontrar_relacao(dirs["entrada_relacao"])
    if not arquivo_relacao:
        print("Nenhuma relação de colaboradores encontrada em entrada/relacao/")
        logger.warning("Nenhuma relacao de colaboradores encontrada em entrada/relacao/")
        return

    nomes_relacao = carregar_relacao(arquivo_relacao)
    nomes_relacao = [n for n in nomes_relacao if n.strip()]
    if not nomes_relacao:
        print("Nenhuma relação de colaboradores encontrada em entrada/relacao/")
        logger.warning("Arquivo de relacao sem nomes validos: %s", arquivo_relacao)
        return

    logger.info("Relacao carregada: %s | total nomes: %s", arquivo_relacao.name, len(nomes_relacao))

    bancos_apoio = [
        base_dir / "database_comprovantes_relacao_colaboradores.csv",
        base_dir / "database_comprovantes.csv",
        dirs["entrada_database"] / "database_comprovantes.csv",
        dirs["entrada_database"] / "database_comprovantes_relacao_colaboradores.csv",
        Path(r"c:\Users\Notebook\Downloads\database_comprovantes_relacao_colaboradores.csv"),
    ]
    database_apoio = carregar_database_apoio(bancos_apoio, logger)

    registros, documentos_abertos, paginas_sem_nome, total_paginas, total_nomes_extraidos, total_paginas_sem_nome = montar_database_comprovantes(
        dirs["entrada_comprovantes"],
        logger,
        dirs["logs_paginas_sem_nome"],
        database_apoio,
    )
    logger.info("Total de paginas processadas no database: %s", len(registros))

    database_csv = dirs["saida_database"] / "database_comprovantes.csv"
    salvar_csv(
        database_csv,
        [
            {
                "arquivo": r.arquivo,
                "pagina": r.pagina,
                "nome_comprovante": r.nome_comprovante,
                "nome_normalizado": r.nome_normalizado,
                "valor": r.valor,
                "data_pagamento": r.data_pagamento,
                "banco": r.banco,
                "texto_primeiras_linhas": r.texto_primeiras_linhas,
                "nome_extraido": r.nome_comprovante,
                "metodo_extracao_nome": r.metodo_extracao_nome,
                "nome_vazio_sim_nao": r.nome_vazio_sim_nao,
                "origem_nome": r.origem_nome,
            }
            for r in registros
        ],
        [
            "arquivo",
            "pagina",
            "nome_comprovante",
            "nome_normalizado",
            "valor",
            "data_pagamento",
            "banco",
            "texto_primeiras_linhas",
            "nome_extraido",
            "metodo_extracao_nome",
            "nome_vazio_sim_nao",
            "origem_nome",
        ],
    )

    paginas_sem_nome_csv = dirs["saida_relatorios"] / "paginas_sem_nome_extraido.csv"
    salvar_csv(
        paginas_sem_nome_csv,
        paginas_sem_nome,
        ["arquivo", "pagina", "primeiras_20_linhas_texto", "motivo"],
    )

    indice = indexar_por_primeiro_nome(registros)
    tops_por_nome: Dict[int, List[Tuple[float, Comprovante]]] = {}
    todos_candidatos: List[Tuple[float, int, Comprovante]] = []

    for idx, nome in enumerate(nomes_relacao):
        candidatos = []
        base_candidatos = registros if MODO_MAXIMA_EXTRACAO else candidatos_por_primeiro_nome(nome, registros, indice)
        for r in base_candidatos:
            if not r.nome_comprovante:
                continue
            sc = score_nome(nome, r.nome_comprovante)
            if sc > 0:
                candidatos.append((sc, r))

        candidatos.sort(key=lambda x: x[0], reverse=True)
        tops_por_nome[idx] = candidatos[:8]

        for sc, r in candidatos:
            if sc >= SCORE_CONFERIR:
                todos_candidatos.append((sc, idx, r))

    todos_candidatos.sort(key=lambda x: (-x[0], x[1], x[2].pagina))

    atribuido_por_nome: Dict[int, Tuple[Comprovante, float]] = {}
    paginas_usadas = set()

    for sc, idx, r in todos_candidatos:
        chave = (r.arquivo, r.pagina)
        if idx in atribuido_por_nome:
            continue
        if not PERMITIR_DUPLICIDADE and chave in paginas_usadas:
            continue
        atribuido_por_nome[idx] = (r, sc)
        paginas_usadas.add(chave)

    for idx, tops in tops_por_nome.items():
        if idx in atribuido_por_nome or not tops:
            continue
        sc1, r1 = tops[0]
        sc2 = tops[1][0] if len(tops) > 1 else 0.0
        margem = sc1 - sc2
        chave = (r1.arquivo, r1.pagina)
        if sc1 < MIN_SCORE_RESCUE or margem < MARGEM_MINIMA_RESCUE:
            continue
        if not PERMITIR_DUPLICIDADE and chave in paginas_usadas:
            continue
        atribuido_por_nome[idx] = (r1, sc1)
        paginas_usadas.add(chave)

    colunas_relatorio = [
        "nome_relacao",
        "status",
        "nome_encontrado_no_comprovante",
        "arquivo_origem",
        "pagina",
        "valor",
        "data_pagamento",
        "score",
        "motivo",
        "candidatos_proximos",
    ]

    relatorio_linhas: List[dict] = []
    encontrados_linhas: List[dict] = []
    faltantes_linhas: List[dict] = []
    conferir_linhas: List[dict] = []
    contagem = Counter()
    nome_saida_usado = Counter()

    for idx, nome in enumerate(nomes_relacao):
        tops = tops_por_nome.get(idx, [])
        candidatos_txt = " | ".join([f"{sc:.2f}% p.{r.pagina} {r.nome_comprovante}" for sc, r in tops[:5]])

        status = "NAO ENCONTRADO"
        motivo = "Nenhum candidato seguro"
        registro = None
        score = 0.0

        if idx in atribuido_por_nome:
            registro, score = atribuido_por_nome[idx]
            if score >= SCORE_OK:
                status = "OK"
                motivo = "Correspondencia segura"
            elif score >= SCORE_ABREVIACAO:
                status = "OK - CONFERIR ABREVIACAO"
                motivo = "Nome no comprovante parece abreviado/truncado"
            elif score >= SCORE_CONFERIR:
                status = "CONFERIR MANUALMENTE"
                motivo = "Score intermediario"
            else:
                status = "NAO ENCONTRADO"
                motivo = "Score abaixo do minimo"

            # Se for truncamento forte no final, sobe para abreviacao.
            if eh_abreviacao_final(nome, registro.nome_comprovante) and score >= SCORE_CONFERIR:
                status = "OK - CONFERIR ABREVIACAO"
                motivo = "Truncamento de final reconhecido"

            # Nome muito curto no comprovante exige cautela.
            if len(tokens_nome(registro.nome_comprovante)) <= 2 and len(tokens_nome(nome)) >= 4 and status == "OK":
                status = "CONFERIR MANUALMENTE"
                motivo = "Nome curto no comprovante exige validacao manual"

            if len(tops) > 1:
                score2, r2 = tops[1]
                if score2 >= SCORE_ABREVIACAO and abs(score - score2) <= 3 and (r2.arquivo, r2.pagina) != (registro.arquivo, registro.pagina):
                    status = "OK - CONFERIR AMBIGUIDADE"
                    motivo = "Mais de um candidato forte com score proximo"

            logger.info("Melhor correspondencia | relacao: %s | comprovante: %s | score: %.2f", nome, registro.nome_comprovante, score)

            base_nome = nome_arquivo_seguro(nome)
            nome_saida_usado[base_nome] += 1
            sufixo = "" if nome_saida_usado[base_nome] == 1 else f" ({nome_saida_usado[base_nome]})"
            destino = dirs["saida_extraidos"] / f"{base_nome}{sufixo}.pdf"

            try:
                extrair_pagina_pdf(registro, documentos_abertos, destino)
            except Exception as e:
                status = "NAO ENCONTRADO"
                motivo = f"Erro ao extrair PDF: {e}"
                logger.error("Erro ao extrair pagina %s do arquivo %s: %s", registro.pagina, registro.arquivo, e)
                registro = None
                score = 0.0
        else:
            if tops:
                score_top, reg_top = tops[0]
                chave = (reg_top.arquivo, reg_top.pagina)
                if not PERMITIR_DUPLICIDADE and chave in paginas_usadas and score_top >= SCORE_CONFERIR:
                    status = "DUPLICADO"
                    motivo = "Pagina de comprovante ja utilizada por outro colaborador"
                    registro = reg_top
                    score = score_top
                else:
                    logger.info("Sem correspondencia segura | relacao: %s | melhor score: %.2f", nome, score_top)
            else:
                logger.info("Sem candidatos | relacao: %s", nome)

        linha = {
            "nome_relacao": nome,
            "status": status,
            "nome_encontrado_no_comprovante": registro.nome_comprovante if registro else "",
            "arquivo_origem": registro.arquivo if registro else "",
            "pagina": registro.pagina if registro else "",
            "valor": registro.valor if registro else "",
            "data_pagamento": registro.data_pagamento if registro else "",
            "score": round(score, 2),
            "motivo": motivo,
            "candidatos_proximos": candidatos_txt,
        }

        relatorio_linhas.append(linha)
        contagem[status] += 1

        if status.startswith("OK"):
            encontrados_linhas.append(linha)
        if status == "NAO ENCONTRADO":
            faltantes_linhas.append(linha)
        if "CONFERIR" in status or status == "DUPLICADO":
            conferir_linhas.append(linha)

    relatorio_csv = dirs["saida_relatorios"] / "relatorio_conferencia_comprovantes.csv"
    faltantes_csv = dirs["saida_relatorios"] / "faltantes.csv"
    encontrados_csv = dirs["saida_relatorios"] / "encontrados.csv"
    conferir_csv = dirs["saida_relatorios"] / "conferir_manualmente.csv"

    salvar_csv(relatorio_csv, relatorio_linhas, colunas_relatorio)
    salvar_csv(faltantes_csv, faltantes_linhas, colunas_relatorio)
    salvar_csv(encontrados_csv, encontrados_linhas, colunas_relatorio)
    salvar_csv(conferir_csv, conferir_linhas, colunas_relatorio)

    total_colaboradores = len(nomes_relacao)
    total_encontrados = len(encontrados_linhas)
    total_faltantes = len(faltantes_linhas)
    total_duplicados = contagem.get("DUPLICADO", 0)
    total_conferir = len(conferir_linhas)

    if total_paginas == 678 and total_nomes_extraidos < 650:
        alerta = "ATENÇÃO: muitos comprovantes ficaram sem nome. O problema está na extração do campo Nome, não na comparação dos colaboradores."
        print(alerta)
        logger.warning(alerta)

    print("=" * 72)
    print("RESUMO")
    print("=" * 72)
    print(f"Total de paginas processadas: {total_paginas}")
    print(f"Total de nomes extraidos: {total_nomes_extraidos}")
    print(f"Total de paginas sem nome extraido: {total_paginas_sem_nome}")
    print(f"Total de colaboradores encontrados: {total_encontrados}")
    print(f"Total de colaboradores faltantes: {total_faltantes}")
    print(f"Conferir manualmente: {total_conferir}")
    print(f"Duplicados: {total_duplicados}")
    print("Relatorios gerados em: saida/relatorios/")
    print(f"- {relatorio_csv}")
    print(f"- {faltantes_csv}")
    print(f"- {encontrados_csv}")
    print(f"- {conferir_csv}")
    print(f"- {paginas_sem_nome_csv}")
    print(f"Database: {database_csv}")
    print(f"Log: {dirs['logs'] / 'log_execucao.txt'}")
    print("=" * 72)

    for doc in documentos_abertos.values():
        try:
            doc.close()
        except Exception:
            pass

    logger.info("Fim da execucao")


if __name__ == "__main__":
    BASE_DIR = Path(__file__).resolve().parent
    processar(BASE_DIR)
