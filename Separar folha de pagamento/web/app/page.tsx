"use client";

import { FormEvent, useMemo, useState } from "react";

type Linha = {
  nome_relacao: string;
  status: string;
  nome_encontrado_no_comprovante: string;
  arquivo_origem: string;
  pagina: string | number;
  valor: string;
  data_pagamento: string;
  score: string | number;
  motivo: string;
  candidatos_proximos: string;
};

type ApiResult = {
  versao?: string;
  total_nomes: number;
  encontrados: number;
  faltantes: number;
  conferir_manualmente: number;
  total_paginas_pdf: number;
  nomes_extraidos_pdf: number;
  faltantes_lista: string[];
  resultados: Linha[];
  downloads?: { zip?: string; csv?: string };
  error?: string;
};

const VERSAO_ESPERADA = "MAX_EXTRACAO_NEXTJS_V5";

export default function Home() {
  const [pdf, setPdf] = useState<File | null>(null);
  const [relacao, setRelacao] = useState<File | null>(null);
  const [debug, setDebug] = useState(true);
  const [loading, setLoading] = useState(false);
  const [erro, setErro] = useState("");
  const [res, setRes] = useState<ApiResult | null>(null);

  const alertaVersao = useMemo(() => {
    if (!res) return "";
    if (res.versao !== VERSAO_ESPERADA) {
      return "A rota está chamando uma versão antiga do script Python.";
    }
    return "";
  }, [res]);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!pdf) {
      setErro("Selecione o PDF de comprovantes.");
      return;
    }

    setLoading(true);
    setErro("");
    setRes(null);

    const form = new FormData();
    form.append("pdf", pdf);
    if (relacao) form.append("relacao", relacao);
    form.append("debug", String(debug));

    try {
      const r = await fetch("/api/extract", { method: "POST", body: form });
      const data = (await r.json()) as ApiResult;
      if (!r.ok) {
        setErro(data.error || "Falha ao processar extração.");
        return;
      }
      setRes(data);
    } catch {
      setErro("Falha de comunicação com o servidor.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto min-h-screen w-full max-w-7xl px-4 py-10 text-slate-800 sm:px-8">
      <h1 className="text-3xl font-bold">Extração de Comprovantes</h1>
      <p className="mt-2 text-sm text-slate-600">Upload do PDF e extração máxima por colaborador.</p>

      <form onSubmit={onSubmit} className="mt-6 space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div>
          <label className="mb-2 block text-sm font-medium">PDF de comprovantes</label>
          <input type="file" accept="application/pdf" onChange={(e) => setPdf(e.target.files?.[0] ?? null)} className="block w-full rounded-md border border-slate-300 p-2 text-sm" />
        </div>

        <div>
          <label className="mb-2 block text-sm font-medium">Relação de colaboradores (opcional: .txt/.csv/.xlsx)</label>
          <input type="file" accept=".txt,.csv,.xlsx,.xls" onChange={(e) => setRelacao(e.target.files?.[0] ?? null)} className="block w-full rounded-md border border-slate-300 p-2 text-sm" />
          <p className="mt-1 text-xs text-slate-500">Se não enviar, usa `data/colaboradores.txt`.</p>
        </div>

        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={debug} onChange={(e) => setDebug(e.target.checked)} />
          Modo debug (compara colaboradores com todos os comprovantes)
        </label>

        <button disabled={loading} className="rounded-md bg-slate-900 px-5 py-2 text-sm font-semibold text-white hover:bg-slate-700 disabled:opacity-50">
          {loading ? "Processando..." : "Processar"}
        </button>

        {erro ? <p className="text-sm font-medium text-red-600">{erro}</p> : null}
      </form>

      {res ? (
        <section className="mt-8 space-y-4">
          {alertaVersao ? <p className="rounded-md bg-amber-100 p-3 text-sm font-semibold text-amber-900">{alertaVersao}</p> : null}

          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <p><strong>Versão:</strong> {res.versao}</p>
            <p><strong>Total de nomes:</strong> {res.total_nomes}</p>
            <p><strong>Encontrados:</strong> {res.encontrados}</p>
            <p><strong>Faltantes:</strong> {res.faltantes}</p>
            <p><strong>Conferir manualmente:</strong> {res.conferir_manualmente}</p>
            <p><strong>Total de páginas PDF:</strong> {res.total_paginas_pdf}</p>
            <p><strong>Nomes extraídos do PDF:</strong> {res.nomes_extraidos_pdf}</p>

            <div className="mt-3 flex gap-3">
              {res.downloads?.zip ? (
                <a className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-semibold text-white" href={res.downloads.zip}>
                  Baixar ZIP dos PDFs
                </a>
              ) : null}
              {res.downloads?.csv ? (
                <a className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white" href={res.downloads.csv}>
                  Baixar relatório CSV
                </a>
              ) : null}
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="mb-2 text-lg font-semibold">Faltantes</h2>
            {res.faltantes_lista.length === 0 ? <p className="text-sm text-slate-600">Nenhum faltante.</p> : (
              <ul className="list-disc pl-6 text-sm">
                {res.faltantes_lista.map((n) => <li key={n}>{n}</li>)}
              </ul>
            )}
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="mb-3 text-lg font-semibold">Tabela completa</h2>
            <div className="max-h-[560px] overflow-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-left">
                    <th className="py-2 pr-3">Nome relação</th>
                    <th className="py-2 pr-3">Status</th>
                    <th className="py-2 pr-3">Nome comprovante</th>
                    <th className="py-2 pr-3">Arquivo</th>
                    <th className="py-2 pr-3">Página</th>
                    <th className="py-2 pr-3">Score</th>
                    <th className="py-2 pr-3">Motivo</th>
                  </tr>
                </thead>
                <tbody>
                  {res.resultados.map((r, i) => (
                    <tr key={`${r.nome_relacao}-${i}`} className="border-b border-slate-100">
                      <td className="py-2 pr-3">{r.nome_relacao}</td>
                      <td className="py-2 pr-3">{r.status}</td>
                      <td className="py-2 pr-3">{r.nome_encontrado_no_comprovante || "-"}</td>
                      <td className="py-2 pr-3">{r.arquivo_origem || "-"}</td>
                      <td className="py-2 pr-3">{r.pagina || "-"}</td>
                      <td className="py-2 pr-3">{r.score}</td>
                      <td className="py-2 pr-3">{r.motivo}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      ) : null}
    </main>
  );
}
