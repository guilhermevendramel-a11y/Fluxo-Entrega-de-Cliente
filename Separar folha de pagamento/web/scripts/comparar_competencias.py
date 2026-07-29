# -*- coding: utf-8 -*-
"""
Compara duas folhas de pagamento e aponta quem estava na competencia anterior
mas nao aparece na competencia atual.

Dependencies:
  pip install pymupdf pandas openpyxl rapidfuzz
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

import fitz
import pandas as pd

try:
    from rapidfuzz import fuzz
except Exception:
    fuzz = None
    from difflib import SequenceMatcher


VERSAO_SCRIPT = "COMPARAR_COMPETENCIAS_V1"
MIN_SCORE_PAREAMENTO = 78.0
SCORE_CONFIRMACAO = 88.0

PALAVRAS_LIGACAO = {"DA", "DE", "DO", "DAS", "DOS", "E"}
PALAVRAS_BLOQUEIO = {
    "COMPETENCIA",
    "FOLHA",
    "PAGAMENTO",
    "SALARIO",
    "REMUNERACAO",
    "PROVENTOS",
    "DESCONTOS",
    "LIQUIDO",
    "TOTAL",
    "CARGO",
    "FUNCAO",
    "SETOR",
    "CBO",
    "MATRICULA",
    "ADMISSAO",
    "DEMISSAO",
    "DEMITIDO",
    "RESCISAO",
    "RESCINDIDO",
    "RESCINDIDOS",
    "UNIDADE",
    "EMPRESA",
    "PIS",
    "CPF",
    "CNPJ",
    "CTPS",
    "HORA",
    "HORAS",
    "DIAS",
}


@dataclass
class NomeExtraido:
    nome: str
    chave: str


def normalizar(texto: str) -> str:
    texto = texto or ""
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = texto.upper()
    texto = re.sub(r"[^A-Z0-9 ]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def tokens_nome(texto: str) -> List[str]:
    tokens = [t for t in normalizar(texto).split() if t not in PALAVRAS_LIGACAO]
    return [t for t in tokens if t not in PALAVRAS_BLOQUEIO]


def chave_nome(texto: str) -> str:
    return " ".join(tokens_nome(texto))


def similaridade(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if fuzz:
        return float(fuzz.ratio(a, b)) / 100.0
    return SequenceMatcher(None, a, b).ratio()


def token_eq(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(b) >= 2 and a.startswith(b):
        return True
    if len(a) >= 3 and b.startswith(a):
        return True
    return similaridade(a, b) >= 0.80


def eh_abreviacao_final(nome_oficial: str, nome_lido: str) -> bool:
    to = tokens_nome(nome_oficial)
    tl = tokens_nome(nome_lido)
    if not to or not tl or len(tl) > len(to):
        return False
    i = 0
    for token in tl:
        while i < len(to) and not token_eq(to[i], token):
            i += 1
        if i >= len(to):
            return False
        i += 1
    return True


def score_nome(nome_oficial: str, nome_lido: str) -> float:
    no = normalizar(nome_oficial)
    nl = normalizar(nome_lido)
    if not no or not nl:
        return 0.0
    if no == nl:
        return 100.0

    to = tokens_nome(nome_oficial)
    tl = tokens_nome(nome_lido)
    if not to or not tl:
        return 0.0

    sim_frase = similaridade(no, nl)
    sim_compacto = similaridade("".join(to), "".join(tl))

    encontrados = 0
    pos = 0
    for token in tl:
        while pos < len(to):
            if token_eq(to[pos], token):
                encontrados += 1
                pos += 1
                break
            pos += 1

    cobertura_lido = encontrados / len(tl)
    cobertura_oficial = encontrados / len(to)
    primeiro_ok = 1.0 if token_eq(to[0], tl[0]) else 0.0
    ultimo_ok = 1.0 if token_eq(to[-1], tl[-1]) else 0.0

    score = 100 * (
        0.38 * cobertura_lido
        + 0.27 * cobertura_oficial
        + 0.17 * sim_frase
        + 0.12 * sim_compacto
        + 0.04 * primeiro_ok
        + 0.02 * ultimo_ok
    )

    if eh_abreviacao_final(nome_oficial, nome_lido):
        score = max(score, 79.0)

    if len(tl) <= 2 and len(to) >= 4:
        score = min(score, 77.5)

    return round(max(0.0, min(score, 100.0)), 2)


def limpar_nome_texto(texto: str) -> str:
    texto = re.sub(r"\s+", " ", texto or "").strip()
    texto = re.sub(
        r"\b(AG|AGENCIA|CONTA|CPF|CNPJ|MATRICULA|CARGO|FUNCAO|SETOR|SALARIO|PROVENTOS|DESCONTOS|LIQUIDO|TOTAL)\b.*$",
        "",
        texto,
        flags=re.I,
    )
    texto = re.sub(r"\s+", " ", texto).strip(" -|:")
    return texto


def nome_plausivel(texto: str) -> bool:
    bruto = limpar_nome_texto(texto)
    if not bruto:
        return False

    norm = normalizar(bruto)
    if not norm:
        return False
    if re.search(r"\d", norm):
        return False
    if any(p in norm for p in PALAVRAS_BLOQUEIO):
        return False

    tokens = tokens_nome(norm)
    if len(tokens) < 2 or len(tokens) > 7:
        return False

    letras = sum(1 for c in norm if c.isalpha())
    if letras < 4:
        return False

    return True


def extrair_nome_da_linha(linha: str) -> str:
    linha = limpar_nome_texto(linha)
    linha = re.sub(r"^\s*\d+\s*[-.:]?\s*", "", linha).strip()
    linha = re.sub(r"\s+\d{2,}(?:\s+.*)?$", "", linha).strip()
    linha = re.split(r"\s{2,}", linha, maxsplit=1)[0].strip()
    return limpar_nome_texto(linha)


def extrair_candidatos_texto(texto: str) -> List[str]:
    if not texto:
        return []

    candidatos: list[str] = []
    linhas = [re.sub(r"\s+", " ", l).strip() for l in (texto or "").replace("\r", "\n").split("\n")]

    for idx, linha in enumerate(linhas):
        if not linha:
            continue

        upper = normalizar(linha)
        if not upper:
            continue

        if re.search(r"\bNOME\s*:", upper):
            m = re.search(
                r"NOME\s*:\s*(.+?)(?:\n\s*(?:AG\b|AGENCIA\b|CONTA\b|VALOR\b|CPF\b|CNPJ\b|MATRICULA\b|CARGO\b|FUNCAO\b|SETOR\b|PIS\b|CBO\b|SALARIO\b|PROVENTOS\b|DESCONTOS\b|LIQUIDO\b|TOTAL\b)|$)",
                linha,
                flags=re.I | re.S,
            )
            if m:
                nome = limpar_nome_texto(m.group(1))
                if nome_plausivel(nome):
                    candidatos.append(nome)

        if re.search(r"\bEMPR\.?\s*:", upper) and idx > 0:
            prev = extrair_nome_da_linha(linhas[idx - 1])
            if nome_plausivel(prev):
                candidatos.append(prev)

        if nome_plausivel(linha):
            candidatos.append(extrair_nome_da_linha(linha))

    return candidatos


def extrair_candidatos_pdf(caminho: Path) -> List[str]:
    doc = fitz.open(str(caminho))
    nomes: list[str] = []
    try:
        for pagina in doc:
            texto = pagina.get_text("text") or ""
            nomes.extend(extrair_candidatos_texto(texto))

            try:
                blocos = pagina.get_text("blocks") or []
                for bloco in blocos:
                    if len(bloco) > 4 and bloco[4]:
                        nomes.extend(extrair_candidatos_texto(str(bloco[4])))
            except Exception:
                pass
    finally:
        doc.close()

    return nomes


def unificar_nomes(nomes: Iterable[str]) -> List[NomeExtraido]:
    unicos: dict[str, NomeExtraido] = {}
    for nome in nomes:
        nome = limpar_nome_texto(nome)
        if not nome:
            continue
        chave = chave_nome(nome)
        if not chave or chave in unicos:
            continue
        unicos[chave] = NomeExtraido(nome=nome, chave=chave)
    return list(unicos.values())


def carregar_nomes_arquivo(caminho: Path) -> List[NomeExtraido]:
    ext = caminho.suffix.lower()

    if ext == ".txt":
        nomes = caminho.read_text(encoding="utf-8", errors="ignore").splitlines()
        return unificar_nomes(nomes)

    if ext in {".csv", ".xlsx", ".xls"}:
        if ext == ".csv":
            df = pd.read_csv(caminho, dtype=str, sep=None, engine="python")
        else:
            df = pd.read_excel(caminho, dtype=str)

        df = df.fillna("")
        colunas = list(df.columns)
        coluna_nome = next((c for c in colunas if "nome" in normalizar(str(c)).lower()), colunas[0] if colunas else None)
        if not coluna_nome:
            return []
        valores = (str(v) for v in df[coluna_nome].tolist() if str(v).strip() and str(v).strip().lower() != "nan")
        return unificar_nomes(valores)

    if ext == ".pdf":
        try:
            nomes = extrair_candidatos_pdf(caminho)
        except Exception:
            return []
        return unificar_nomes(nomes)

    return []


def comparar_nomes(anterior: List[NomeExtraido], atual: List[NomeExtraido]) -> dict:
    candidatos: list[tuple[float, int, int]] = []

    for i, nome_anterior in enumerate(anterior):
        for j, nome_atual in enumerate(atual):
            score = score_nome(nome_anterior.nome, nome_atual.nome)
            if score > 0:
                candidatos.append((score, i, j))

    candidatos.sort(key=lambda x: (-x[0], x[1], x[2]))

    match_anterior: dict[int, tuple[int, float]] = {}
    match_atual: dict[int, tuple[int, float]] = {}

    for score, i, j in candidatos:
        if score < MIN_SCORE_PAREAMENTO:
            continue
        if i in match_anterior or j in match_atual:
            continue
        match_anterior[i] = (j, score)
        match_atual[j] = (i, score)

    resultados = []
    rescindidos = []
    novos = []

    for i, nome in enumerate(anterior):
        if i in match_anterior:
            j, score = match_anterior[i]
            correspondente = atual[j]
            if score >= SCORE_CONFIRMACAO:
                status = "PRESENTE"
                observacao = "Correspondencia segura"
            else:
                status = "PRESENTE - CONFERIR"
                observacao = "Correspondencia aproximada"

            resultados.append(
                {
                    "nome_competencia_anterior": nome.nome,
                    "status": status,
                    "nome_correspondente_na_atual": correspondente.nome,
                    "score": round(score, 2),
                    "observacao": observacao,
                }
            )
        else:
            resultados.append(
                {
                    "nome_competencia_anterior": nome.nome,
                    "status": "POSSIVEL_RESCINDIDO",
                    "nome_correspondente_na_atual": "",
                    "score": 0.0,
                    "observacao": "Nao apareceu na competencia atual",
                }
            )
            rescindidos.append(nome.nome)

    for j, nome in enumerate(atual):
        if j not in match_atual:
            novos.append(nome.nome)

    return {
        "correspondencias": len(match_anterior),
        "possiveis_rescindidos": len(rescindidos),
        "novos_na_atual": len(novos),
        "rescindidos_lista": rescindidos,
        "novos_lista": novos,
        "resultados": resultados,
    }


def processar(competencia_anterior: Path, competencia_atual: Path, debug: bool) -> dict:
    anterior = carregar_nomes_arquivo(competencia_anterior)
    atual = carregar_nomes_arquivo(competencia_atual)

    if not anterior:
        raise ValueError("Nao foi possivel extrair nomes da competencia anterior.")
    if not atual:
        raise ValueError("Nao foi possivel extrair nomes da competencia atual.")

    if debug:
        print(f"[compare] anterior={competencia_anterior.name} nomes={len(anterior)}")
        print(f"[compare] atual={competencia_atual.name} nomes={len(atual)}")

    resultado = comparar_nomes(anterior, atual)

    return {
        "versao": VERSAO_SCRIPT,
        "arquivo_anterior": competencia_anterior.name,
        "arquivo_atual": competencia_atual.name,
        "total_anterior": len(anterior),
        "total_atual": len(atual),
        **resultado,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--anterior", type=str, default="")
    parser.add_argument("--atual", type=str, default="")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    anterior = Path(args.anterior)
    atual = Path(args.atual)

    if not anterior.exists():
        raise FileNotFoundError("Arquivo da competencia anterior nao encontrado.")
    if not atual.exists():
        raise FileNotFoundError("Arquivo da competencia atual nao encontrado.")

    resultado = processar(anterior, atual, args.debug)
    print(json.dumps(resultado, ensure_ascii=False))


if __name__ == "__main__":
    main()
