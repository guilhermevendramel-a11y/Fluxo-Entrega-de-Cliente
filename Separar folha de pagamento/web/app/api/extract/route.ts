import { NextResponse } from "next/server";
import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import path from "node:path";
import os from "node:os";
import { randomUUID } from "node:crypto";

export const runtime = "nodejs";

type PythonResult = {
  versao?: string;
  total_nomes: number;
  encontrados: number;
  faltantes: number;
  conferir_manualmente: number;
  total_paginas_pdf: number;
  nomes_extraidos_pdf: number;
  faltantes_lista: string[];
  resultados: Array<Record<string, unknown>>;
  arquivos?: {
    zip_extraidos?: string;
    relatorio_csv?: string;
    saida_dir?: string;
  };
};

function getPythonBin(): string {
  return process.env.PYTHON_BIN || "python";
}

function parseLastJson(stdout: string): PythonResult {
  const lines = stdout.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
  for (let i = lines.length - 1; i >= 0; i -= 1) {
    try {
      return JSON.parse(lines[i]) as PythonResult;
    } catch {
      // continue
    }
  }
  throw new Error("Python não retornou JSON válido no stdout.");
}

export async function POST(request: Request) {
  const projectRoot = process.cwd();
  const scriptPath = path.join(projectRoot, "scripts", "extrair_comprovantes.py");
  const pythonBin = getPythonBin();

  const form = await request.formData();
  const pdf = form.get("pdf");
  const relacao = form.get("relacao");
  const debug = String(form.get("debug") ?? "false") === "true";

  if (!(pdf instanceof File)) {
    return NextResponse.json({ error: "Envie um PDF em 'pdf'." }, { status: 400 });
  }

  const jobId = randomUUID();
  const jobRoot = path.join(os.tmpdir(), "comprovantes-next", jobId);
  const inputDir = path.join(jobRoot, "input");
  const outputDir = path.join(jobRoot, "output");
  await fs.mkdir(inputDir, { recursive: true });
  await fs.mkdir(outputDir, { recursive: true });

  const pdfPath = path.join(inputDir, pdf.name || "comprovantes.pdf");
  await fs.writeFile(pdfPath, Buffer.from(await pdf.arrayBuffer()));

  let relacaoPath = path.join(projectRoot, "data", "colaboradores.txt");
  if (relacao instanceof File && relacao.size > 0) {
    relacaoPath = path.join(inputDir, relacao.name || "colaboradores.txt");
    await fs.writeFile(relacaoPath, Buffer.from(await relacao.arrayBuffer()));
  }

  const args = [
    scriptPath,
    "--pdf",
    pdfPath,
    "--relacao",
    relacaoPath,
    "--saida",
    outputDir,
    ...(debug ? ["--debug"] : []),
  ];

  console.log("[extract] python:", pythonBin);
  console.log("[extract] script:", scriptPath);
  console.log("[extract] pdf:", pdfPath);
  console.log("[extract] relacao:", relacaoPath);

  const execResult = await new Promise<{ stdout: string; stderr: string; code: number | null }>((resolve) => {
    const child = spawn(pythonBin, args, { cwd: projectRoot, stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (d) => {
      stdout += String(d);
    });
    child.stderr.on("data", (d) => {
      stderr += String(d);
    });
    child.on("close", (code) => resolve({ stdout, stderr, code }));
  });

  if (execResult.code !== 0) {
    return NextResponse.json(
      {
        error: "Falha ao executar Python.",
        details: execResult.stderr || execResult.stdout || "Sem detalhes.",
      },
      { status: 500 },
    );
  }

  let parsed: PythonResult;
  try {
    parsed = parseLastJson(execResult.stdout);
  } catch (e) {
    return NextResponse.json(
      {
        error: "Python finalizou sem JSON válido.",
        details: String(e),
        stdout: execResult.stdout,
        stderr: execResult.stderr,
      },
      { status: 500 },
    );
  }

  console.log("[extract] paginas:", parsed.total_paginas_pdf);
  console.log("[extract] nomes_extraidos_pdf:", parsed.nomes_extraidos_pdf);
  console.log("[extract] nomes_relacao:", parsed.total_nomes);

  const zipPath = path.join(outputDir, "extraidos.zip");
  const csvPath = path.join(outputDir, "relatorios", "relatorio_conferencia_comprovantes.csv");

  return NextResponse.json({
    ...parsed,
    job_id: jobId,
    downloads: {
      zip: `/api/extract/download?job=${encodeURIComponent(jobId)}&tipo=zip`,
      csv: `/api/extract/download?job=${encodeURIComponent(jobId)}&tipo=csv`,
    },
    _interno: {
      output_dir: outputDir,
      zip_path: zipPath,
      csv_path: csvPath,
    },
  });
}
