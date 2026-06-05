import { NextResponse } from "next/server";
import { promises as fs } from "node:fs";
import path from "node:path";
import os from "node:os";

export const runtime = "nodejs";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const job = searchParams.get("job") || "";
  const tipo = searchParams.get("tipo") || "";

  if (!job || !/^[a-f0-9-]+$/i.test(job)) {
    return NextResponse.json({ error: "job inválido." }, { status: 400 });
  }

  const jobRoot = path.join(os.tmpdir(), "comprovantes-next", job);
  const filePath =
    tipo === "zip"
      ? path.join(jobRoot, "output", "extraidos.zip")
      : path.join(jobRoot, "output", "relatorios", "relatorio_conferencia_comprovantes.csv");

  try {
    const data = await fs.readFile(filePath);
    const filename = tipo === "zip" ? "extraidos.zip" : "relatorio_conferencia_comprovantes.csv";
    const contentType = tipo === "zip" ? "application/zip" : "text/csv; charset=utf-8";

    return new NextResponse(data, {
      headers: {
        "Content-Type": contentType,
        "Content-Disposition": `attachment; filename="${filename}"`,
      },
    });
  } catch {
    return NextResponse.json({ error: "Arquivo não encontrado para esse job." }, { status: 404 });
  }
}
