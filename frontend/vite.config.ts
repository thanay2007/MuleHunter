import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { execSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import path from 'node:path'

/**
 * The commit this bundle was built from, stamped into the portal footer.
 *
 * Reproducibility is one of this project's claims, so it is shown as chrome
 * rather than described in a README nobody opens on stage. Falls back rather
 * than throwing -- a missing git binary or a tarball export must not break the
 * build, and "unknown" is an honest answer.
 */
function gitSha(): string {
  try {
    return execSync('git rev-parse --short HEAD', {
      cwd: __dirname,
      stdio: ['ignore', 'pipe', 'ignore'],
    })
      .toString()
      .trim()
  } catch {
    /* git is not on PATH for this process; read the repo directly */
  }

  // Reading .git by hand keeps the footer honest on machines where the Vite
  // process cannot see the git binary -- which is common enough on Windows,
  // and "unknown" in the chrome undercuts the reproducibility claim it is
  // there to make.
  try {
    const gitDir = path.resolve(__dirname, '..', '.git')
    const head = readFileSync(path.join(gitDir, 'HEAD'), 'utf8').trim()
    if (!head.startsWith('ref:')) return head.slice(0, 7)
    const ref = head.slice(5).trim()
    return readFileSync(path.join(gitDir, ref), 'utf8').trim().slice(0, 7)
  } catch {
    return 'unknown'
  }
}

export default defineConfig({
  define: { __GIT_SHA__: JSON.stringify(gitSha()) },
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        // The graph renderer and the chart library are the two heavyweights,
        // and neither is needed to paint the first screen. Splitting them out
        // keeps the initial parse small, which matters on venue wifi where a
        // single 960 kB chunk is a visible pause before anything appears.
        manualChunks: {
          graph: ['react-force-graph-2d'],
          charts: ['recharts'],
        },
      },
    },
  },
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  server: {
    port: 5173,
    // Proxy keeps the frontend origin-relative: it calls /api/... and never
    // needs to know the backend host. Also sidesteps CORS entirely in dev.
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
})
