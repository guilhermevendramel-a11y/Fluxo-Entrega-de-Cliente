# -*- coding: utf-8 -*-
"""
Dependencias:
  pip install pymupdf pypdf rapidfuzz pandas openpyxl
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import unicodedata
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import fitz
import pandas as pd

try:
    from rapidfuzz import fuzz
except Exception:
    fuzz = None
    from difflib import SequenceMatcher

VERSAO_SCRIPT = "MAX_EXTRACAO_NEXTJS_V5"
MODO_MAXIMA_EXTRACAO = True

SCORE_OK = 88.0
SCORE_ABREV = 78.0
SCORE_CONFERIR = 68.0

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
    "WILKISON": "WILKSON",
    "WILKSON": "WILKISON",
    "CLEITON": "CLEYTON",
    "CLEYTON": "CLEITON",
    "TALISSON": "TALISON",
    "TALISON": "TALISSON",
    "JEFERSON": "JEFFERSON",
    "JEFFERSON": "JEFERSON",
    "NATANAEL": "NATANIEL",
    "NATANIEL": "NATANAEL",
}
STOP_RE = re.compile(r"^(AG|AGEN[CC]IA|AGENCIA|CONTA|VALOR|CPF|CNPJ)\b", re.I)


@dataclass
class Comprovante:
    arquivo: str
    pagina: int
    nome: str
    valor: str
    data_pagamento: str


def normalizar(s: str) -> str:
    s = s or ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.upper()
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokens_nome(s: str) -> List[str]:
    toks = [t for t in normalizar(s).split() if t not in PALAVRAS_LIGACAO]
    return [EQUIVALENCIAS.get(t, t) for t in toks]


def similaridade(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if fuzz:
        return float(fuzz.ratio(a, b)) / 100.0
    return SequenceMatcher(None, a, b).ratio()


def token_eq(a: str, b: str) -> bool:
    a = EQUIVALENCIAS.get(a, a)
    b = EQUIVALENCIAS.get(b, b)
    if a == b:
        return True
    if len(b) >= 2 and a.startswith(b):
        return True
    if len(a) >= 3 and b.startswith(a):
        return True
    return similaridade(a, b) >= 0.80


def truncado_final_ok(nome_oficial: str, nome_banco: str) -> bool:
    to = tokens_nome(nome_oficial)
    tb = tokens_nome(nome_banco)
    if not to or not tb or len(tb) > len(to):
        return False
    i = 0
    for b in tb:
        while i < len(to) and not token_eq(to[i], b):
            i += 1
        if i >= len(to):
            return False
        i += 1
    return True


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

    comp_o = "".join(to)
    comp_b = "".join(tb)
    sim_f = similaridade(no, nb)
    sim_c = similaridade(comp_o, comp_b)

    matches = 0
    pos = 0
    for b in tb:
        while pos < len(to):
            if token_eq(to[pos], b):
                matches += 1
                pos += 1
                break
            pos += 1

    cob_b = matches / len(tb)
    cob_o = matches / len(to)
    p_ok = 1.0 if token_eq(to[0], tb[0]) else 0.0
    u_ok = 1.0 if token_eq(to[-1], tb[-1]) else 0.0

    score = 100 * (0.38 * cob_b + 0.27 * cob_o + 0.18 * sim_f + 0.12 * sim_c + 0.03 * p_ok + 0.02 * u_ok)

    if truncado_final_ok(nome_oficial, nome_banco):
        score = max(score, 79.0)

    if len(tb) <= 2 and len(to) >= 4:
        score = min(score, 77.5)

    return round(max(0.0, min(score, 100.0)), 2)


def limpar_nome_extraido(nome: str) -> str:
    nome = re.sub(r"\s+", " ", nome or "").strip()
    for p in [r"\bAG\b.*$", r"\bAG[ÊE]NCIA\b.*$", r"\bAGENCIA\b.*$", r"\bCONTA\b.*$", r"\bVALOR\b.*$", r"\bCPF\b.*$", r"\bCNPJ\b.*$"]:
        nome = re.sub(p, "", nome, flags=re.I).strip()
    return re.sub(r"\s+", " ", nome).strip(" -|:")


def extrair_nome_page(texto: str, page: fitz.Page) -> Tuple[str, str]:
    txt = (texto or "").replace("\r", "\n")
    m = re.search(r"DADOS\s+DA\s+CONTA\s+CREDITADA\s*:?.*?NOME\s*:\s*(.+?)(?:\n\s*(?:AG|AG[ÊE]NCIA|AGENCIA|CONTA|VALOR|CPF|CNPJ)\b|$)", txt, re.I | re.S)
    if m:
        n = limpar_nome_extraido(m.group(1))
        if n:
            return n, "regex"

    linhas = [l.strip() for l in txt.split("\n")]
    for i, l in enumerate(linhas):
        if re.match(r"^NOME\s*:", l, re.I):
            rest = re.sub(r"^NOME\s*:\s*", "", l, flags=re.I).strip()
            if rest:
                return limpar_nome_extraido(rest), "linhas"
            parts = []
            for j in range(i + 1, min(i + 8, len(linhas))):
                if not linhas[j]:
                    continue
                if STOP_RE.match(normalizar(linhas[j])):
                    break
                parts.append(linhas[j])
            if parts:
                return limpar_nome_extraido(" ".join(parts)), "linhas"

    try:
        d = page.get_text("dict")
        texts = []
        for b in d.get("blocks", []):
            if b.get("type", 0) != 0:
                continue
            for ln in b.get("lines", []):
                s = " ".join((sp.get("text", "") or "").strip() for sp in ln.get("spans", []) if (sp.get("text", "") or "").strip())
                if s:
                    texts.append(s)
        for i, t in enumerate(texts):
            if re.search(r"\bNOME\b\s*:", t, re.I):
                rest = re.sub(r"^.*?\bNOME\b\s*:\s*", "", t, flags=re.I).strip()
                if rest:
                    return limpar_nome_extraido(rest), "blocos"
                for j in range(i + 1, min(i + 8, len(texts))):
                    if STOP_RE.match(normalizar(texts[j])):
                        break
                    if texts[j].strip():
                        return limpar_nome_extraido(texts[j]), "blocos"
    except Exception:
        pass

    return "", "nao_encontrado"


def extrair_valor(texto: str) -> str:
    m = re.search(r"Valor\s*[:\-]?\s*R\$\s*([\d\.]+,\d{2})", texto or "", re.I)
    return m.group(1) if m else ""


def extrair_data(texto: str) -> str:
    m = re.search(r"(?:Transfer[êe]ncia|Pagamento|Opera[cç][aã]o).*?em\s*(\d{2}/\d{2}/\d{4})", texto or "", re.I | re.S)
    return m.group(1) if m else ""


def carregar_relacao(path: Path) -> List[str]:
    ext = path.suffix.lower()
    if ext == ".txt":
        return [l.strip() for l in path.read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()]
    if ext == ".csv":
        df = pd.read_csv(path, sep=None, engine="python", dtype=str).fillna("")
    elif ext in {".xlsx", ".xls"}:
        df = pd.read_excel(path, dtype=str).fillna("")
    else:
        return []
    cols = list(df.columns)
    col = next((c for c in cols if "nome" in normalizar(str(c)).lower()), cols[0] if cols else None)
    if not col:
        return []
    return [str(v).strip() for v in df[col].tolist() if str(v).strip() and str(v).strip().lower() != "nan"]


def salvar_csv(path: Path, rows: List[dict], cols: List[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter=";")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def nome_seguro(nome: str) -> str:
    s = normalizar(nome).title()
    s = re.sub(r"[^A-Za-z0-9 _.-]+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return (s[:120] or "Sem_Nome").rstrip(" .")


def processar(pdf_path: Path, relacao_path: Path, saida_dir: Path, debug: bool) -> dict:
    saida_dir.mkdir(parents=True, exist_ok=True)
    extraidos = saida_dir / "extraidos"
    relatorios = saida_dir / "relatorios"
    database_dir = saida_dir / "database"
    logs_dir = saida_dir / "logs"
    for p in [extraidos, relatorios, database_dir, logs_dir]:
        p.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(level=logging.INFO if debug else logging.WARNING, format="%(asctime)s | %(message)s")

    nomes_relacao = carregar_relacao(relacao_path)
    doc = fitz.open(str(pdf_path))

    comprovantes: List[Comprovante] = []
    nomes_extraidos_pdf = 0

    for i in range(1, len(doc) + 1):
        page = doc[i - 1]
        txt = page.get_text("text") or ""
        nome, _ = extrair_nome_page(txt, page)
        if nome:
            nomes_extraidos_pdf += 1
        comprovantes.append(
            Comprovante(
                arquivo=pdf_path.name,
                pagina=i,
                nome=nome,
                valor=extrair_valor(txt),
                data_pagamento=extrair_data(txt),
            )
        )

    db_rows = [
        {
            "arquivo": c.arquivo,
            "pagina": c.pagina,
            "nome_comprovante": c.nome,
            "nome_normalizado": normalizar(c.nome),
            "valor": c.valor,
            "data_pagamento": c.data_pagamento,
        }
        for c in comprovantes
    ]
    salvar_csv(database_dir / "database_comprovantes.csv", db_rows, ["arquivo", "pagina", "nome_comprovante", "nome_normalizado", "valor", "data_pagamento"])

    # Etapa 1: calcula todos os scores
    tops_por_nome = {}
    all_pairs = []
    for idx, nome in enumerate(nomes_relacao):
        candidatos = []
        base = comprovantes if (MODO_MAXIMA_EXTRACAO or debug) else comprovantes
        for c in base:
            if not c.nome:
                continue
            s = score_nome(nome, c.nome)
            if s > 0:
                candidatos.append((s, c))
                all_pairs.append((s, idx, c))
        candidatos.sort(key=lambda x: x[0], reverse=True)
        tops_por_nome[idx] = candidatos[:10]

    # Etapa 2: resolve duplicidade por maior score
    all_pairs.sort(key=lambda x: (-x[0], x[1], x[2].pagina))
    usados = set()
    atrib = {}
    for s, idx, c in all_pairs:
        key = (c.arquivo, c.pagina)
        if idx in atrib:
            continue
        if key in usados:
            continue
        atrib[idx] = (c, s)
        usados.add(key)

    # Etapa 3: rescue faltantes
    for idx, tops in tops_por_nome.items():
        if idx in atrib or not tops:
            continue
        c, s = tops[0][1], tops[0][0]
        if s >= SCORE_CONFERIR or truncado_final_ok(nomes_relacao[idx], c.nome):
            atrib[idx] = (c, min(max(s, SCORE_CONFERIR), 77.9))

    linhas = []
    encontrados = []
    faltantes = []
    conferir = []
    cont = Counter()

    for idx, nome in enumerate(nomes_relacao):
        tops = tops_por_nome.get(idx, [])
        cand_txt = " | ".join([f"{sc:.2f}% p.{c.pagina} {c.nome}" for sc, c in tops[:5]])
        status = "NAO ENCONTRADO"
        motivo = "Nenhum candidato seguro"
        c = None
        s = 0.0

        if idx in atrib:
            c, s = atrib[idx]
            if truncado_final_ok(nome, c.nome) and s < SCORE_ABREV:
                s = SCORE_ABREV
            if s >= SCORE_OK:
                status = "OK"
                motivo = "Correspondencia segura"
            elif s >= SCORE_ABREV:
                status = "OK - CONFERIR ABREVIACAO"
                motivo = "Nome abreviado/truncado"
            elif s >= SCORE_CONFERIR:
                status = "CONFERIR MANUALMENTE"
                motivo = "Score intermediario"
            else:
                status = "NAO ENCONTRADO"

            if len(tokens_nome(c.nome)) <= 2 and len(tokens_nome(nome)) >= 4 and status == "OK":
                status = "CONFERIR MANUALMENTE"
                motivo = "Nome de banco curto (2 tokens), exige cautela"

        if status == "NAO ENCONTRADO":
            faltantes.append(nome)

        row = {
            "nome_relacao": nome,
            "status": status,
            "nome_encontrado_no_comprovante": c.nome if c else "",
            "arquivo_origem": c.arquivo if c else "",
            "pagina": c.pagina if c else "",
            "valor": c.valor if c else "",
            "data_pagamento": c.data_pagamento if c else "",
            "score": round(s, 2),
            "motivo": motivo,
            "candidatos_proximos": cand_txt,
        }
        linhas.append(row)
        cont[status] += 1
        if status.startswith("OK"):
            encontrados.append(row)
        if status == "CONFERIR MANUALMENTE":
            conferir.append(row)

    cols_rel = ["nome_relacao", "status", "nome_encontrado_no_comprovante", "arquivo_origem", "pagina", "valor", "data_pagamento", "score", "motivo", "candidatos_proximos"]
    salvar_csv(relatorios / "relatorio_conferencia_comprovantes.csv", linhas, cols_rel)
    salvar_csv(relatorios / "faltantes.csv", [r for r in linhas if r["status"] == "NAO ENCONTRADO"], cols_rel)
    salvar_csv(relatorios / "encontrados.csv", encontrados, cols_rel)
    salvar_csv(relatorios / "conferir_manualmente.csv", [r for r in linhas if "CONFERIR" in r["status"]], cols_rel)

    # debug faltantes top10
    debug_rows = []
    for idx, nome in enumerate(nomes_relacao):
        if linhas[idx]["status"] != "NAO ENCONTRADO":
            continue
        tops = tops_por_nome.get(idx, [])[:10]
        row = {"nome_relacao": nome}
        for i in range(10):
            if i < len(tops):
                sc, c = tops[i]
                row[f"top{i+1}_nome"] = c.nome
                row[f"top{i+1}_score"] = round(sc, 2)
                row[f"top{i+1}_pagina"] = c.pagina
            else:
                row[f"top{i+1}_nome"] = ""
                row[f"top{i+1}_score"] = ""
                row[f"top{i+1}_pagina"] = ""
        debug_rows.append(row)

    debug_cols = ["nome_relacao"] + [x for i in range(1, 11) for x in (f"top{i}_nome", f"top{i}_score", f"top{i}_pagina")]
    salvar_csv(relatorios / "debug_faltantes_top10.csv", debug_rows, debug_cols)

    # extrai pdfs
    for i, r in enumerate(linhas, start=1):
        if not r["status"].startswith("OK"):
            continue
        p = int(r["pagina"])
        novo = fitz.open()
        novo.insert_pdf(doc, from_page=p - 1, to_page=p - 1)
        novo.save(str(extraidos / f"{i:03d} - {nome_seguro(r['nome_relacao'])}.pdf"))
        novo.close()

    zip_path = saida_dir / "extraidos.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(extraidos.glob("*.pdf")):
            z.write(f, arcname=f.name)

    doc.close()

    result = {
        "versao": VERSAO_SCRIPT,
        "total_nomes": len(nomes_relacao),
        "encontrados": len([r for r in linhas if r["status"].startswith("OK")]),
        "faltantes": len([r for r in linhas if r["status"] == "NAO ENCONTRADO"]),
        "conferir_manualmente": len([r for r in linhas if "CONFERIR" in r["status"]]),
        "total_paginas_pdf": len(comprovantes),
        "nomes_extraidos_pdf": nomes_extraidos_pdf,
        "faltantes_lista": faltantes,
        "resultados": linhas,
        "arquivos": {
            "zip_extraidos": str(zip_path),
            "relatorio_csv": str(relatorios / "relatorio_conferencia_comprovantes.csv"),
            "saida_dir": str(saida_dir),
        },
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", type=str, default="")
    parser.add_argument("--relacao", type=str, default="")
    parser.add_argument("--saida", type=str, default="")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    base = Path(__file__).resolve().parent.parent
    pdf_fallback = next((p for p in (base / "entrada" / "comprovantes").glob("*.pdf")), None)
    rel_fallback = next((p for ext in ("*.txt", "*.csv", "*.xlsx", "*.xls") for p in (base / "entrada" / "relacao").glob(ext)), None)

    pdf_path = Path(args.pdf) if args.pdf else pdf_fallback
    rel_path = Path(args.relacao) if args.relacao else (base / "data" / "colaboradores.txt" if (base / "data" / "colaboradores.txt").exists() else rel_fallback)
    saida = Path(args.saida) if args.saida else (base / "saida")

    if not pdf_path or not Path(pdf_path).exists():
        raise FileNotFoundError("PDF nao encontrado.")
    if not rel_path or not Path(rel_path).exists():
        raise FileNotFoundError("Relacao nao encontrada.")

    res = processar(Path(pdf_path), Path(rel_path), Path(saida), args.debug)
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
