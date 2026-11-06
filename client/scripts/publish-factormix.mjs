import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";

const root = fileURLToPath(new URL("../../", import.meta.url));
const venv = resolve(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const python = process.env.FACTORMIX_PYTHON || (existsSync(venv) ? venv : "python");
const result = spawnSync(python, ["-m", "factormix.build_dashboard", ...process.argv.slice(2)], { cwd: root, stdio: "inherit", shell: false });
if (result.error) console.error(result.error.message);
process.exit(result.status ?? 1);
