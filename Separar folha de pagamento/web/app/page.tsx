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

type LinhaComparacao = {
  nome_competencia_anterior: string;
  status: string;
  nome_correspondente_na_atual: string;
  score: string | number;
  observacao: string;
};

type CompareApiResult = {
  versao?: string;
  arquivo_anterior?: string;
  arquivo_atual?: string;
  total_anterior: number;
  total_atual: number;
  correspondencias: number;
  possiveis_rescindidos: number;
  novos_na_atual: number;
  rescindidos_lista: string[];
  novos_lista: string[];
  resultados: LinhaComparacao[];
  error?: string;
};

const VERSAO_ESPERADA = "MAX_EXTRACAO_NEXTJS_V5";
const VERSAO_COMPARACAO_ESPERADA = "COMPARAR_COMPETENCIAS_V1";

export default function Home() {
  const [aba, setAba] = useState<"extrair" | "comparar">("extrair");

  const [pdf, setPdf] = useState<File | null>(null);
  const [relacao, setRelacao] = useState<File | null>(null);
  const [debug, setDebug] = useState(true);
  const [loading, setLoading] = useState(false);
  const [erro, setErro] = useState("");
  const [res, setRes] = useState<ApiResult | null>(null);

  const [competenciaAnterior, setCompetenciaAnterior] = useState<File | null>(null);
  const [competenciaAtual, setCompetenciaAtual] = useState<File | null>(null);
  const [debugComparacao, setDebugComparacao] = useState(true);
  const [loadingComparacao, setLoadingComparacao] = useState(false);
  const [erroComparacao, setErroComparacao] = useState("");
  const [resComparacao, setResComparacao] = useState<CompareApiResult | null>(null);

  const alertaVersao = useMemo(() => {
    if (!res) return "";
    if (res.versao !== VERSAO_ESPERADA) {
      return "A rota está chamando uma versão antiga do script Python.";
    }
    return "";
  }, [res]);

  const alertaVersaoComparacao = useMemo(() => {
    if (!resComparacao) return "";
    if (resComparacao.versao !== VERSAO_COMPARACAO_ESPERADA) {
      return "A comparação está usando uma versão antiga do script Python.";
    }
    return "";
  }, [resComparacao]);

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

  async function onSubmitComparacao(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!competenciaAnterior) {
      setErroComparacao("Selecione a folha da competência anterior.");
      return;
    }
    if (!competenciaAtual) {
      setErroComparacao("Selecione a folha da competência atual.");
      return;
    }

    setLoadingComparacao(true);
    setErroComparacao("");
    setResComparacao(null);

    const form = new FormData();
    form.append("competencia_anterior", competenciaAnterior);
    form.append("competencia_atual", competenciaAtual);
    form.append("debug", String(debugComparacao));

    try {
      const r = await fetch("/api/compare", { method: "POST", body: form });
      const data = (await r.json()) as CompareApiResult;
      if (!r.ok) {
        setErroComparacao(data.error || "Falha ao processar a comparação.");
        return;
      }
      setResComparacao(data);
    } catch {
      setErroComparacao("Falha de comunicação com o servidor.");
    } finally {
      setLoadingComparacao(false);
    }
  }

  return (
    <main className="relative min-h-screen overflow-hidden text-slate-800">
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute left-[-8rem] top-[-6rem] h-72 w-72 rounded-full bg-amber-200/50 blur-3xl" />
        <div className="absolute right-[-7rem] top-24 h-80 w-80 rounded-full bg-sky-200/55 blur-3xl" />
        <div className="absolute bottom-[-6rem] left-1/3 h-72 w-72 rounded-full bg-emerald-200/40 blur-3xl" />
      </div>

      <div className="relative mx-auto w-full max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <header className="rounded-[32px] border border-white/50 bg-white/70 p-6 shadow-[0_20px_70px_rgba(15,23,42,0.08)] backdrop-blur">
          <p className="text-sm font-semibold uppercase tracking-[0.28em] text-slate-500">Fluxo de entrega de cliente</p>
          <div className="mt-3 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <h1 className="text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">Extração e comparação de folhas</h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600 sm:text-base">
                Separe comprovantes por colaborador ou compare duas competências para identificar quem estava na anterior e não apareceu na atual.
              </p>
            </div>
            <div className="flex gap-2 rounded-2xl border border-slate-200 bg-slate-50 p-2">
              <button
                type="button"
                onClick={() => {
                  setAba("extrair");
                }}
                className={`rounded-xl px-4 py-2 text-sm font-semibold transition ${
                  aba === "extrair" ? "bg-slate-900 text-white shadow-sm" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                Extrair comprovantes
              </button>
              <button
                type="button"
                onClick={() => {
                  setAba("comparar");
                }}
                className={`rounded-xl px-4 py-2 text-sm font-semibold transition ${
                  aba === "comparar" ? "bg-amber-600 text-white shadow-sm" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                Comparar competências
              </button>
            </div>
          </div>
        </header>

        {aba === "extrair" ? (
          <section className="mt-6 grid gap-6 lg:grid-cols-[1.05fr_0.95fr]">
            <form onSubmit={onSubmit} className="space-y-5 rounded-[28px] border border-white/60 bg-white/80 p-6 shadow-[0_24px_80px_rgba(15,23,42,0.10)] backdrop-blur">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-500">Fluxo 01</p>
                  <h2 className="text-2xl font-semibold text-slate-900">Extração de comprovantes</h2>
                </div>
                <span className="rounded-full bg-slate-900 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-white">
                  PDF + relação
                </span>
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700">PDF de comprovantes</label>
                <input
                  type="file"
                  accept="application/pdf"
                  onChange={(e) => {
                    setPdf(e.target.files?.[0] ?? null);
                  }}
                  className="block w-full rounded-2xl border border-slate-300 bg-white p-3 text-sm shadow-sm outline-none transition focus:border-slate-900"
                />
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700">Relação de colaboradores (opcional: .txt/.csv/.xlsx)</label>
                <input
                  type="file"
                  accept=".txt,.csv,.xlsx,.xls"
                  onChange={(e) => {
                    setRelacao(e.target.files?.[0] ?? null);
                  }}
                  className="block w-full rounded-2xl border border-slate-300 bg-white p-3 text-sm shadow-sm outline-none transition focus:border-slate-900"
                />
                <p className="mt-2 text-xs text-slate-500">Se não enviar, o sistema usa `data/colaboradores.txt`.</p>
              </div>

              <label className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={debug}
                  onChange={(e) => {
                    setDebug(e.target.checked);
                  }}
                  className="h-4 w-4 rounded border-slate-300"
                />
                Modo debug para revisar candidatos e incompatibilidades
              </label>

              <button
                disabled={loading}
                className="inline-flex items-center justify-center rounded-2xl bg-slate-900 px-5 py-3 text-sm font-semibold text-white transition hover:-translate-y-0.5 hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loading ? "Processando..." : "Processar comprovantes"}
              </button>

              {erro ? <p className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">{erro}</p> : null}
            </form>

            <div className="space-y-6">
              <div className="rounded-[28px] border border-white/60 bg-white/75 p-6 shadow-[0_24px_80px_rgba(15,23,42,0.08)] backdrop-blur">
                <p className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-500">O que sai daqui</p>
                <h2 className="mt-1 text-2xl font-semibold text-slate-900">Separação por colaborador</h2>
                <p className="mt-3 text-sm leading-6 text-slate-600">
                  Faz a leitura do PDF, cruza com a relação enviada e gera relatórios com encontrados, faltantes e itens para conferência manual.
                </p>
                <div className="mt-5 grid gap-3 sm:grid-cols-2">
                  <div className="rounded-2xl bg-slate-900 p-4 text-white">
                    <p className="text-xs uppercase tracking-[0.2em] text-slate-300">Saída 01</p>
                    <p className="mt-1 text-lg font-semibold">ZIP com PDFs extraídos</p>
                  </div>
                  <div className="rounded-2xl bg-emerald-600 p-4 text-white">
                    <p className="text-xs uppercase tracking-[0.2em] text-emerald-100">Saída 02</p>
                    <p className="mt-1 text-lg font-semibold">Relatório CSV com status</p>
                  </div>
                </div>
              </div>

              {res ? (
                <div className="rounded-[28px] border border-white/60 bg-white/80 p-6 shadow-[0_24px_80px_rgba(15,23,42,0.08)] backdrop-blur">
                  {alertaVersao ? (
                    <p className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-semibold text-amber-900">{alertaVersao}</p>
                  ) : null}

                  <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                    <Metric label="Versão" value={res.versao || "-"} />
                    <Metric label="Total de nomes" value={res.total_nomes} />
                    <Metric label="Encontrados" value={res.encontrados} />
                    <Metric label="Faltantes" value={res.faltantes} />
                    <Metric label="Conferir manualmente" value={res.conferir_manualmente} />
                    <Metric label="Páginas PDF" value={res.total_paginas_pdf} />
                  </div>

                  <div className="mt-4 flex flex-wrap gap-3">
                    {res.downloads?.zip ? (
                      <a className="rounded-2xl bg-emerald-600 px-4 py-3 text-sm font-semibold text-white transition hover:-translate-y-0.5 hover:bg-emerald-500" href={res.downloads.zip}>
                        Baixar ZIP
                      </a>
                    ) : null}
                    {res.downloads?.csv ? (
                      <a className="rounded-2xl bg-blue-600 px-4 py-3 text-sm font-semibold text-white transition hover:-translate-y-0.5 hover:bg-blue-500" href={res.downloads.csv}>
                        Baixar CSV
                      </a>
                    ) : null}
                  </div>
                </div>
              ) : null}

              {res ? (
                <div className="rounded-[28px] border border-white/60 bg-white/80 p-6 shadow-[0_24px_80px_rgba(15,23,42,0.08)] backdrop-blur">
                  <h3 className="text-lg font-semibold text-slate-900">Faltantes</h3>
                  {res.faltantes_lista.length === 0 ? (
                    <p className="mt-3 text-sm text-slate-600">Nenhum faltante.</p>
                  ) : (
                    <ul className="mt-3 grid gap-2 text-sm text-slate-700 sm:grid-cols-2">
                      {res.faltantes_lista.map((n) => (
                        <li key={n} className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2">
                          {n}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ) : null}
            </div>

            {res ? (
              <div className="lg:col-span-2 rounded-[28px] border border-white/60 bg-white/80 p-6 shadow-[0_24px_80px_rgba(15,23,42,0.08)] backdrop-blur">
                <h3 className="mb-4 text-lg font-semibold text-slate-900">Tabela completa</h3>
                <div className="max-h-[560px] overflow-auto rounded-2xl border border-slate-200">
                  <table className="min-w-full text-sm">
                    <thead className="sticky top-0 bg-slate-100 text-left text-slate-700">
                      <tr>
                        <th className="py-3 pl-4 pr-3 font-semibold">Nome relação</th>
                        <th className="py-3 pr-3 font-semibold">Status</th>
                        <th className="py-3 pr-3 font-semibold">Nome comprovante</th>
                        <th className="py-3 pr-3 font-semibold">Arquivo</th>
                        <th className="py-3 pr-3 font-semibold">Página</th>
                        <th className="py-3 pr-3 font-semibold">Score</th>
                        <th className="py-3 pr-4 font-semibold">Motivo</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 bg-white">
                      {res.resultados.map((r, i) => (
                        <tr key={`${r.nome_relacao}-${i}`} className="align-top">
                          <td className="py-3 pl-4 pr-3 font-medium text-slate-900">{r.nome_relacao}</td>
                          <td className="py-3 pr-3 text-slate-700">{r.status}</td>
                          <td className="py-3 pr-3 text-slate-700">{r.nome_encontrado_no_comprovante || "-"}</td>
                          <td className="py-3 pr-3 text-slate-700">{r.arquivo_origem || "-"}</td>
                          <td className="py-3 pr-3 text-slate-700">{r.pagina || "-"}</td>
                          <td className="py-3 pr-3 text-slate-700">{r.score}</td>
                          <td className="py-3 pr-4 text-slate-700">{r.motivo}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : null}
          </section>
        ) : (
          <section className="mt-6 grid gap-6 lg:grid-cols-[1.05fr_0.95fr]">
            <form onSubmit={onSubmitComparacao} className="space-y-5 rounded-[28px] border border-white/60 bg-white/80 p-6 shadow-[0_24px_80px_rgba(15,23,42,0.10)] backdrop-blur">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-500">Fluxo 02</p>
                  <h2 className="text-2xl font-semibold text-slate-900">Comparação de competências</h2>
                </div>
                <span className="rounded-full bg-amber-500 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-white">
                  Anterior x atual
                </span>
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700">Folha da competência anterior</label>
                <input
                  type="file"
                  accept=".pdf,.txt,.csv,.xlsx,.xls"
                  onChange={(e) => {
                    setCompetenciaAnterior(e.target.files?.[0] ?? null);
                  }}
                  className="block w-full rounded-2xl border border-slate-300 bg-white p-3 text-sm shadow-sm outline-none transition focus:border-slate-900"
                />
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700">Folha da competência atual</label>
                <input
                  type="file"
                  accept=".pdf,.txt,.csv,.xlsx,.xls"
                  onChange={(e) => {
                    setCompetenciaAtual(e.target.files?.[0] ?? null);
                  }}
                  className="block w-full rounded-2xl border border-slate-300 bg-white p-3 text-sm shadow-sm outline-none transition focus:border-slate-900"
                />
                <p className="mt-2 text-xs text-slate-500">Se os nomes estiverem abreviados, a comparação tenta reconciliar automaticamente antes de marcar como faltante.</p>
              </div>

              <label className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={debugComparacao}
                  onChange={(e) => {
                    setDebugComparacao(e.target.checked);
                  }}
                  className="h-4 w-4 rounded border-slate-300"
                />
                Modo debug para retornar mais detalhes da correspondência
              </label>

              <button
                disabled={loadingComparacao}
                className="inline-flex items-center justify-center rounded-2xl bg-amber-600 px-5 py-3 text-sm font-semibold text-white transition hover:-translate-y-0.5 hover:bg-amber-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loadingComparacao ? "Comparando..." : "Comparar competências"}
              </button>

              {erroComparacao ? <p className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">{erroComparacao}</p> : null}
            </form>

            <div className="space-y-6">
              <div className="rounded-[28px] border border-white/60 bg-white/75 p-6 shadow-[0_24px_80px_rgba(15,23,42,0.08)] backdrop-blur">
                <p className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-500">O que você recebe</p>
                <h2 className="mt-1 text-2xl font-semibold text-slate-900">Quem saiu e quem entrou</h2>
                <p className="mt-3 text-sm leading-6 text-slate-600">
                  A rotina cruza os nomes da competência anterior com a atual e lista os colaboradores que não apareceram novamente, tratando isso como possíveis rescindidos.
                </p>
                <div className="mt-5 grid gap-3 sm:grid-cols-2">
                  <div className="rounded-2xl bg-amber-600 p-4 text-white">
                    <p className="text-xs uppercase tracking-[0.2em] text-amber-100">Saída 01</p>
                    <p className="mt-1 text-lg font-semibold">Possíveis rescindidos</p>
                  </div>
                  <div className="rounded-2xl bg-slate-900 p-4 text-white">
                    <p className="text-xs uppercase tracking-[0.2em] text-slate-300">Saída 02</p>
                    <p className="mt-1 text-lg font-semibold">Novos na competência atual</p>
                  </div>
                </div>
              </div>

              {resComparacao ? (
                <div className="rounded-[28px] border border-white/60 bg-white/80 p-6 shadow-[0_24px_80px_rgba(15,23,42,0.08)] backdrop-blur">
                  {alertaVersaoComparacao ? (
                    <p className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-semibold text-amber-900">{alertaVersaoComparacao}</p>
                  ) : null}

                  <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                    <Metric label="Competência anterior" value={resComparacao.total_anterior} />
                    <Metric label="Competência atual" value={resComparacao.total_atual} />
                    <Metric label="Correspondências" value={resComparacao.correspondencias} />
                    <Metric label="Possíveis rescindidos" value={resComparacao.possiveis_rescindidos} />
                    <Metric label="Novos na atual" value={resComparacao.novos_na_atual} />
                    <Metric label="Versão" value={resComparacao.versao || "-"} />
                  </div>
                </div>
              ) : null}

              {resComparacao ? (
                <div className="rounded-[28px] border border-white/60 bg-white/80 p-6 shadow-[0_24px_80px_rgba(15,23,42,0.08)] backdrop-blur">
                  <h3 className="text-lg font-semibold text-slate-900">Possíveis rescindidos</h3>
                  {resComparacao.rescindidos_lista.length === 0 ? (
                    <p className="mt-3 text-sm text-slate-600">Nenhum nome ficou de fora da competência atual.</p>
                  ) : (
                    <ul className="mt-3 grid gap-2 text-sm text-slate-700 sm:grid-cols-2">
                      {resComparacao.rescindidos_lista.map((n) => (
                        <li key={n} className="rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2">
                          {n}
                        </li>
                      ))}
                    </ul>
                  )}

                  <h3 className="mt-6 text-lg font-semibold text-slate-900">Novos na competência atual</h3>
                  {resComparacao.novos_lista.length === 0 ? (
                    <p className="mt-3 text-sm text-slate-600">Nenhum nome novo apareceu na competência atual.</p>
                  ) : (
                    <ul className="mt-3 grid gap-2 text-sm text-slate-700 sm:grid-cols-2">
                      {resComparacao.novos_lista.map((n) => (
                        <li key={n} className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2">
                          {n}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ) : null}
            </div>

            {resComparacao ? (
              <div className="lg:col-span-2 rounded-[28px] border border-white/60 bg-white/80 p-6 shadow-[0_24px_80px_rgba(15,23,42,0.08)] backdrop-blur">
                <h3 className="mb-4 text-lg font-semibold text-slate-900">Detalhes da comparação</h3>
                <div className="max-h-[560px] overflow-auto rounded-2xl border border-slate-200">
                  <table className="min-w-full text-sm">
                    <thead className="sticky top-0 bg-slate-100 text-left text-slate-700">
                      <tr>
                        <th className="py-3 pl-4 pr-3 font-semibold">Competência anterior</th>
                        <th className="py-3 pr-3 font-semibold">Status</th>
                        <th className="py-3 pr-3 font-semibold">Correspondente na atual</th>
                        <th className="py-3 pr-3 font-semibold">Score</th>
                        <th className="py-3 pr-4 font-semibold">Observação</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 bg-white">
                      {resComparacao.resultados.map((r, i) => (
                        <tr key={`${r.nome_competencia_anterior}-${i}`} className="align-top">
                          <td className="py-3 pl-4 pr-3 font-medium text-slate-900">{r.nome_competencia_anterior}</td>
                          <td className="py-3 pr-3 text-slate-700">{r.status}</td>
                          <td className="py-3 pr-3 text-slate-700">{r.nome_correspondente_na_atual || "-"}</td>
                          <td className="py-3 pr-3 text-slate-700">{r.score}</td>
                          <td className="py-3 pr-4 text-slate-700">{r.observacao}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : null}
          </section>
        )}
      </div>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">{label}</p>
      <p className="mt-1 text-lg font-semibold text-slate-900">{value}</p>
    </div>
  );
}
