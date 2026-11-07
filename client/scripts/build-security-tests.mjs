import { build } from 'esbuild';

await build({
  entryPoints: ['test/securityEntry.ts'], bundle: true, platform: 'node', format: 'esm',
  outfile: 'test/.generated/security.mjs',
  define: { 'import.meta.env.DEV':'false', 'import.meta.env.PROD':'true', 'import.meta.env.VITE_API_BASE':'"/api"' },
});
