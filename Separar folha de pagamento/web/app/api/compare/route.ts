import { NextResponse } from "next/server";
import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import path from "node:path";
import os from "node:os";
import { randomUUID } from "node:crypto";

export const runtime = "nodejs";

type PythonResult = {
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
  resultados: Array<Record<string, unknown>>;
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
  throw new Error("Python nao retornou JSON valido no stdout.");
}

export async function POST(request: Request) {
  const projectRoot = process.cwd();
  const scriptPath = path.join(projectRoot, "scripts", "comparar_competencias.py");
  const pythonBin = getPythonBin();

  const form = await request.formData();
  const competenciaAnterior = form.get("competencia_anterior") || form.get("anterior");
  const competenciaAtual = form.get("competencia_atual") || form.get("atual");
  const debug = String(form.get("debug") ?? "false") === "true";

  if (!(competenciaAnterior instanceof File)) {
    return NextResponse.json({ error: "Envie um arquivo em 'competencia_anterior'." }, { status: 400 });
  }
  if (!(competenciaAtual instanceof File)) {
    return NextResponse.json({ error: "Envie um arquivo em 'competencia_atual'." }, { status: 400 });
  }

  const jobId = randomUUID();
  const jobRoot = path.join(os.tmpdir(), "competencias-next", jobId);
  const inputDir = path.join(jobRoot, "input");
  await fs.mkdir(inputDir, { recursive: true });

  const anteriorPath = path.join(inputDir, competenciaAnterior.name || "competencia_anterior.pdf");
  const atualPath = path.join(inputDir, competenciaAtual.name || "competencia_atual.pdf");
  await fs.writeFile(anteriorPath, Buffer.from(await competenciaAnterior.arrayBuffer()));
  await fs.writeFile(atualPath, Buffer.from(await competenciaAtual.arrayBuffer()));

  const args = [
    scriptPath,
    "--anterior",
    anteriorPath,
    "--atual",
    atualPath,
    ...(debug ? ["--debug"] : []),
  ];

  console.log("[compare] python:", pythonBin);
  console.log("[compare] script:", scriptPath);
  console.log("[compare] anterior:", anteriorPath);
  console.log("[compare] atual:", atualPath);

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
        error: "Falha ao executar comparacao em Python.",
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
        error: "Python finalizou sem JSON valido.",
        details: String(e),
        stdout: execResult.stdout,
        stderr: execResult.stderr,
      },
      { status: 500 },
    );
  }

  console.log("[compare] anterior:", parsed.total_anterior);
  console.log("[compare] atual:", parsed.total_atual);
  console.log("[compare] correspondencias:", parsed.correspondencias);

  return NextResponse.json({
    ...parsed,
    job_id: jobId,
  });
}
